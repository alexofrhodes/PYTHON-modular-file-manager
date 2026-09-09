"""Universal File Toolkit — host app, plugin base, and standalone plugin shell."""

from __future__ import annotations

import glob
import json
import locale
import os
import pkgutil
import importlib
import queue
import subprocess
import sys
import time
import webbrowser
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    import windnd
except ImportError:
    windnd = None

ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# When launched as `python modular-file-manager.py`, __name__ is __main__;
# alias so plugins can import_host() without loading a duplicate module.
sys.modules.setdefault("modular_file_manager", sys.modules[__name__])

STATE_FILE = ROOT_DIR / ".toolkit_state.json"


def decode_dropped_path(value) -> str:
    """Decode windnd / Explorer drop payloads on Windows (often ANSI / mbcs, not UTF-8)."""
    if isinstance(value, bytes):
        text = None
        for enc in (
            sys.getfilesystemencoding(),
            "mbcs",
            locale.getpreferredencoding(False),
            "utf-8",
        ):
            if not enc:
                continue
            try:
                text = value.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:
            text = value.decode("utf-8", errors="replace")
    else:
        text = str(value)
    # windnd often appends a trailing NUL
    return text.strip("\x00").strip()


def paths_from_drop_payload(files_dropped) -> List[str]:
    paths = [decode_dropped_path(f) for f in (files_dropped or [])]
    return [p for p in paths if p]


class TkDropBridge:
    """Thread-safe bridge from windnd (non-Tk thread) to the Tk main loop.

    Never call Tk APIs (including root.after) from the windnd callback — on
    Python 3.14 that causes a fatal GIL / PyEval_RestoreThread crash.
    """

    def __init__(self, root: tk.Misc, on_paths: Callable[[List[str]], None], poll_ms: int = 80):
        self.root = root
        self.on_paths = on_paths
        self.poll_ms = poll_ms
        self._q: queue.Queue = queue.Queue()
        self._polling = False

    def start(self):
        if self._polling:
            return
        self._polling = True
        self.root.after(self.poll_ms, self._poll)

    def enqueue_from_windnd(self, files_dropped):
        # Runs on windnd's thread — queue only, no Tk.
        try:
            self._q.put(paths_from_drop_payload(files_dropped))
        except Exception:
            pass

    def hook(self, widget):
        if not windnd:
            return False
        try:
            windnd.hook_dropfiles(widget, func=self.enqueue_from_windnd)
            self.start()
            return True
        except Exception:
            return False

    def _poll(self):
        try:
            while True:
                paths = self._q.get_nowait()
                if paths:
                    try:
                        self.on_paths(paths)
                    except Exception as e:
                        try:
                            messagebox.showerror("Drop Error", str(e))
                        except Exception:
                            pass
        except queue.Empty:
            pass
        if self._polling:
            self.root.after(self.poll_ms, self._poll)

DEFAULT_COLORS = {
    "page": "#EEF2F6",
    "sidebar": "#F7F9FC",
    "card": "#FFFFFF",
    "edge": "#D7DEE7",
    "text": "#1F2A37",
    "muted": "#5C6B7A",
    "accent": "#1F6F5B",
    "accent_hover": "#185A4A",
    "log_bg": "#1A2332",
    "log_fg": "#D7E0EA",
}

AUTHOR_NAME = "Alex of Rhodes"
AUTHOR_EMAIL = "alexofrhodes@gmail.com"
AUTHOR_GITHUB = "https://github.com/alexofrhodes"


