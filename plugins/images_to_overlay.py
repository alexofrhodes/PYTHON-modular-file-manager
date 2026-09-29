"""Image Overlay — bake text / QR / icons onto images; save layouts and field presets."""

from __future__ import annotations

import argparse
import copy
import sys
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, messagebox, simpledialog, ttk

from PIL import Image

try:
    from PIL import ImageTk

    _TK_PIL = True
except Exception:
    _TK_PIL = False

try:
    from plugins import import_host
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from plugins import import_host

_host = import_host()
BaseFileOperation = _host.BaseFileOperation
plugin_entry = _host.plugin_entry

from plugins import overlay_engine as eng

_SIDEBAR_W = 240
_HANDLE = 8


def _notify(parent, msg):
    messagebox.showinfo("Image Overlay", msg, parent=parent)


def _ask_yes_no(parent, title, msg):
    return messagebox.askyesno(title, msg, parent=parent)


class OverlayEditorDialog(tk.Toplevel):
    """Interactive overlay editor for one image."""

    def __init__(self, parent, image_path: str, *, initial_spec=None, initial_fields=None):
        super().__init__(parent)
        self.title("Image Overlay")
        self.resizable(True, True)
        self.transient(parent)
        self.grab_set()

        self.image_path = str(image_path)
        self.result_spec = None
        self.result_fields = None
        self._photo = None
        self._preview_job = None
        self._suppress = False
        self._el_enabled = {}
        self._el_labels = {}
        self._preview_geom = None
        self._drag = None

        self.spec = eng.sanitize_overlay_spec(initial_spec) if initial_spec else eng.default_overlay_spec()
        self.fields = dict(initial_fields or {})
        # Seed element values from fields
        eng.apply_fields_to_spec(self.spec, self.fields)
        for el in self.spec["elements"]:
            eid = el.get("id")
            if eid and str(el.get("value") or "").strip() and eid not in self.fields:
                self.fields[eid] = str(el.get("value"))
        self._fresh = not bool(initial_spec)
        self.selected_id = self.spec["elements"][0]["id"]

        shell = ttk.Frame(self, padding=4)
        shell.pack(fill=tk.BOTH, expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(1, weight=1)

        header = ttk.Frame(shell)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 4))
        ttk.Label(header, text=Path(self.image_path).name, font=("Segoe UI Semibold", 10)).pack(side="left")

        body = ttk.Frame(shell)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, minsize=_SIDEBAR_W, weight=0)
        body.rowconfigure(0, weight=1)

        preview_wrap = ttk.Frame(body, padding=4)
        preview_wrap.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        preview_wrap.columnconfigure(0, weight=1)
        preview_wrap.rowconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(preview_wrap, highlightthickness=0, bg="#0f172a", cursor="arrow")
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        preview_wrap.bind("<Configure>", self._on_preview_configure)
        self.preview_canvas.bind("<Button-1>", self._on_preview_down)
        self.preview_canvas.bind("<B1-Motion>", self._on_preview_drag)
        self.preview_canvas.bind("<ButtonRelease-1>", self._on_preview_up)

        side = ttk.Frame(body, padding=3)
        side.grid(row=0, column=1, sticky="nsew")
        side.columnconfigure(0, weight=1)

        top = ttk.Frame(side)
        top.grid(row=0, column=0, sticky="ew")
        self.mode_var = tk.StringVar(value=self.spec.get("mode") or "on_poster")
        ttk.Radiobutton(top, text="Poster", value="on_poster", variable=self.mode_var, command=self._on_mode_change).pack(
            side="left"
        )
        ttk.Radiobutton(top, text="A4", value="on_page", variable=self.mode_var, command=self._on_mode_change).pack(
            side="left", padx=(4, 0)
        )
        self.orient_var = tk.StringVar(value=self.spec.get("orientation") or "auto")
        self.orient_combo = ttk.Combobox(
            top, textvariable=self.orient_var, values=("auto", "portrait", "landscape"), state="readonly", width=10
        )
        self.orient_combo.pack(side="right")
        self.orient_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_orient_change())
        self._sync_orient_state()

        # Layout templates
        tmpl = ttk.LabelFrame(side, text="Layout", padding=2)
        tmpl.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        self.template_var = tk.StringVar()
        self.template_combo = ttk.Combobox(tmpl, textvariable=self.template_var, state="readonly", width=12)
        self.template_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(tmpl, text="Load", width=4, command=self._load_layout).pack(side="left", padx=(2, 0))
        ttk.Button(tmpl, text="Save", width=4, command=self._save_layout).pack(side="left", padx=(2, 0))
        ttk.Button(tmpl, text="Del", width=3, command=self._delete_layout).pack(side="left", padx=(2, 0))
        self._refresh_layout_list()

        # Field presets
        fld = ttk.LabelFrame(side, text="Field presets", padding=2)
        fld.grid(row=2, column=0, sticky="ew", pady=(2, 2))
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(fld, textvariable=self.preset_var, state="readonly", width=12)
        self.preset_combo.pack(side="left", fill="x", expand=True)
        ttk.Button(fld, text="Apply", width=5, command=self._apply_field_preset).pack(side="left", padx=(2, 0))
        ttk.Button(fld, text="Save", width=4, command=self._save_field_preset).pack(side="left", padx=(2, 0))
        ttk.Button(fld, text="Del", width=3, command=self._delete_field_preset).pack(side="left", padx=(2, 0))
        self._refresh_preset_list()

        ttk.Label(side, text="Elements").grid(row=3, column=0, sticky="w", pady=(4, 0))
        el_wrap = ttk.Frame(side)
        el_wrap.grid(row=4, column=0, sticky="nsew")
        side.rowconfigure(4, weight=1)
        self._el_canvas = tk.Canvas(el_wrap, height=140, highlightthickness=0)
        el_scroll = ttk.Scrollbar(el_wrap, orient="vertical", command=self._el_canvas.yview)
        self._el_host = ttk.Frame(self._el_canvas)
        self._el_host.bind(
            "<Configure>", lambda e: self._el_canvas.configure(scrollregion=self._el_canvas.bbox("all"))
        )
        self._el_canvas.create_window((0, 0), window=self._el_host, anchor="nw")
        self._el_canvas.configure(yscrollcommand=el_scroll.set)
        self._el_canvas.pack(side="left", fill="both", expand=True)
        el_scroll.pack(side="right", fill="y")
        self._el_host.columnconfigure(1, weight=1)
        self._build_element_list()

        add = ttk.Frame(side)
        add.grid(row=5, column=0, sticky="ew", pady=(2, 2))
        for i, (label, cmd) in enumerate(
            (
                ("+Note", self._add_note),
                ("Pin", lambda: self._add_icon("pin")),
                ("Cal", lambda: self._add_icon("calendar")),
                ("URL", lambda: self._add_icon("link")),
                ("○", lambda: self._add_icon("circle")),
                ("─", lambda: self._add_icon("line")),
                ("#", lambda: self._add_icon("number")),
            )
        ):
            r, c = divmod(i, 4)
            add.columnconfigure(c, weight=1)
            ttk.Button(add, text=label, width=4, command=cmd).grid(row=r, column=c, padx=1, pady=1, sticky="ew")

        self.hint_var = tk.StringVar(value="")
        ttk.Label(side, textvariable=self.hint_var, wraplength=_SIDEBAR_W - 10).grid(row=6, column=0, sticky="ew")

        self.controls = ttk.Frame(side)
        self.controls.grid(row=7, column=0, sticky="ew", pady=(3, 0))

        self.value_var = tk.StringVar()
        self.value_entry = ttk.Entry(self.controls, textvariable=self.value_var, width=22)
        self.value_entry.pack(anchor="w")
        self.value_var.trace_add("write", lambda *_a: self._write_selected())
        self.value_text = tk.Text(self.controls, height=3, width=24, wrap="word")
        self.value_text.bind("<<Modified>>", self._on_value_text)

        row_a = ttk.Frame(self.controls)
        row_a.pack(anchor="w", pady=(3, 0))
        self.size_label = ttk.Label(row_a, text="Size")
        self.size_label.pack(side="left")
        self.size_var = tk.StringVar(value="12")
        self.size_entry = ttk.Entry(row_a, textvariable=self.size_var, width=4)
        self.size_entry.pack(side="left", padx=(3, 0))
        ttk.Button(row_a, text="+", width=2, command=lambda: self._resize(1)).pack(side="left", padx=(3, 0))
        ttk.Button(row_a, text="−", width=2, command=lambda: self._resize(-1)).pack(side="left", padx=(2, 0))
        self.size_var.trace_add("write", lambda *_a: self._write_selected())

        row_b = ttk.Frame(self.controls)
        row_b.pack(anchor="w", pady=(3, 0))
        ttk.Label(row_b, text="Fg").pack(side="left")
        self.color_var = tk.StringVar(value="#ffffff")
        ttk.Entry(row_b, textvariable=self.color_var, width=7).pack(side="left", padx=(2, 0))
        self.fg_swatch = tk.Button(row_b, width=2, relief="solid", bd=1, command=lambda: self._pick_color("fg"))
        self.fg_swatch.pack(side="left", padx=(2, 0))
        ttk.Label(row_b, text="Bg").pack(side="left", padx=(4, 0))
        self.bg_var = tk.StringVar(value="#000000")
        ttk.Entry(row_b, textvariable=self.bg_var, width=7).pack(side="left", padx=(2, 0))
        self.bg_swatch = tk.Button(row_b, width=2, relief="solid", bd=1, command=lambda: self._pick_color("bg"))
        self.bg_swatch.pack(side="left", padx=(2, 0))
        self.bg_alpha_var = tk.StringVar(value="160")
        self.alpha_entry = ttk.Entry(row_b, textvariable=self.bg_alpha_var, width=3)
        self.alpha_entry.pack(side="left", padx=(3, 0))
        self.color_var.trace_add("write", lambda *_a: self._on_color_write())
        self.bg_var.trace_add("write", lambda *_a: self._on_color_write())
        self.bg_alpha_var.trace_add("write", lambda *_a: self._write_selected())

        row_c = ttk.Frame(self.controls)
        row_c.pack(anchor="w", pady=(3, 0))
        self.align_label = ttk.Label(row_c, text="Align")
        self.align_label.pack(side="left")
        self.align_var = tk.StringVar(value="left")
        self.align_combo = ttk.Combobox(
            row_c, textvariable=self.align_var, values=("left", "center", "right"), state="readonly", width=6
        )
        self.align_combo.pack(side="left", padx=(3, 0))
        self.align_var.trace_add("write", lambda *_a: self._write_selected())

        presets = ttk.Frame(self.controls)
        presets.pack(anchor="w", pady=(4, 0))
        for label, key in (("TL", "top_left"), ("TR", "top_right"), ("BL", "bottom_left"), ("BR", "bottom_right")):
            ttk.Button(presets, text=label, width=2, command=lambda k=key: self._preset(k)).pack(side="left", padx=(0, 1))

        actions = ttk.Frame(shell, padding=(0, 6, 0, 0))
        actions.grid(row=2, column=0, sticky="ew")
        ttk.Button(actions, text="Cancel", command=self.destroy).pack(side="right")
        ttk.Button(actions, text="OK — use this layout", command=self._ok).pack(side="right", padx=(0, 6))
        ttk.Button(actions, text="Reset", command=self._reset_elements).pack(side="right", padx=(0, 6))

        self._load_selected_into_controls()
        if self._fresh:
            eng.pack_fresh_overlay(self.spec, self.fields, *self._canvas_guess())
        self._place_half_screen()
        self.after(80, self._schedule_preview)

        if not eng.PIL_AVAILABLE:
            _notify(self, "Pillow is required for overlays.")
        elif not eng.QRCODE_AVAILABLE:
            _notify(self, "Install qrcode for QR overlays (pip install qrcode).")

    def _place_half_screen(self):
        self.minsize(720, 480)
        self.update_idletasks()
        sw = max(720, self.winfo_screenwidth())
        sh = max(480, self.winfo_screenheight())
        w = max(720, sw // 2)
        h = max(480, sh // 2)
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        self.geometry(f"{w}x{h}+{x}+{y}")

    def _ok(self):
        self._write_selected()
        self.spec["mode"] = self.mode_var.get()
        self.spec["orientation"] = self.orient_var.get()
        self.fields = eng.fields_from_spec(self.spec)
        self.result_spec = copy.deepcopy(self.spec)
        self.result_fields = dict(self.fields)
        self.destroy()

    def _element(self, eid=None):
        eid = eid or self.selected_id
        for el in self.spec["elements"]:
            if el["id"] == eid:
                return el
        return self.spec["elements"][0]

    def _build_element_list(self):
        for child in self._el_host.winfo_children():
            child.destroy()
        self._el_enabled.clear()
        self._el_labels.clear()
        for row_i, el in enumerate(self.spec["elements"]):
            eid = el["id"]
            var = tk.BooleanVar(value=bool(el.get("enabled")))
            self._el_enabled[eid] = var
            ttk.Checkbutton(self._el_host, variable=var, command=lambda i=eid: self._toggle_element(i)).grid(
                row=row_i, column=0, sticky="w"
            )
            lbl = ttk.Label(self._el_host, text=eng.element_label(el, self.spec["elements"]), cursor="hand2")
            lbl.grid(row=row_i, column=1, sticky="w", padx=(4, 0))
            lbl.bind("<Button-1>", lambda _e, i=eid: self._select_element(i))
            self._el_labels[eid] = lbl
        self._highlight_selected()

    def _highlight_selected(self):
        for eid, lbl in self._el_labels.items():
            if eid == self.selected_id:
                lbl.configure(foreground="#4f46e5")
            else:
                lbl.configure(foreground="")

    def _toggle_element(self, eid):
        if self._suppress:
            return
        el = self._element(eid)
        el["enabled"] = bool(self._el_enabled[eid].get())
        if self.selected_id != eid:
            self._select_element(eid)
        else:
            self._schedule_preview()

    def _select_element(self, eid):
        if eid == self.selected_id:
            self._highlight_selected()
            return
        self._write_selected()
        self.selected_id = eid
        self._highlight_selected()
        self._load_selected_into_controls()
        self._schedule_preview()

    def _refresh_layout_list(self, select_name=None):
        names = eng.list_layouts()
        self.template_combo.configure(values=names)
        if select_name and select_name in names:
            self.template_var.set(select_name)
        elif names and self.template_var.get() not in names:
            self.template_var.set(names[0])
        elif not names:
            self.template_var.set("")

    def _refresh_preset_list(self, select_name=None):
        names = eng.list_field_presets()
        self.preset_combo.configure(values=names)
        if select_name and select_name in names:
            self.preset_var.set(select_name)
        elif names and self.preset_var.get() not in names:
            self.preset_var.set(names[0])
        elif not names:
            self.preset_var.set("")

    def _load_layout(self):
        name = self.template_var.get().strip()
        if not name:
            _notify(self, "No layout selected.")
            return
        layouts = eng.load_layouts()
        spec = layouts.get(name)
        if not spec:
            _notify(self, "Layout not found.")
            return
        self._write_selected()
        self.spec = eng.sanitize_overlay_spec(spec)
        eng.apply_fields_to_spec(self.spec, self.fields)
        self.mode_var.set(self.spec.get("mode") or "on_poster")
        self.orient_var.set(self.spec.get("orientation") or "auto")
        self._sync_orient_state()
        self.selected_id = self.spec["elements"][0]["id"]
        self._build_element_list()
        self._load_selected_into_controls()
        self._schedule_preview()

    def _save_layout(self):
        self._write_selected()
        self.spec["mode"] = self.mode_var.get()
        self.spec["orientation"] = self.orient_var.get()
        suggested = self.template_var.get().strip() or "My layout"
        name = simpledialog.askstring("Save layout", "Layout name:", initialvalue=suggested, parent=self)
        if name is None:
            return
        name = (name or "").strip()
        if not name:
            _notify(self, "Layout name is required.")
            return
        if name in eng.load_layouts():
            if not _ask_yes_no(self, "Overwrite", f'Layout "{name}" exists. Overwrite?'):
                return
        # Save layout without baking field values into positions-only template: keep values for convenience
        ok, result = eng.save_layout(name, self.spec)
        if not ok:
            _notify(self, result)
            return
        self._refresh_layout_list(select_name=result)
        _notify(self, f"Saved layout: {result}")

    def _delete_layout(self):
        name = self.template_var.get().strip()
        if not name:
            _notify(self, "Select a layout to delete.")
            return
        if not _ask_yes_no(self, "Delete layout", f'Delete layout "{name}"?'):
            return
        ok, result = eng.delete_layout(name)
        if not ok:
            _notify(self, result)
            return
        self._refresh_layout_list()
        _notify(self, f"Deleted layout: {name}")

    def _apply_field_preset(self):
        name = self.preset_var.get().strip()
        if not name:
            _notify(self, "No field preset selected.")
            return
        presets = eng.load_field_presets()
        fields = presets.get(name)
        if not fields:
            _notify(self, "Preset not found.")
            return
        self._write_selected()
        self.fields.update(fields)
        eng.apply_fields_to_spec(self.spec, self.fields)
        self._load_selected_into_controls()
        self._schedule_preview()

    def _save_field_preset(self):
        self._write_selected()
        fields = eng.fields_from_spec(self.spec)
        suggested = self.preset_var.get().strip() or "My fields"
        name = simpledialog.askstring("Save field preset", "Preset name:", initialvalue=suggested, parent=self)
        if name is None:
            return
        name = (name or "").strip()
        if not name:
            _notify(self, "Preset name is required.")
            return
        if name in eng.load_field_presets():
            if not _ask_yes_no(self, "Overwrite", f'Preset "{name}" exists. Overwrite?'):
                return
        ok, result = eng.save_field_preset(name, fields)
        if not ok:
            _notify(self, result)
            return
        self._refresh_preset_list(select_name=result)
        _notify(self, f"Saved field preset: {result}")

    def _delete_field_preset(self):
        name = self.preset_var.get().strip()
        if not name:
            _notify(self, "Select a preset to delete.")
            return
        if not _ask_yes_no(self, "Delete preset", f'Delete field preset "{name}"?'):
            return
        ok, result = eng.delete_field_preset(name)
        if not ok:
            _notify(self, result)
            return
        self._refresh_preset_list()
        _notify(self, f"Deleted preset: {name}")

    def _qr_size(self, el):
        return max(0.04, min(float(el.get("w", 0.12)), float(el.get("h", 0.12))))

    def _set_qr_size(self, el, size):
        size = max(0.04, min(0.8, float(size)))
        el["w"] = el["h"] = size
        el["x"] = min(float(el.get("x", 0)), 1.0 - size)
        el["y"] = min(float(el.get("y", 0)), 1.0 - size)
        return size

    def _canvas_guess(self):
        if self.mode_var.get() == "on_page":
            orient = self.orient_var.get() if self.orient_var.get() in ("portrait", "landscape") else "portrait"
            return eng.a4_pixel_size(orient, 150)
        return 1000, 1400

    def _text_payload(self, el):
        kind, payload = eng.resolve_element_payload(el, self.fields)
        return payload if kind == "text" else " "

    def _fit_font_to_el(self, el):
        g = self._preview_geom
        cw, ch = (g["src_w"], g["src_h"]) if g else self._canvas_guess()
        fs = eng.fit_font_to_box(
            self._text_payload(el), float(el.get("w", 0.1)) * cw, float(el.get("h", 0.1)) * ch
        )
        el["font_size"] = fs
        return fs

    def _hex_color(self, value, fallback="#ffffff"):
        text = (value or "").strip()
        if not text.startswith("#"):
            text = "#" + text
        if len(text) == 4:
            text = "#" + "".join(ch * 2 for ch in text[1:])
        if len(text) != 7:
            return fallback
        try:
            int(text[1:], 16)
        except ValueError:
            return fallback
        return text.lower()

    def _sync_swatches(self):
        fg = self._hex_color(self.color_var.get(), "#ffffff")
        bg = self._hex_color(self.bg_var.get(), "#000000")
        self.fg_swatch.configure(bg=fg, activebackground=fg)
        self.bg_swatch.configure(bg=bg, activebackground=bg)

    def _on_color_write(self):
        self._sync_swatches()
        self._write_selected()

    def _pick_color(self, which):
        var = self.color_var if which == "fg" else self.bg_var
        _rgb, picked = colorchooser.askcolor(color=self._hex_color(var.get()), parent=self, title="Color")
        if picked:
            var.set(picked)

    def _add_note(self):
        self._write_selected()
        note = eng.make_custom_note(self.spec, enabled=True)
        self._build_element_list()
        self._select_element(note["id"])

    def _add_icon(self, field):
        self._write_selected()
        icon = eng.make_icon_element(self.spec, field, enabled=True)
        self._build_element_list()
        self._select_element(icon["id"])

    def _reset_elements(self):
        if not _ask_yes_no(self, "Reset", "Clear all elements and turn everything off?"):
            return
        self._write_selected()
        mode = self.mode_var.get()
        self.spec = eng.default_overlay_spec(mode=mode)
        self.spec["orientation"] = self.orient_var.get()
        eng.apply_fields_to_spec(self.spec, self.fields)
        self.selected_id = self.spec["elements"][0]["id"]
        self._build_element_list()
        self._load_selected_into_controls()
        self._schedule_preview()

    def _is_custom_text(self, el):
        return el.get("type") == "text" and el.get("field") == "custom"

    def _show_value_controls(self, el):
        if self._is_custom_text(el):
            self.value_entry.pack_forget()
            self.value_text.pack(anchor="w", fill="x")
        elif el.get("type") == "icon" and el.get("field") == "number":
            self.value_text.pack_forget()
            self.value_entry.pack(anchor="w")
        elif el.get("type") == "icon":
            self.value_entry.pack_forget()
            self.value_text.pack_forget()
        else:
            self.value_text.pack_forget()
            self.value_entry.pack(anchor="w")

    def _on_value_text(self, _event=None):
        if self._suppress:
            return
        try:
            if self.value_text.edit_modified():
                self.value_text.edit_modified(False)
                self._write_selected()
        except tk.TclError:
            pass

    def _load_selected_into_controls(self):
        el = self._element()
        is_qr = el.get("type") == "qr"
        is_icon = el.get("type") == "icon"
        self._suppress = True
        try:
            self._show_value_controls(el)
            eid = el.get("id")
            if self._is_custom_text(el):
                text = el.get("value") or self.fields.get(eid, "")
                self.value_text.configure(state="normal")
                self.value_text.delete("1.0", tk.END)
                self.value_text.insert("1.0", text)
            elif is_icon and el.get("field") == "number":
                self.value_entry.configure(state="normal")
                self.value_var.set(str(el.get("value") or "1"))
            elif is_icon:
                pass
            else:
                text = el.get("value") or self.fields.get(eid, "")
                self.value_entry.configure(state="normal")
                self.value_var.set(text)
            if is_qr or is_icon:
                self.size_label.configure(text="Size")
                if is_qr:
                    size_text = str(int(round(self._qr_size(el) * 100)))
                elif el.get("field") == "line":
                    size_text = str(int(round(float(el.get("w", 0.22)) * 100)))
                else:
                    size_text = str(int(round(max(float(el.get("w", 0.05)), float(el.get("h", 0.05))) * 100)))
                self.size_var.set(size_text)
                self.align_label.pack_forget()
                self.align_combo.pack_forget()
                self.alpha_entry.pack_forget()
            else:
                self.size_label.configure(text="Font")
                self.size_var.set(str(el.get("font_size", 28)))
                if not self.align_label.winfo_ismapped():
                    self.align_label.pack(side="left")
                    self.align_combo.pack(side="left", padx=(3, 0))
                if not self.alpha_entry.winfo_ismapped():
                    self.alpha_entry.pack(side="left", padx=(3, 0))
            color = el.get("color") or el.get("fg") or "#ffffff"
            bg = el.get("bg") or "#000000"
            alpha = str(el.get("bg_alpha", 160 if el.get("type") == "text" else 0))
            self.color_var.set(color)
            self.bg_var.set(bg)
            self.bg_alpha_var.set(alpha)
            self.align_var.set(el.get("align") or "left")
            self._sync_swatches()
        finally:
            self._suppress = False
            try:
                self.value_text.edit_modified(False)
            except tk.TclError:
                pass

    def _write_selected(self):
        if self._suppress:
            return
        el = self._element()
        eid = el.get("id")
        if self._is_custom_text(el):
            el["value"] = self.value_text.get("1.0", "end-1c")
            if eid:
                self.fields[eid] = el["value"]
        elif el.get("type") == "icon" and el.get("field") == "number":
            el["value"] = self.value_var.get().strip() or "1"
            lbl = self._el_labels.get(el["id"])
            if lbl:
                lbl.configure(text=eng.element_label(el, self.spec["elements"]))
        elif el.get("type") != "icon":
            el["value"] = self.value_var.get()
            if eid:
                self.fields[eid] = el["value"]
        if el.get("type") == "text":
            try:
                wanted = max(8, min(200, int(self.size_var.get().strip() or "28")))
            except ValueError:
                wanted = max(8, int(el.get("font_size", 28)))
            current = self._fit_font_to_el(el)
            if current and wanted != current:
                scale = wanted / current
                el["w"] = max(0.04, min(0.95, float(el.get("w", 0.1)) * scale))
                el["h"] = max(0.03, min(0.95, float(el.get("h", 0.1)) * scale))
                el["x"] = min(float(el.get("x", 0)), 1.0 - el["w"])
                el["y"] = min(float(el.get("y", 0)), 1.0 - el["h"])
                wanted = self._fit_font_to_el(el)
            el["font_size"] = wanted
            el["color"] = (self.color_var.get() or "#ffffff").strip()
            el["bg"] = (self.bg_var.get() or "#000000").strip()
            try:
                el["bg_alpha"] = max(0, min(255, int(self.bg_alpha_var.get().strip() or "0")))
            except ValueError:
                pass
            el["align"] = self.align_var.get() if self.align_var.get() in ("left", "center", "right") else "left"
        elif el.get("type") == "icon":
            if el.get("field") == "line":
                try:
                    pct = max(4, min(90, float(self.size_var.get().strip() or "22")))
                    el["w"] = pct / 100.0
                    el["x"] = min(float(el.get("x", 0)), 1.0 - el["w"])
                except ValueError:
                    pass
            else:
                try:
                    pct = max(3, min(30, float(self.size_var.get().strip() or "5")))
                    size = pct / 100.0
                    el["w"] = el["h"] = size
                except ValueError:
                    pass
            el["color"] = (self.color_var.get() or "#ffffff").strip()
            el["fg"] = el["color"]
            el["bg"] = (self.bg_var.get() or "#000000").strip()
        else:
            try:
                pct = max(4, min(80, float(self.size_var.get().strip() or "12")))
                self._set_qr_size(el, pct / 100.0)
            except ValueError:
                pass
            el["fg"] = (self.color_var.get() or "#000000").strip()
            el["bg"] = (self.bg_var.get() or "#ffffff").strip()
        self._schedule_preview()

    def _on_mode_change(self):
        self._write_selected()
        new_mode = self.mode_var.get()
        old = copy.deepcopy(self.spec)
        extras = [
            el
            for el in old.get("elements") or []
            if el.get("type") == "icon"
            or (el.get("type") == "text" and el.get("field") == "custom" and el.get("id") != "custom_note")
        ]
        self.spec = eng.default_overlay_spec(mode=new_mode)
        self.spec["orientation"] = self.orient_var.get()
        old_by_id = {el["id"]: el for el in old.get("elements") or []}
        for el in self.spec["elements"]:
            prev = old_by_id.get(el["id"])
            if not prev:
                continue
            el["enabled"] = bool(prev.get("enabled"))
            el["value"] = prev.get("value") or self.fields.get(el["id"], "")
            for key in ("font_size", "color", "bg", "bg_alpha", "align", "fg", "x", "y", "w", "h"):
                if key in prev:
                    el[key] = prev[key]
        for extra in extras:
            cleaned = copy.deepcopy(extra)
            if cleaned.get("type") == "text":
                cleaned.update(eng._style_for_mode(new_mode, "text"))
            elif cleaned.get("type") == "icon":
                cleaned.update(eng._style_for_mode(new_mode, "icon"))
            self.spec["elements"].append(cleaned)
        eng.apply_fields_to_spec(self.spec, self.fields)
        self._sync_orient_state()
        self._build_element_list()
        eng.pack_fresh_overlay(self.spec, self.fields, *self._canvas_guess())
        self._load_selected_into_controls()
        self._schedule_preview()

    def _on_orient_change(self):
        self.spec["orientation"] = self.orient_var.get()
        self._schedule_preview()

    def _sync_orient_state(self):
        self.orient_combo.configure(state="readonly" if self.mode_var.get() == "on_page" else "disabled")

    def _resize(self, step):
        el = self._element()
        self._suppress = True
        try:
            if el.get("type") == "qr":
                size = self._set_qr_size(el, self._qr_size(el) + step * 0.02)
                self.size_var.set(str(int(round(size * 100))))
            elif el.get("type") == "icon" and el.get("field") == "line":
                el["w"] = max(0.04, min(0.9, float(el.get("w", 0.22)) + step * 0.03))
                el["x"] = min(float(el.get("x", 0)), 1.0 - el["w"])
                self.size_var.set(str(int(round(el["w"] * 100))))
            elif el.get("type") == "icon":
                size = max(
                    0.03,
                    min(0.30, max(float(el.get("w", 0.05)), float(el.get("h", 0.05))) + step * 0.005),
                )
                el["w"] = el["h"] = size
                self.size_var.set(str(int(round(size * 100))))
            else:
                old = max(8, int(el.get("font_size", 28)))
                size = max(8, min(200, old + step * 2))
                scale = size / old
                el["w"] = max(0.04, min(0.95, float(el.get("w", 0.1)) * scale))
                el["h"] = max(0.03, min(0.95, float(el.get("h", 0.1)) * scale))
                el["x"] = min(float(el.get("x", 0)), 1.0 - el["w"])
                el["y"] = min(float(el.get("y", 0)), 1.0 - el["h"])
                self.size_var.set(str(self._fit_font_to_el(el)))
        finally:
            self._suppress = False
        self._schedule_preview()

    def _preset(self, key):
        self._write_selected()
        selected = self._element()
        if selected.get("type") == "icon":
            group = [el for el in self.spec["elements"] if el.get("type") == "icon" and (el.get("enabled") or el is selected)]
        elif selected.get("type") == "text" and selected.get("field") == "custom":
            group = [
                el
                for el in self.spec["elements"]
                if el.get("type") == "text" and el.get("field") == "custom" and (el.get("enabled") or el is selected)
            ]
        else:
            group = [
                el
                for el in self.spec["elements"]
                if el.get("type") == selected.get("type") and (el.get("enabled") or el is selected)
            ]
        if selected not in group:
            group.append(selected)
        eng.pack_elements_at_corner(group, key, self.fields, *self._canvas_guess())
        self._schedule_preview()

    def _on_preview_configure(self, _event=None):
        if not self._drag:
            self._schedule_preview()

    def _el_canvas_rect(self, el):
        g = self._preview_geom
        if not g:
            return None
        x0 = g["ox"] + float(el.get("x", 0)) * g["src_w"] * g["scale"]
        y0 = g["oy"] + float(el.get("y", 0)) * g["src_h"] * g["scale"]
        x1 = g["ox"] + (float(el.get("x", 0)) + float(el.get("w", 0.1))) * g["src_w"] * g["scale"]
        y1 = g["oy"] + (float(el.get("y", 0)) + float(el.get("h", 0.1))) * g["src_h"] * g["scale"]
        return x0, y0, x1, y1

    def _handle_rect(self, box):
        x0, y0, x1, y1 = box
        return x1 - _HANDLE, y1 - _HANDLE, x1 + _HANDLE, y1 + _HANDLE

    def _draw_selection(self):
        canvas = self.preview_canvas
        canvas.delete("sel")
        el = self._element()
        if not el.get("enabled"):
            return
        box = self._el_canvas_rect(el)
        if not box:
            return
        x0, y0, x1, y1 = box
        canvas.create_rectangle(x0, y0, x1, y1, outline="#818cf8", width=2, tags="sel")
        hx0, hy0, hx1, hy1 = self._handle_rect(box)
        canvas.create_rectangle(hx0, hy0, hx1, hy1, outline="#4f46e5", fill="#c7d2fe", tags="sel")

    def _hit_element(self, cx, cy):
        for el in reversed(self.spec["elements"]):
            if not el.get("enabled"):
                continue
            box = self._el_canvas_rect(el)
            if not box:
                continue
            x0, y0, x1, y1 = box
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                return el
        return None

    def _on_preview_down(self, event):
        el = self._element()
        box = self._el_canvas_rect(el) if el.get("enabled") else None
        if box:
            hx0, hy0, hx1, hy1 = self._handle_rect(box)
            if hx0 <= event.x <= hx1 and hy0 <= event.y <= hy1:
                self._drag = {
                    "mode": "resize",
                    "id": el["id"],
                    "x": event.x,
                    "y": event.y,
                    "orig": (float(el.get("x", 0)), float(el.get("y", 0)), float(el.get("w", 0.1)), float(el.get("h", 0.1))),
                }
                return
        hit = self._hit_element(event.x, event.y)
        if not hit:
            self._drag = None
            return
        if hit["id"] != self.selected_id:
            self._select_element(hit["id"])
            el = hit
        self._drag = {
            "mode": "move",
            "id": el["id"],
            "x": event.x,
            "y": event.y,
            "orig": (float(el.get("x", 0)), float(el.get("y", 0)), float(el.get("w", 0.1)), float(el.get("h", 0.1))),
        }

    def _on_preview_drag(self, event):
        if not self._drag or not self._preview_geom:
            return
        el = self._element(self._drag["id"])
        g = self._preview_geom
        denx = g["src_w"] * g["scale"]
        deny = g["src_h"] * g["scale"]
        if denx <= 0 or deny <= 0:
            return
        ox, oy, ow, oh = self._drag["orig"]
        dnx = (event.x - self._drag["x"]) / denx
        dny = (event.y - self._drag["y"]) / deny
        if self._drag["mode"] == "move":
            el["x"] = max(0.0, min(1.0 - ow, ox + dnx))
            el["y"] = max(0.0, min(1.0 - oh, oy + dny))
        else:
            if el.get("type") == "text":
                el["w"] = max(0.04, min(0.95, ow + dnx))
                el["h"] = max(0.03, min(0.95, oh + dny))
                el["x"] = min(ox, 1.0 - el["w"])
                el["y"] = min(oy, 1.0 - el["h"])
                fs = self._fit_font_to_el(el)
                self._suppress = True
                try:
                    self.size_var.set(str(fs))
                finally:
                    self._suppress = False
            else:
                size = max(0.04, min(0.8, max(ow + dnx, oh + dny)))
                el["w"] = el["h"] = size
                el["x"] = min(ox, 1.0 - size)
                el["y"] = min(oy, 1.0 - size)
                self._suppress = True
                try:
                    self.size_var.set(str(int(round(size * 100))))
                finally:
                    self._suppress = False
        self._draw_selection()
        self._schedule_preview()

    def _on_preview_up(self, _event=None):
        self._drag = None
        self._schedule_preview()

    def _schedule_preview(self):
        if self._preview_job is not None:
            try:
                self.after_cancel(self._preview_job)
            except Exception:
                pass
        self._preview_job = self.after(80, self._render_preview)

    def _render_preview(self):
        self._preview_job = None
        canvas = self.preview_canvas
        if not eng.PIL_AVAILABLE or not _TK_PIL:
            canvas.delete("all")
            canvas.create_text(12, 12, anchor="nw", fill="#94a3b8", text="Pillow required for preview")
            self._preview_geom = None
            return
        self.spec["mode"] = self.mode_var.get()
        self.spec["orientation"] = self.orient_var.get()
        try:
            composed, warnings, _spec = eng.compose_poster(
                self.image_path, fields=self.fields, spec=self.spec
            )
        except Exception as exc:
            self.hint_var.set(str(exc))
            canvas.delete("all")
            canvas.create_text(12, 12, anchor="nw", fill="#f87171", text=f"Preview failed: {exc}")
            self._preview_geom = None
            return
        self.hint_var.set("; ".join(warnings[:2]) if warnings else "")
        self.update_idletasks()
        max_w = max(240, canvas.winfo_width() or 420)
        max_h = max(320, canvas.winfo_height() or 520)
        preview = composed.copy()
        preview.thumbnail((max_w, max_h))
        self._photo = ImageTk.PhotoImage(preview)
        scale = preview.width / composed.width if composed.width else 1.0
        ox = max(0, (max_w - preview.width) // 2)
        oy = max(0, (max_h - preview.height) // 2)
        self._preview_geom = {"ox": ox, "oy": oy, "scale": scale, "src_w": composed.width, "src_h": composed.height}
        canvas.delete("all")
        canvas.create_image(ox, oy, anchor="nw", image=self._photo)
        self._draw_selection()


class ImageOverlayPlugin(BaseFileOperation):
    name = "Image Overlay"
    description = "Bake text, QR codes, and icons onto images. Save layouts and field presets for reuse."
    supported_extensions = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    needs_output_dir = True

    def __init__(self):
        super().__init__()
        self.on_change_callback = None
        self._session_spec = None
        self._session_fields = None

    def _bind_trace(self, var):
        var.trace_add("write", lambda *args: self._notify_change())
        return var

    def _notify_change(self):
        if callable(self.on_change_callback):
            self.on_change_callback()

    def _resolve_spec_and_fields(self):
        layout_name = self.layout_var.get().strip() if hasattr(self, "layout_var") else ""
        preset_name = self.fields_var.get().strip() if hasattr(self, "fields_var") else ""
        spec = None
        if self._session_spec is not None:
            spec = copy.deepcopy(self._session_spec)
        elif layout_name:
            layouts = eng.load_layouts()
            if layout_name in layouts:
                spec = copy.deepcopy(layouts[layout_name])
        if spec is None:
            spec = eng.default_overlay_spec()

        fields = {}
        if preset_name:
            presets = eng.load_field_presets()
            if preset_name in presets:
                fields.update(presets[preset_name])
        if self._session_fields:
            fields.update(self._session_fields)
        eng.apply_fields_to_spec(spec, fields)
        return spec, fields

    def open_editor(self, parent=None, image_path=None):
        if not image_path:
            messagebox.showwarning("Image Overlay", "Add an image to the queue first.")
            return
        parent = parent or (hasattr(self, "_ui_parent") and self._ui_parent)
        root = parent.winfo_toplevel() if parent else None
        spec, fields = self._resolve_spec_and_fields()
        dlg = OverlayEditorDialog(root, image_path, initial_spec=spec, initial_fields=fields)
        root.wait_window(dlg) if root else dlg.wait_window()
        if dlg.result_spec is not None:
            self._session_spec = dlg.result_spec
            self._session_fields = dlg.result_fields or {}
            # Reflect names in combos if user saved during edit
            self._refresh_option_lists()

    def _refresh_option_lists(self):
        if hasattr(self, "layout_combo"):
            names = [""] + eng.list_layouts()
            self.layout_combo.configure(values=names)
        if hasattr(self, "fields_combo"):
            names = [""] + eng.list_field_presets()
            self.fields_combo.configure(values=names)

    def execute(self, files, output_path, **kwargs):
        if not files:
            raise ValueError("No files provided.")
        if not eng.PIL_AVAILABLE:
            raise RuntimeError("Pillow is required.")

        out_dir = Path(output_path)
        if out_dir.suffix:
            out_dir = out_dir.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        overwrite = self.overwrite_var.get() if hasattr(self, "overwrite_var") else False
        spec, fields = self._resolve_spec_and_fields()

        # Enable any element that has a value so batch apply works from presets alone
        for el in spec.get("elements") or []:
            eid = el.get("id")
            val = fields.get(eid) or el.get("value") or ""
            if str(val).strip() and el.get("type") in ("text", "qr"):
                el["enabled"] = True
                el["value"] = str(val)

        done = 0
        for f_str in files:
            src = Path(f_str)
            if not src.is_file():
                print(f"Skip missing: {src}")
                continue
            ext = src.suffix.lower() or ".jpg"
            if overwrite:
                dest = out_dir / src.name
            else:
                dest = out_dir / f"{src.stem}_overlay{ext}"
            written, warnings, _ = eng.compose_to_file(str(src), str(dest), spec=spec, fields=fields)
            extra = f" ({len(warnings)} skipped)" if warnings else ""
            print(f"Overlay -> {written}{extra}")
            done += 1
        print(f"Done: {done} of {len(files)}")

    def render_options_ui(self, parent_frame, on_change_callback=None):
        self.on_change_callback = on_change_callback
        self._ui_parent = parent_frame
        frame = ttk.Frame(parent_frame, padding=4)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Layout").grid(row=0, column=0, sticky="w", pady=1)
        self.layout_var = self._bind_trace(tk.StringVar(value=""))
        self.layout_combo = ttk.Combobox(frame, textvariable=self.layout_var, state="readonly", width=16)
        self.layout_combo.grid(row=0, column=1, sticky="ew", pady=1)

        ttk.Label(frame, text="Fields").grid(row=1, column=0, sticky="w", pady=1)
        self.fields_var = self._bind_trace(tk.StringVar(value=""))
        self.fields_combo = ttk.Combobox(frame, textvariable=self.fields_var, state="readonly", width=16)
        self.fields_combo.grid(row=1, column=1, sticky="ew", pady=1)

        self.overwrite_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Overwrite (same name)", variable=self.overwrite_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=2
        )

        ttk.Button(frame, text="Open overlay editor…", command=self._ui_open_editor).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=(4, 0)
        )
        ttk.Label(frame, text="Editor uses the first queued image.", wraplength=200).grid(
            row=4, column=0, columnspan=2, sticky="w"
        )

        self._refresh_option_lists()
        return frame

    def _ui_open_editor(self):
        root = self._ui_parent.winfo_toplevel() if hasattr(self, "_ui_parent") else None
        image_path = None
        if root is not None and getattr(root, "file_queue", None):
            image_path = root.file_queue[0].get("path")
        if not image_path:
            from tkinter import filedialog

            image_path = filedialog.askopenfilename(
                parent=root,
                title="Choose image to overlay",
                filetypes=[("Images", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("All", "*.*")],
            )
        if image_path:
            self.open_editor(parent=self._ui_parent, image_path=image_path)

    def get_output_path(self, output_dir, files):
        return output_dir


def _self_check():
    eng._self_check()
    root = tk.Tk()
    root.withdraw()
    try:
        img = Image.new("RGB", (120, 160), (20, 20, 20))
        tmp = Path(tempfile.gettempdir()) / "overlay_plugin_selfcheck.png"
        img.save(tmp)
        spec = eng.default_overlay_spec()
        for el in spec["elements"]:
            if el["id"] == "title":
                el["enabled"] = True
                el["value"] = "Hello"
        out = Path(tempfile.gettempdir()) / "overlay_plugin_out.jpg"
        eng.compose_to_file(str(tmp), str(out), spec=spec, fields={"title": "Hello"})
        assert out.is_file()
        plugin = ImageOverlayPlugin()
        plugin.layout_var = tk.StringVar(value="")
        plugin.fields_var = tk.StringVar(value="")
        plugin.overwrite_var = tk.BooleanVar(value=False)
        plugin._session_spec = spec
        plugin._session_fields = {"title": "Hello"}
        out_dir = Path(tempfile.gettempdir()) / "overlay_plugin_batch"
        out_dir.mkdir(exist_ok=True)
        plugin.execute([str(tmp)], str(out_dir))
        assert any(out_dir.glob("*_overlay.*"))
        for p in (tmp, out):
            try:
                p.unlink()
            except OSError:
                pass
    finally:
        root.destroy()
    print("images_to_overlay self-check OK")


def cli_main():
    parser = argparse.ArgumentParser(description="Image Overlay")
    parser.add_argument("-i", "--inputs", nargs="+", default=[])
    parser.add_argument("-o", "--output", default="")
    parser.add_argument("--layout", default="", help="Saved layout name")
    parser.add_argument("--fields", default="", help="Saved field-preset name")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return

    if not args.inputs:
        parser.error("the following arguments are required: -i/--inputs")

    plugin = ImageOverlayPlugin()
    files = plugin.filter_inputs(plugin.collect_input_files(args.inputs))
    if not files:
        print("No matching files.")
        sys.exit(1)

    plugin.layout_var = tk.StringVar(value=args.layout)
    plugin.fields_var = tk.StringVar(value=args.fields)
    plugin.overwrite_var = tk.BooleanVar(value=args.overwrite)
    out = args.output.strip() or str(Path(files[0]).parent)
    plugin.execute(files, plugin.get_output_path(out, files))


if __name__ == "__main__":
    plugin_entry(ImageOverlayPlugin, cli_main)