def center_window(win: tk.Misc, width: Optional[int] = None, height: Optional[int] = None) -> None:
    """Place window in the middle of the screen (keeps size if width/height omitted)."""
    win.update_idletasks()
    if width is None or height is None:
        wh = win.winfo_width(), win.winfo_height()
        # Before map, winfo_* can be 1; fall back to geometry string
        geo = win.geometry().split("+", 1)[0]
        try:
            gw, gh = (int(x) for x in geo.split("x", 1))
        except ValueError:
            gw, gh = 800, 600
        if width is None:
            width = gw if wh[0] <= 1 else wh[0]
        if height is None:
            height = gh if wh[1] <= 1 else wh[1]
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = max(0, (sw - width) // 2)
    y = max(0, (sh - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")


def parse_geometry_size(geo: str) -> Optional[Tuple[int, int]]:
    """Extract WxH from a Tk geometry string."""
    try:
        wh = geo.split("+", 1)[0]
        w, h = wh.split("x", 1)
        return int(w), int(h)
    except (ValueError, IndexError):
        return None


def make_link_label(parent, text: str, url: str, colors: dict, **pack_kwargs) -> tk.Label:
    """Accent-colored clickable label (no underline)."""
    lbl = tk.Label(
        parent,
        text=text,
        fg=colors["accent"],
        bg=colors["page"],
        cursor="hand2",
        font=("Segoe UI", 9),
        anchor="w",
    )
    lbl.pack(**pack_kwargs)
    lbl.bind("<Button-1>", lambda _e: webbrowser.open(url))
    return lbl


def apply_toolkit_styles(root: tk.Tk | tk.Toplevel, colors: Optional[dict] = None) -> dict:
    """Shared clam theme + named styles for host and standalone plugin windows."""
    c = dict(colors or DEFAULT_COLORS)
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=c["page"])

    style.configure(".", font=("Segoe UI", 9), background=c["page"], foreground=c["text"])
    style.configure("TFrame", background=c["page"])
    style.configure("TLabel", background=c["page"], foreground=c["text"], font=("Segoe UI", 9))
    style.configure("TCheckbutton", background=c["page"], foreground=c["text"], font=("Segoe UI", 9))
    style.configure("TRadiobutton", background=c["page"], foreground=c["text"], font=("Segoe UI", 9))
    style.configure("TEntry", fieldbackground=c["card"], foreground=c["text"])
    style.configure("TCombobox", fieldbackground=c["card"], foreground=c["text"])
    style.configure("TNotebook", background=c["page"], borderwidth=0)
    style.configure("TNotebook.Tab", background=c["sidebar"], foreground=c["text"], padding=(8, 3))
    style.map("TNotebook.Tab", background=[("selected", c["card"])], foreground=[("selected", c["accent"])])
    style.configure("TSeparator", background=c["edge"])
    style.configure("TScrollbar", background=c["sidebar"], troughcolor=c["page"])

    style.configure("Sidebar.TFrame", background=c["sidebar"])
    style.configure("Sidebar.TLabel", background=c["sidebar"], foreground=c["text"], font=("Segoe UI", 9))
    style.configure("Sidebar.TCheckbutton", background=c["sidebar"], foreground=c["text"])
    style.configure("Sidebar.TRadiobutton", background=c["sidebar"], foreground=c["text"])
    style.configure("SidebarMuted.TLabel", background=c["sidebar"], foreground=c["muted"], font=("Segoe UI", 8))
    style.configure(
        "SidebarSection.TLabel", background=c["sidebar"], foreground=c["accent"], font=("Segoe UI Semibold", 8)
    )

    style.configure("Card.TFrame", background=c["card"])
    style.configure("Card.TLabel", background=c["card"], foreground=c["text"], font=("Segoe UI", 9))
    style.configure("CardMuted.TLabel", background=c["card"], foreground=c["muted"], font=("Segoe UI", 8))
    style.configure("CardSection.TLabel", background=c["card"], foreground=c["accent"], font=("Segoe UI Semibold", 8))
    style.configure("Card.TCheckbutton", background=c["card"], foreground=c["text"])
    style.configure("Card.TRadiobutton", background=c["card"], foreground=c["text"])

    style.configure("Title.TLabel", background=c["page"], foreground=c["text"], font=("Segoe UI Semibold", 14))
    style.configure("Subtitle.TLabel", background=c["page"], foreground=c["muted"], font=("Segoe UI", 9))

    style.configure(
        "Accent.TButton",
        font=("Segoe UI Semibold", 9),
        background=c["accent"],
        foreground="#FFFFFF",
        padding=(10, 5),
        borderwidth=0,
    )
    style.map(
        "Accent.TButton",
        background=[("active", c["accent_hover"]), ("pressed", c["accent_hover"])],
        foreground=[("disabled", "#A0AAB4")],
    )
    style.configure("Toolbar.TButton", font=("Segoe UI", 8), padding=(6, 3))
    style.configure(
        "Ghost.TButton",
        font=("Segoe UI", 8),
        background=c["page"],
        foreground=c["muted"],
        padding=(8, 3),
    )
    style.map("Ghost.TButton", background=[("active", c["sidebar"])], foreground=[("active", c["text"])])

    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=c["edge"],
        background=c["accent"],
        bordercolor=c["edge"],
        lightcolor=c["accent"],
        darkcolor=c["accent"],
    )
    style.configure(
        "Treeview",
        font=("Segoe UI", 9),
        rowheight=24,
        fieldbackground=c["card"],
        background=c["card"],
        foreground=c["text"],
        borderwidth=0,
    )
    style.configure(
        "Treeview.Heading",
        font=("Segoe UI Semibold", 8),
        background=c["sidebar"],
        foreground=c["muted"],
        relief="flat",
    )
    style.map("Treeview", background=[("selected", c["accent"])], foreground=[("selected", "#FFFFFF")])
    style.map("Treeview.Heading", background=[("active", c["edge"])])

    style.configure("TLabelframe", background=c["sidebar"], borderwidth=0)
    style.configure(
        "TLabelframe.Label",
        background=c["sidebar"],
        foreground=c["accent"],
        font=("Segoe UI Semibold", 8),
    )
    return c


def make_card(parent, colors: dict, padding=(10, 8)) -> tuple[tk.Frame, ttk.Frame]:
    outer = tk.Frame(parent, bg=colors["card"], highlightbackground=colors["edge"], highlightthickness=1, bd=0)
    inner = ttk.Frame(outer, style="Card.TFrame", padding=padding)
    inner.pack(fill=tk.BOTH, expand=True)
    return outer, inner


def format_size(num_bytes: float) -> str:
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(num_bytes) < 1024.0:
            return f"{num_bytes:3.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} TB"


# ---------------------------------------------------------------------------
# Plugin base
# ---------------------------------------------------------------------------

class BaseFileOperation(ABC):
    name = "Base Operation"
    description = "Generic file operation"
    supported_extensions: Tuple[str, ...] = ()
    # When False, host / standalone hide the output-directory controls.
    needs_output_dir: bool = True

    def __init__(self):
        pass

    @staticmethod
    def unique_paths_in_order(paths):
        unique_files = []
        seen = set()
        for path in paths:
            absolute_path = os.path.abspath(path)
            normalized_key = os.path.normcase(absolute_path)
            if normalized_key in seen:
                continue
            seen.add(normalized_key)
            unique_files.append(absolute_path)
        return unique_files

    @staticmethod
    def expand_patterns(patterns):
        files = []
        for pattern in patterns:
            # Existing paths must not go through glob (brackets [] are character classes).
            if os.path.exists(pattern):
                files.append(pattern)
                continue
            matched = glob.glob(pattern, recursive=True)
            files.extend(matched)
        return files

    @staticmethod
    def load_patterns_from_txt(txt_file):
        patterns = []
        with open(txt_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    patterns.append(line)
        return patterns

    @classmethod
    def collect_input_files(cls, inputs):
        patterns = []
        for item in inputs:
            item = decode_dropped_path(item) if not isinstance(item, str) else item.strip("\x00").strip()
            if not item:
                continue
            # Only treat .txt as a pattern list when it exists; never glob away real files.
            if item.lower().endswith(".txt") and os.path.isfile(item):
                patterns.extend(cls.load_patterns_from_txt(item))
            else:
                patterns.append(item)
        files = cls.expand_patterns(patterns)
        return cls.unique_paths_in_order(files)

    def filter_inputs(self, files):
        if not self.supported_extensions:
            return files
        allowed = tuple(ext.lower() for ext in self.supported_extensions)
        return [f for f in files if Path(f).suffix.lower() in allowed]

    def get_extra_columns(self) -> List[str]:
        return []

    def get_extra_row_data(self, file_path: Path, index: int) -> Dict[str, str]:
        return {}

    def render_options_ui(self, parent_frame, on_change_callback=None):
        pass

    def get_output_path(self, output_dir: str, files: List[str]) -> str:
        return output_dir

    @abstractmethod
    def execute(self, files: List[str], output_path: str, **kwargs) -> Any:
        pass


# ---------------------------------------------------------------------------
# Standalone single-plugin GUI
# ---------------------------------------------------------------------------

class StandalonePluginApp:
    """Compact window for running one plugin by itself (`python plugins/foo.py`)."""

    def __init__(self, root: tk.Tk, plugin: BaseFileOperation):
        self.root = root
        self.plugin = plugin
        self.file_queue: List[dict] = []
        self.colors = apply_toolkit_styles(root)

        self.root.title(plugin.name)
        self.root.geometry("720x560")
        self.root.minsize(560, 420)
        center_window(self.root, 720, 560)

        self._build()
        self._drop_bridge = TkDropBridge(self.root, self._process_drop)
        self._drop_bridge.hook(self.root)

    def _build(self):
        c = self.colors
        pad = ttk.Frame(self.root, padding=(10, 8))
        pad.pack(fill=tk.BOTH, expand=True)
        pad.columnconfigure(0, weight=1)
        pad.rowconfigure(1, weight=1)

        head = ttk.Frame(pad)
        head.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        ttk.Label(head, text=self.plugin.name, style="Title.TLabel").pack(side=tk.LEFT)
        exts = getattr(self.plugin, "supported_extensions", ()) or ()
        hint = ", ".join(exts) if exts else "any"
        ttk.Label(head, text=hint, style="Subtitle.TLabel").pack(side=tk.LEFT, padx=(10, 0))

        body = ttk.Frame(pad)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        # Files
        files_outer, files_inner = make_card(body, c, padding=(8, 6))
        files_outer.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        files_inner.columnconfigure(0, weight=1)
        files_inner.rowconfigure(1, weight=1)

        ttk.Label(files_inner, text="FILES", style="CardSection.TLabel").grid(row=0, column=0, sticky="w")
        list_frame = ttk.Frame(files_inner, style="Card.TFrame")
        list_frame.grid(row=1, column=0, sticky="nsew", pady=4)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)

        self.listbox = tk.Listbox(
            list_frame,
            font=("Segoe UI", 9),
            bg=c["card"],
            fg=c["text"],
            selectbackground=c["accent"],
            selectforeground="#FFFFFF",
            relief=tk.FLAT,
            highlightthickness=0,
            activestyle="none",
        )
        self.listbox.grid(row=0, column=0, sticky="nsew")
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")

        btn_row = ttk.Frame(files_inner, style="Card.TFrame")
        btn_row.grid(row=2, column=0, sticky="ew")
        ttk.Button(btn_row, text="Add", style="Toolbar.TButton", command=self._add_files).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(btn_row, text="Remove", style="Toolbar.TButton", command=self._remove).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(btn_row, text="Clear", style="Toolbar.TButton", command=self._clear).pack(side=tk.LEFT)

        # Options
        opts_outer, opts_inner = make_card(body, c, padding=(8, 6))
        opts_outer.grid(row=0, column=1, sticky="nsew")
        ttk.Label(opts_inner, text="OPTIONS", style="CardSection.TLabel").pack(anchor=tk.W)
        self.opts_host = ttk.Frame(opts_inner, style="Card.TFrame")
        self.opts_host.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        try:
            ui = self.plugin.render_options_ui(self.opts_host, on_change_callback=None)
            if ui:
                ui.pack(fill=tk.BOTH, expand=True)
        except Exception as e:
            ttk.Label(self.opts_host, text=f"Options error: {e}", foreground="red").pack()

        # Bottom actions
        bottom = ttk.Frame(pad)
        bottom.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        self.output_frame = ttk.Frame(bottom)
        self.output_var = tk.StringVar(value="")
        if self.plugin.needs_output_dir:
            self.output_frame.pack(fill=tk.X, pady=(0, 6))
            ttk.Label(self.output_frame, text="Output").pack(side=tk.LEFT, padx=(0, 6))
            ttk.Entry(self.output_frame, textvariable=self.output_var).pack(
                side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4)
            )
            ttk.Button(self.output_frame, text="...", style="Toolbar.TButton", width=3, command=self._browse_out).pack(
                side=tk.LEFT
            )

        act = ttk.Frame(bottom)
        act.pack(fill=tk.X)
        self.status = ttk.Label(act, text="Ready", style="Subtitle.TLabel")
        self.status.pack(side=tk.LEFT)
        ttk.Button(act, text="Start", style="Accent.TButton", command=self._run).pack(side=tk.RIGHT)

    def _paths(self) -> List[str]:
        return [item["path"] for item in self.file_queue]

    def _refresh_list(self):
        self.listbox.delete(0, tk.END)
        for item in self.file_queue:
            self.listbox.insert(tk.END, item["name"])

    def _append(self, path_str: str):
        path = Path(path_str)
        if not path.exists() or any(i["path"] == str(path) for i in self.file_queue):
            return
        self.file_queue.append({"path": str(path), "name": path.name})

    def _add_files(self):
        exts = getattr(self.plugin, "supported_extensions", ()) or ()
        filetypes = [("Supported", " ".join(f"*{e}" for e in exts))] if exts else []
        filetypes.append(("All", "*.*"))
        selected = filedialog.askopenfilenames(filetypes=filetypes)
        if not selected:
            return
        collected = self.plugin.collect_input_files(selected)
        collected = self.plugin.filter_inputs(collected)
        for p in collected:
            self._append(p)
        if collected and self.plugin.needs_output_dir and not self.output_var.get().strip():
            self.output_var.set(str(Path(collected[0]).parent))
        self._refresh_list()

    def _process_drop(self, paths: list):
        collected = self.plugin.filter_inputs(self.plugin.collect_input_files(paths))
        for p in collected:
            self._append(p)
        if collected and self.plugin.needs_output_dir:
            self.output_var.set(str(Path(collected[0]).parent))
        self._refresh_list()
        if not collected and paths:
            messagebox.showwarning(
                "Drop",
                "No matching files were added.\n"
                f"This tool accepts: {', '.join(self.plugin.supported_extensions) or 'any'}",
            )

    def _remove(self):
        sel = list(self.listbox.curselection())
        for idx in reversed(sel):
            if 0 <= idx < len(self.file_queue):
                self.file_queue.pop(idx)
        self._refresh_list()

    def _clear(self):
        self.file_queue.clear()
        self._refresh_list()

    def _browse_out(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_var.set(folder)

    def _resolve_out(self) -> str:
        if not self.plugin.needs_output_dir:
            if self.file_queue:
                return str(Path(self.file_queue[0]["path"]).parent)
            return str(Path.cwd())
        explicit = self.output_var.get().strip()
        if explicit:
            return explicit
        if self.file_queue:
            return str(Path(self.file_queue[0]["path"]).parent)
        return str(Path.cwd())

    def _run(self):
        if not self.file_queue:
            messagebox.showwarning("Queue Empty", "Add files first.")
            return
        files = self._paths()
        out_dir = self._resolve_out()
        if self.plugin.needs_output_dir:
            os.makedirs(out_dir, exist_ok=True)
        try:
            self.status.configure(text="Running...")
            self.root.update()
            output_path = self.plugin.get_output_path(out_dir, files)
            self.plugin.execute(files, output_path)
            self.status.configure(text="Done")
            msg = "Completed." if not self.plugin.needs_output_dir else f"Completed.\nSaved to: {output_path}"
            messagebox.showinfo("Success", msg)
        except Exception as e:
            self.status.configure(text="Failed")
            messagebox.showerror("Error", str(e))


def run_plugin_gui(plugin: BaseFileOperation):
    """Launch the compact standalone GUI for a plugin instance."""
    root = tk.Tk()
    StandalonePluginApp(root, plugin)
    root.mainloop()


def plugin_entry(plugin_cls: type, cli_main: Optional[Callable[[], None]] = None):
    """Standard plugin `__main__` helper: no args → GUI; with args → CLI."""
    if len(sys.argv) <= 1:
        run_plugin_gui(plugin_cls())
        return
    if cli_main:
        cli_main()
    else:
        run_plugin_gui(plugin_cls())


# ---------------------------------------------------------------------------
# Host application
# ---------------------------------------------------------------------------

class UniversalToolkitApp:
    APP_NAME = "Universal File Toolkit"
    APP_SUBTITLE = "Modular batch tools — drop plugins into /plugins"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(self.APP_NAME)
        self.root.geometry("1000x640")
        self.root.minsize(800, 480)
        center_window(self.root, 1000, 640)

        self.operations: Dict[str, BaseFileOperation] = {}
        self.file_queue: List[dict] = []
        self.current_plugin: Optional[BaseFileOperation] = None
        self._log_redirect = None
        self._plugin_options: Dict[str, dict] = {}
        self._drag_iids: List[str] = []
        self._dragging = False
        self._state_loading = False
        self.colors = apply_toolkit_styles(root)

        self.load_plugins()
        self.build_ui()
        self._hook_logging()
        self._drop_bridge = TkDropBridge(self.root, self._process_drop)
        self._drop_bridge.hook(self.root)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._load_state()

    def _make_card(self, parent, padding=(10, 8)):
        return make_card(parent, self.colors, padding=padding)

    def load_plugins(self):
        plugins_dir = ROOT_DIR / "plugins"
        plugins_dir.mkdir(exist_ok=True)

        for _, module_name, _ in pkgutil.iter_modules([str(plugins_dir)]):
            try:
                mod = importlib.import_module(f"plugins.{module_name}")
                seen_classes = set()
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if (
                        isinstance(attr, type)
                        and issubclass(attr, BaseFileOperation)
                        and attr is not BaseFileOperation
                        and attr not in seen_classes
                    ):
                        seen_classes.add(attr)
                        instance = attr()
                        self.operations[instance.name] = instance
            except Exception as e:
                print(f"Failed to load plugin {module_name}: {e}")

    def build_ui(self):
        c = self.colors

        header = ttk.Frame(self.root, padding=(12, 8, 12, 4))
        header.pack(fill=tk.X)

        title_block = ttk.Frame(header)
        title_block.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ttk.Label(title_block, text=self.APP_NAME, style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(title_block, text=self.APP_SUBTITLE, style="Subtitle.TLabel").pack(anchor=tk.W)

        ttk.Button(header, text="About", style="Ghost.TButton", command=self.show_about).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(header, text="Open Script Dir", style="Toolbar.TButton", command=self.open_script_dir).pack(
            side=tk.RIGHT
        )

        body = ttk.Frame(self.root, padding=(12, 4, 12, 10))
        body.pack(fill=tk.BOTH, expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        sidebar_shell = tk.Frame(body, bg=c["sidebar"], highlightbackground=c["edge"], highlightthickness=1, bd=0)
        sidebar_shell.grid(row=0, column=0, sticky="nsw", padx=(0, 8))
        sidebar = ttk.Frame(sidebar_shell, style="Sidebar.TFrame", padding=(10, 10))
        sidebar.pack(fill=tk.BOTH, expand=True)

        ttk.Label(sidebar, text="ACTIVE TOOL", style="SidebarSection.TLabel").pack(anchor=tk.W, pady=(0, 4))
        self.tool_var = tk.StringVar()
        tool_names = list(self.operations.keys())
        self.tool_dropdown = ttk.Combobox(
            sidebar, textvariable=self.tool_var, values=tool_names, state="readonly", width=26
        )
        self.tool_dropdown.pack(fill=tk.X, pady=(0, 2))
        if tool_names:
            self.tool_dropdown.current(0)
            self.current_plugin = self.operations[tool_names[0]]
        self.tool_dropdown.bind("<<ComboboxSelected>>", self.on_tool_changed)

        self.formats_lbl = ttk.Label(sidebar, text="", style="SidebarMuted.TLabel", wraplength=230)
        self.formats_lbl.pack(anchor=tk.W, pady=(0, 8))

        ttk.Label(sidebar, text="TOOL OPTIONS", style="SidebarSection.TLabel").pack(anchor=tk.W, pady=(0, 4))

        opts_canvas = tk.Canvas(sidebar, highlightthickness=0, bg=c["sidebar"], width=240)
        opts_scroll = ttk.Scrollbar(sidebar, orient=tk.VERTICAL, command=opts_canvas.yview)
        self.sidebar_content = ttk.Frame(opts_canvas, style="Sidebar.TFrame")
        self.sidebar_content.bind(
            "<Configure>", lambda e: opts_canvas.configure(scrollregion=opts_canvas.bbox("all"))
        )
        opts_window = opts_canvas.create_window((0, 0), window=self.sidebar_content, anchor="nw")
        opts_canvas.configure(yscrollcommand=opts_scroll.set)
        self._opts_canvas = opts_canvas

        def _sync_opts_width(event):
            opts_canvas.itemconfigure(opts_window, width=event.width)

        opts_canvas.bind("<Configure>", _sync_opts_width)
        opts_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        opts_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        # Only scroll the options canvas when the pointer is over the sidebar
        def _sidebar_wheel(event):
            opts_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        def _sidebar_enter(_event=None):
            opts_canvas.bind_all("<MouseWheel>", _sidebar_wheel)

        def _sidebar_leave(_event=None):
            opts_canvas.unbind_all("<MouseWheel>")

        sidebar_shell.bind("<Enter>", _sidebar_enter)
        sidebar_shell.bind("<Leave>", _sidebar_leave)
        opts_canvas.bind("<MouseWheel>", _sidebar_wheel)
        self.sidebar_content.bind("<MouseWheel>", _sidebar_wheel)

        main = ttk.Frame(body)
        main.grid(row=0, column=1, sticky="nsew")
        main.columnconfigure(0, weight=1)
        main.rowconfigure(0, weight=3)
        main.rowconfigure(2, weight=1)

        files_outer, files_inner = self._make_card(main)
        files_outer.grid(row=0, column=0, sticky="nsew", pady=(0, 6))
        files_inner.columnconfigure(0, weight=1)
        files_inner.rowconfigure(1, weight=1)

        ttk.Label(files_inner, text="FILE QUEUE", style="CardSection.TLabel").grid(row=0, column=0, sticky="w")

        search_row = ttk.Frame(files_inner, style="Card.TFrame")
        search_row.grid(row=0, column=0, sticky="e")
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *args: self.refresh_treeview())
        ttk.Entry(search_row, textvariable=self.search_var, width=18).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(search_row, text="✕", style="Toolbar.TButton", width=3, command=lambda: self.search_var.set("")).pack(
            side=tk.LEFT
        )

        table_frame = ttk.Frame(files_inner, style="Card.TFrame")
        table_frame.grid(row=1, column=0, sticky="nsew", pady=(4, 4))
        table_frame.columnconfigure(0, weight=1)
        table_frame.rowconfigure(0, weight=1)

        self.tree = ttk.Treeview(table_frame, show="headings", selectmode="extended")
        self.tree.grid(row=0, column=0, sticky="nsew")
        tree_scroll = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tree_scroll.set)
        tree_scroll.grid(row=0, column=1, sticky="ns")
        self.tree.bind("<ButtonPress-1>", self._on_tree_press, add="+")
        self.tree.bind("<B1-Motion>", self._on_tree_motion, add="+")
        self.tree.bind("<ButtonRelease-1>", self._on_tree_release, add="+")

        queue_row = ttk.Frame(files_inner, style="Card.TFrame")
        queue_row.grid(row=2, column=0, sticky="ew")
        ttk.Button(queue_row, text="Add", style="Toolbar.TButton", command=self.add_files).pack(side=tk.LEFT, padx=(0, 3))
        ttk.Button(queue_row, text="Remove", style="Toolbar.TButton", command=self.remove_selected).pack(
            side=tk.LEFT, padx=(0, 3)
        )
        ttk.Button(queue_row, text="Clear", style="Toolbar.TButton", command=self.clear_queue).pack(side=tk.LEFT)
        ttk.Label(queue_row, text="Drag rows to reorder", style="CardMuted.TLabel").pack(side=tk.LEFT, padx=(8, 0))
        self.queue_info_lbl = ttk.Label(queue_row, text="0 files", style="CardMuted.TLabel")
        self.queue_info_lbl.pack(side=tk.RIGHT)

        # Output + actions (output row shown only when plugin needs it)
        out_outer, out_inner = self._make_card(main)
        out_outer.grid(row=1, column=0, sticky="ew", pady=(0, 6))
        self.out_card_inner = out_inner

        self.output_section = ttk.Frame(out_inner, style="Card.TFrame")
        ttk.Label(self.output_section, text="OUTPUT", style="CardSection.TLabel").pack(anchor=tk.W, pady=(0, 4))
        out_row = ttk.Frame(self.output_section, style="Card.TFrame")
        out_row.pack(fill=tk.X)
        self.output_entry_var = tk.StringVar(value="")
        ttk.Entry(out_row, textvariable=self.output_entry_var).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 4))
        ttk.Button(out_row, text="Browse", style="Toolbar.TButton", command=self.browse_output).pack(side=tk.LEFT)
        ttk.Label(
            self.output_section,
            text="Empty = beside source files",
            style="CardMuted.TLabel",
        ).pack(anchor=tk.W, pady=(2, 0))

        self._action_row = ttk.Frame(out_inner, style="Card.TFrame")
        self._action_row.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(self._action_row, text="Start", style="Accent.TButton", command=self.run_operation).pack(side=tk.RIGHT)
        self.progressbar = ttk.Progressbar(self._action_row, orient=tk.HORIZONTAL, mode="determinate", length=160)
        self.progressbar.pack(side=tk.RIGHT, fill=tk.X, expand=True, padx=(0, 8))
        self.status_lbl = ttk.Label(self._action_row, text="Ready", style="CardMuted.TLabel")
        self.status_lbl.pack(side=tk.LEFT)

        log_outer, log_inner = self._make_card(main)
        log_outer.grid(row=2, column=0, sticky="nsew")
        log_inner.columnconfigure(0, weight=1)
        log_inner.rowconfigure(1, weight=1)

        ttk.Label(log_inner, text="LOG", style="CardSection.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 4))
        self.log_text = tk.Text(
            log_inner,
            height=6,
            wrap=tk.WORD,
            bg=c["log_bg"],
            fg=c["log_fg"],
            insertbackground=c["log_fg"],
            font=("Consolas", 8),
            relief=tk.FLAT,
            bd=0,
            padx=8,
            pady=6,
            highlightthickness=0,
        )
        self.log_text.grid(row=1, column=0, sticky="nsew")
        self.log_text.configure(state=tk.DISABLED)

        self.refresh_plugin_ui()
        self.refresh_treeview()
        self._sync_output_section()

    def _hook_logging(self):
        app = self

        class _LogWriter:
            def __init__(self, stream):
                self._stream = stream

            def write(self, msg):
                if self._stream:
                    try:
                        self._stream.write(msg)
                    except UnicodeEncodeError:
                        self._stream.write(msg.encode(self._stream.encoding or "utf-8", errors="replace").decode(
                            self._stream.encoding or "utf-8", errors="replace"
                        ))
                if msg and msg.strip():
                    app.append_log(msg.rstrip("\n"))

            def flush(self):
                if self._stream:
                    self._stream.flush()

        self._log_redirect = _LogWriter(sys.stdout)
        sys.stdout = self._log_redirect

    def append_log(self, message: str):
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {message}"

        def _write():
            self.log_text.configure(state=tk.NORMAL)
            self.log_text.insert(tk.END, line + "\n")
            self.log_text.see(tk.END)
            self.log_text.configure(state=tk.DISABLED)

        self.root.after(0, _write)

    def script_dir(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent
        return ROOT_DIR

    def open_script_dir(self):
        path = self.script_dir()
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except Exception as e:
            messagebox.showerror("Open Folder", f"Could not open folder:\n{e}")

    def show_about(self):
        c = self.colors
        win = tk.Toplevel(self.root)
        win.title("About")
        win.configure(bg=c["page"])
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        frame = ttk.Frame(win, padding=16)
        frame.pack(fill=tk.BOTH, expand=True)

        ttk.Label(frame, text=self.APP_NAME, style="Title.TLabel").pack(anchor=tk.W)
        ttk.Label(
            frame,
            text=AUTHOR_NAME,
            font=("Segoe UI Semibold", 10),
            background=c["page"],
        ).pack(anchor=tk.W, pady=(8, 2))
        make_link_label(frame, AUTHOR_EMAIL, f"mailto:{AUTHOR_EMAIL}", c, anchor=tk.W)
        make_link_label(frame, AUTHOR_GITHUB, AUTHOR_GITHUB, c, anchor=tk.W, pady=(2, 10))
        ttk.Label(
            frame,
            text="Drop-in plugins in /plugins auto-load here.\n"
            "Each plugin also runs alone:  python plugins/<name>.py",
            style="Subtitle.TLabel",
            justify=tk.LEFT,
        ).pack(anchor=tk.W, pady=(0, 12))
        ttk.Button(frame, text="Close", style="Toolbar.TButton", command=win.destroy).pack(anchor=tk.E)

        win.update_idletasks()
        w = win.winfo_reqwidth()
        h = win.winfo_reqheight()
        center_window(win, w, h)

    def resolve_output_dir(self) -> str:
        if self.current_plugin and not getattr(self.current_plugin, "needs_output_dir", True):
            if self.file_queue:
                return str(Path(self.file_queue[0]["path"]).parent)
            return str(self.script_dir())
        explicit = self.output_entry_var.get().strip()
        if explicit:
            return explicit
        if self.file_queue:
            return str(Path(self.file_queue[0]["path"]).parent)
        return str(self.script_dir() / "output")

    def on_tool_changed(self, event=None):
        if self.current_plugin and not self._state_loading:
            self._plugin_options[self.current_plugin.name] = self._collect_plugin_options()
        name = self.tool_var.get()
        if name in self.operations:
            self.current_plugin = self.operations[name]
            self.refresh_plugin_ui()
            self._apply_plugin_options(self._plugin_options.get(name, {}))
            self.refresh_treeview()
            self._sync_output_section()
            if not self._state_loading:
                self.append_log(f"Tool: {name}")
                self._save_state()

    def _sync_output_section(self):
        needs = bool(self.current_plugin and getattr(self.current_plugin, "needs_output_dir", True))
        for child in list(self.out_card_inner.winfo_children()):
            child.pack_forget()
        if needs:
            self.output_section.pack(fill=tk.X)
        self._action_row.pack(fill=tk.X, pady=(6 if needs else 0, 0))

    def _collect_plugin_options(self) -> dict:
        opts = {}
        if not self.current_plugin:
            return opts
        for name in dir(self.current_plugin):
            if not name.endswith("_var"):
                continue
            attr = getattr(self.current_plugin, name, None)
            if hasattr(attr, "get"):
                try:
                    opts[name] = attr.get()
                except Exception:
                    pass
        return opts

    def _apply_plugin_options(self, opts: dict):
        if not self.current_plugin or not opts:
            return
        for name, value in opts.items():
            attr = getattr(self.current_plugin, name, None)
            if hasattr(attr, "set"):
                try:
                    attr.set(value)
                except Exception:
                    pass

    def refresh_plugin_ui(self):
        for widget in self.sidebar_content.winfo_children():
            widget.destroy()

        if not self.current_plugin:
            return

        exts = getattr(self.current_plugin, "supported_extensions", ())
        self.formats_lbl.configure(text=f"Accepted: {', '.join(exts)}" if exts else "Accepted: any")

        def _options_changed(*_a):
            if self._state_loading:
                return
            if self.current_plugin:
                self._plugin_options[self.current_plugin.name] = self._collect_plugin_options()
            self.refresh_treeview()
            self._schedule_save()

        try:
            try:
                ui_frame = self.current_plugin.render_options_ui(
                    self.sidebar_content, on_change_callback=_options_changed
                )
            except TypeError:
                ui_frame = self.current_plugin.render_options_ui(self.sidebar_content)

            if ui_frame:
                ui_frame.pack(fill=tk.BOTH, expand=True)
        except Exception as e:
            ttk.Label(self.sidebar_content, text=f"Error: {e}", foreground="red").pack()

        # Rebind wheel on new option widgets
        def _wheel(event):
            self._opts_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
            return "break"

        self._bind_wheel_recursive(self.sidebar_content, _wheel)

    def refresh_treeview(self):
        extra_cols = []
        if self.current_plugin and hasattr(self.current_plugin, "get_extra_columns"):
            extra_cols = self.current_plugin.get_extra_columns() or []

        all_cols = ["name", "ext", "size", "status"] + extra_cols
        self.tree["columns"] = all_cols

        self.tree.heading("name", text="Name", anchor=tk.W)
        self.tree.heading("ext", text="Type", anchor=tk.CENTER)
        self.tree.heading("size", text="Size", anchor=tk.E)
        self.tree.heading("status", text="Status", anchor=tk.CENTER)

        self.tree.column("name", width=220, minwidth=100, stretch=True)
        self.tree.column("ext", width=55, minwidth=40, anchor=tk.CENTER, stretch=False)
        self.tree.column("size", width=70, minwidth=50, anchor=tk.E, stretch=False)
        self.tree.column("status", width=70, minwidth=50, anchor=tk.CENTER, stretch=False)

        for col in extra_cols:
            self.tree.heading(col, text=col, anchor=tk.W)
            self.tree.column(col, width=180, minwidth=100, stretch=True)

        for item in self.tree.get_children():
            self.tree.delete(item)

        query = self.search_var.get().strip().lower()
        visible_count = 0
        total_bytes = 0

        for idx, item in enumerate(self.file_queue):
            total_bytes += item["bytes"]
            if query and query not in item["name"].lower() and query not in item["ext"].lower():
                continue
            visible_count += 1
            row_values = [item["name"], item["ext"].upper(), item["size_str"], item["status"]]
            if self.current_plugin and extra_cols and hasattr(self.current_plugin, "get_extra_row_data"):
                extra_data = self.current_plugin.get_extra_row_data(Path(item["path"]), idx)
                for col in extra_cols:
                    row_values.append(extra_data.get(col, ""))
            self.tree.insert("", tk.END, iid=str(idx), values=row_values)

        if not self.file_queue:
            placeholder = ["Drop files or Add", "", "", ""] + [""] * len(extra_cols)
            self.tree.insert("", tk.END, iid="placeholder", values=placeholder)

        filtered_str = f" / {len(self.file_queue)}" if query else ""
        self.queue_info_lbl.configure(text=f"{visible_count}{filtered_str} · {format_size(total_bytes)}")

    def _bind_wheel_recursive(self, widget, handler):
        widget.bind("<MouseWheel>", handler)
        for child in widget.winfo_children():
            self._bind_wheel_recursive(child, handler)

    def _on_tree_press(self, event):
        row = self.tree.identify_row(event.y)
        if not row or row == "placeholder" or not row.isdigit():
            self._drag_iids = []
            self._dragging = False
            return
        sel = list(self.tree.selection())
        if row not in sel:
            # Let default selection happen; capture after a tick
            self.root.after_idle(lambda: self._capture_drag_selection(row))
        else:
            self._drag_iids = [i for i in sel if i.isdigit()]
            self._dragging = True

    def _capture_drag_selection(self, row: str):
        sel = list(self.tree.selection())
        if row not in sel:
            sel = [row]
        self._drag_iids = [i for i in sel if i.isdigit()]
        self._dragging = bool(self._drag_iids)

    def _on_tree_motion(self, event):
        if not self._dragging or not self._drag_iids:
            return
        row = self.tree.identify_row(event.y)
        if row and row.isdigit():
            self.tree.selection_set(self._drag_iids)

    def _on_tree_release(self, event):
        if not self._dragging or not self._drag_iids:
            self._dragging = False
            return
        self._dragging = False
        target = self.tree.identify_row(event.y)
        if not target or target == "placeholder" or not target.isdigit():
            return
        selected = sorted({int(i) for i in self._drag_iids if i.isdigit()})
        if not selected:
            return
        dest = int(target)
        if dest in selected and len(selected) == 1:
            return
        moving = [self.file_queue[i] for i in selected]
        rest = [item for i, item in enumerate(self.file_queue) if i not in selected]
        n_before = sum(1 for i in selected if i < dest)
        dest_adj = dest - n_before
        dest_adj = max(0, min(dest_adj, len(rest)))
        self.file_queue = rest[:dest_adj] + moving + rest[dest_adj:]
        self.append_log(f"Reordered {len(moving)} file(s)")
        self.refresh_treeview()
        # Reselect moved block
        for i in range(dest_adj, dest_adj + len(moving)):
            self.tree.selection_add(str(i))
        self._save_state()

    def add_files(self):
        exts = getattr(self.current_plugin, "supported_extensions", ())
        filetypes = [("Supported Files", " ".join(f"*{ext}" for ext in exts))] if exts else []
        filetypes.append(("All Files", "*.*"))
        selected_paths = filedialog.askopenfilenames(filetypes=filetypes)
        if not selected_paths:
            return
        collected = BaseFileOperation.collect_input_files(selected_paths)
        if self.current_plugin:
            collected = self.current_plugin.filter_inputs(collected)
        before = len(self.file_queue)
        for p_str in collected:
            self._append_file_path(p_str)
        added = len(self.file_queue) - before
        if (
            collected
            and self.current_plugin
            and getattr(self.current_plugin, "needs_output_dir", True)
            and not self.output_entry_var.get().strip()
        ):
            self.output_entry_var.set(str(Path(collected[0]).parent))
        self.refresh_treeview()
        if added:
            self.append_log(f"Added {added} file(s)")
            self._save_state()

    def _process_drop(self, paths: list):
        collected = BaseFileOperation.collect_input_files(paths)
        if self.current_plugin:
            collected = self.current_plugin.filter_inputs(collected)
        before = len(self.file_queue)
        for p in collected:
            self._append_file_path(p)
        added = len(self.file_queue) - before
        if added and self.current_plugin and getattr(self.current_plugin, "needs_output_dir", True):
            self.output_entry_var.set(str(Path(collected[0]).parent))
            self.append_log(f"Dropped {added} -> {self.output_entry_var.get()}")
            self._save_state()
        elif added:
            self.append_log(f"Dropped {added} item(s)")
            self._save_state()
        elif paths:
            accepted = getattr(self.current_plugin, "supported_extensions", ()) or ()
            hint = ", ".join(accepted) if accepted else "any"
            self.append_log(f"Drop ignored (no matching files). Accepted: {hint}")
            messagebox.showwarning(
                "Drop",
                "No matching files were added to the queue.\n"
                f"Active tool accepts: {hint}\n"
                f"Received: {', '.join(Path(p).name for p in paths[:5])}",
            )
        self.refresh_treeview()

    def _append_file_path(self, path_str):
        path = Path(path_str)
        if not path.exists() or any(item["path"] == str(path) for item in self.file_queue):
            return
        size = path.stat().st_size if path.is_file() else 0
        self.file_queue.append(
            {
                "path": str(path),
                "name": path.name,
                "ext": path.suffix.replace(".", ""),
                "size_str": format_size(size),
                "bytes": size,
                "status": "Ready",
            }
        )

    def remove_selected(self):
        selected_iids = self.tree.selection()
        if not selected_iids:
            return
        indices = sorted([int(iid) for iid in selected_iids if iid.isdigit()], reverse=True)
        removed = 0
        for idx in indices:
            if 0 <= idx < len(self.file_queue):
                self.file_queue.pop(idx)
                removed += 1
        self.refresh_treeview()
        if removed:
            self.append_log(f"Removed {removed} file(s)")
            self._save_state()

    def clear_queue(self):
        n = len(self.file_queue)
        self.file_queue.clear()
        self.refresh_treeview()
        if n:
            self.append_log(f"Cleared queue ({n} files)")
            self._save_state()

    def browse_output(self):
        folder = filedialog.askdirectory()
        if folder:
            self.output_entry_var.set(folder)
            self.append_log(f"Output dir: {folder}")
            self._save_state()

    def _schedule_save(self):
        if self._state_loading:
            return
        self.root.after(400, self._save_state)

    def _save_state(self):
        if self._state_loading:
            return
        if self.current_plugin:
            self._plugin_options[self.current_plugin.name] = self._collect_plugin_options()
        data = {
            "selected_tool": self.tool_var.get(),
            "output_directory": self.output_entry_var.get(),
            "file_paths": [item["path"] for item in self.file_queue],
            "plugin_options": self._plugin_options,
            "geometry": self.root.geometry(),
        }
        try:
            STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            self.append_log(f"State save failed: {e}")

    def _load_state(self):
        if not STATE_FILE.exists():
            return
        try:
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            self.append_log(f"State load failed: {e}")
            return

        self._state_loading = True
        try:
            self._plugin_options = data.get("plugin_options") or {}
            if data.get("geometry"):
                try:
                    size = parse_geometry_size(data["geometry"])
                    if size:
                        center_window(self.root, size[0], size[1])
                except Exception:
                    pass
            tool = data.get("selected_tool")
            if tool in self.operations:
                self.tool_var.set(tool)
                self.current_plugin = self.operations[tool]
                self.refresh_plugin_ui()
                self._apply_plugin_options(self._plugin_options.get(tool, {}))
                self._sync_output_section()
            if "output_directory" in data:
                self.output_entry_var.set(data.get("output_directory") or "")
            self.file_queue.clear()
            for p in data.get("file_paths") or []:
                self._append_file_path(p)
            self.refresh_treeview()
            self.append_log(
                f"Restored session ({len(self.file_queue)} files"
                + (f", tool={tool}" if tool else "")
                + ")"
            )
        finally:
            self._state_loading = False

    def _on_close(self):
        self._save_state()
        self.root.destroy()

    def run_operation(self):
        if not self.file_queue:
            messagebox.showwarning("Queue Empty", "Add files first.")
            return
        if not self.current_plugin:
            messagebox.showerror("Error", "No plugin selected.")
            return

        output_dir = self.resolve_output_dir()
        if getattr(self.current_plugin, "needs_output_dir", True):
            os.makedirs(output_dir, exist_ok=True)

        target_files = [item["path"] for item in self.file_queue]
        tool_name = self.current_plugin.name
        t0 = time.perf_counter()
        self.append_log(f"Start: {tool_name} ({len(target_files)} files)")
        try:
            self.progressbar.configure(value=0, maximum=len(target_files))
            self.status_lbl.configure(text="Running...")
            self.root.update()
            for item in self.file_queue:
                item["status"] = "Processing"
            self.refresh_treeview()

            output_path = self.current_plugin.get_output_path(output_dir, target_files)
            self.current_plugin.execute(target_files, output_path)

            elapsed = time.perf_counter() - t0
            for item in self.file_queue:
                item["status"] = "Done"
            self.progressbar.configure(value=len(target_files))
            self.status_lbl.configure(text=f"Done ({elapsed:.2f}s)")
            self.refresh_treeview()
            self.append_log(f"Done: {tool_name} in {elapsed:.2f}s -> {output_path}")
            self._save_state()
            if getattr(self.current_plugin, "needs_output_dir", True):
                messagebox.showinfo("Success", f"Completed in {elapsed:.2f}s.\nSaved to: {output_path}")
            else:
                messagebox.showinfo("Success", f"Completed in {elapsed:.2f}s.")
        except Exception as e:
            elapsed = time.perf_counter() - t0
            for item in self.file_queue:
                item["status"] = "Error"
            self.refresh_treeview()
            self.status_lbl.configure(text="Failed")
            self.append_log(f"Failed: {tool_name} after {elapsed:.2f}s — {e}")
            messagebox.showerror("Execution Error", str(e))


def main():
    root = tk.Tk()
    UniversalToolkitApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()