"""N-up & Booklet layout plugin — standalone GUI or host toolkit."""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import pymupdf
from PIL import Image

try:
    from plugins import import_host
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from plugins import import_host

_host = import_host()
BaseFileOperation = _host.BaseFileOperation
plugin_entry = _host.plugin_entry

# Pages per nested fold; "All" = one signature for the whole job.
SIGNATURE_CHOICES = ("8", "16", "24", "32", "48", "All")
DEFAULT_PAGES_PER_SIGNATURE = "32"


def booklet_sheet_pairs(n_pages: int, pages_per_signature: int) -> list[tuple[int, int]]:
    """0-based (left, right) page indices for each booklet sheet face across signatures."""
    if n_pages < 0 or n_pages % 4:
        raise ValueError("n_pages must be a non-negative multiple of 4")
    if pages_per_signature < 4 or pages_per_signature % 4:
        raise ValueError("pages_per_signature must be a multiple of 4 and >= 4")
    pairs: list[tuple[int, int]] = []
    for start in range(0, n_pages, pages_per_signature):
        chunk = min(pages_per_signature, n_pages - start)
        for i in range(chunk // 4):
            pairs.append((start + chunk - 1 - 2 * i, start + 2 * i))
            pairs.append((start + 2 * i + 1, start + chunk - 2 - 2 * i))
    return pairs


def parse_pages_per_signature(raw: str, total_pages: int) -> int:
    """Resolve UI/CLI value to a signature size (multiple of 4)."""
    text = (raw or DEFAULT_PAGES_PER_SIGNATURE).strip()
    if text.lower() == "all":
        return max(4, total_pages) if total_pages else 4
    try:
        n = int(text)
    except ValueError:
        n = int(DEFAULT_PAGES_PER_SIGNATURE)
    return max(4, (n // 4) * 4)


class NupBookletPlugin(BaseFileOperation):
    name = "N-up & Booklet"
    description = "Impose pages as 1-up, 2-up, N-up grid, or booklet sheets."
    supported_extensions = (".pdf", ".png", ".jpg", ".jpeg")
    needs_output_dir = True

    def load_page_images(self, files: list) -> list[Image.Image]:
        all_images = []
        for file_str in files:
            f_path = Path(file_str)
            if not f_path.exists():
                continue
            ext = f_path.suffix.lower()
            if ext == ".pdf":
                doc = pymupdf.open(f_path)
                for page in doc:
                    pix = page.get_pixmap(dpi=150)
                    img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
                    all_images.append(img)
                doc.close()
            elif ext in (".png", ".jpg", ".jpeg"):
                all_images.append(Image.open(f_path).convert("RGB"))
        return all_images

    def normalize_and_rotate(self, img: Image.Image, force_rotation: str) -> Image.Image:
        if force_rotation == "Rotate 90° CW":
            return img.rotate(-90, expand=True)
        if force_rotation == "Rotate 90° CCW":
            return img.rotate(90, expand=True)
        if force_rotation == "Auto-Portrait" and img.width > img.height:
            return img.rotate(-90, expand=True)
        if force_rotation == "Auto-Landscape" and img.height > img.width:
            return img.rotate(-90, expand=True)
        return img

    def fit_in_cell(self, img: Image.Image, cell_w: int, cell_h: int) -> Image.Image:
        scale = min(cell_w / img.width, cell_h / img.height)
        new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
        return img.resize(new_size, Image.Resampling.LANCZOS)

    def stitch_two(self, left: Image.Image, right: Image.Image, direction: str) -> Image.Image:
        if direction == "Horizontal":
            if right.height != left.height:
                new_w = int(right.width * (left.height / right.height))
                right = right.resize((new_w, left.height), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (left.width + right.width, left.height), (255, 255, 255))
            canvas.paste(left, (0, 0))
            canvas.paste(right, (left.width, 0))
        else:
            if right.width != left.width:
                new_h = int(right.height * (left.width / right.width))
                right = right.resize((left.width, new_h), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (left.width, left.height + right.height), (255, 255, 255))
            canvas.paste(left, (0, 0))
            canvas.paste(right, (0, left.height))
        return canvas

    def build_nup_sheet(self, pages: list[Image.Image], cols: int, rows: int) -> Image.Image:
        cell_w = max(p.width for p in pages[: cols * rows]) if pages else 100
        cell_h = max(p.height for p in pages[: cols * rows]) if pages else 100
        # Use first page size as cell reference for consistency
        if pages:
            cell_w, cell_h = pages[0].width, pages[0].height
        sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), (255, 255, 255))
        for idx, img in enumerate(pages[: cols * rows]):
            fitted = self.fit_in_cell(img, cell_w, cell_h)
            r, c = divmod(idx, cols)
            x = c * cell_w + (cell_w - fitted.width) // 2
            y = r * cell_h + (cell_h - fitted.height) // 2
            sheet.paste(fitted, (x, y))
        return sheet

    def execute(self, files, output_path, **kwargs):
        if not files:
            raise ValueError("No files provided.")

        mode = getattr(self, "mode_var", tk.StringVar(value="Booklet")).get()
        binding = getattr(self, "binding_var", tk.StringVar(value="Auto")).get()
        rotation = getattr(self, "rotation_var", tk.StringVar(value="None")).get()
        cols = int(self.cols_var.get()) if hasattr(self, "cols_var") and self.cols_var.get().isdigit() else 2
        rows = int(self.rows_var.get()) if hasattr(self, "rows_var") and self.rows_var.get().isdigit() else 2
        cols = max(1, cols)
        rows = max(1, rows)
        out_name = getattr(self, "output_name_var", tk.StringVar(value="nup_output.pdf")).get() or "nup_output.pdf"

        base_out = Path(output_path if os.path.isdir(output_path) else os.path.dirname(output_path) or ".")
        base_out.mkdir(parents=True, exist_ok=True)

        raw = self.load_page_images(files)
        if not raw:
            raise ValueError("No renderable pages found.")
        pages = [self.normalize_and_rotate(p, rotation) for p in raw]

        if binding == "Auto":
            stitch_dir = "Vertical" if pages[0].width > pages[0].height else "Horizontal"
        else:
            stitch_dir = binding

        sheets: list[Image.Image] = []
        sig_note = ""

        if mode == "1-up":
            sheets = pages

        elif mode == "2-up":
            blank = Image.new("RGB", pages[0].size, (255, 255, 255))
            if len(pages) % 2:
                pages.append(blank)
            for i in range(0, len(pages), 2):
                sheets.append(self.stitch_two(pages[i], pages[i + 1], stitch_dir))

        elif mode == "N-up":
            per = cols * rows
            blank = Image.new("RGB", pages[0].size, (255, 255, 255))
            while len(pages) % per:
                pages.append(blank)
            for i in range(0, len(pages), per):
                sheets.append(self.build_nup_sheet(pages[i : i + per], cols, rows))

        elif mode == "Booklet":
            blank = Image.new("RGB", pages[0].size, (255, 255, 255))
            while len(pages) % 4:
                pages.append(blank)
            sig_raw = getattr(self, "signature_var", tk.StringVar(value=DEFAULT_PAGES_PER_SIGNATURE)).get()
            sig_size = parse_pages_per_signature(sig_raw, len(pages))
            for left_i, right_i in booklet_sheet_pairs(len(pages), sig_size):
                sheets.append(self.stitch_two(pages[left_i], pages[right_i], stitch_dir))
            sig_note = f", sig={sig_size}"
        else:
            raise ValueError(f"Unknown mode: {mode}")

        dest = base_out / out_name
        if not dest.suffix.lower() == ".pdf":
            dest = dest.with_suffix(".pdf")
        sheets[0].save(dest, save_all=True, append_images=sheets[1:] if len(sheets) > 1 else [])
        print(f"Saved {mode} ({stitch_dir}{sig_note}) -> {dest}")

    def _toggle_mode_fields(self, *_):
        mode = self.mode_var.get() if hasattr(self, "mode_var") else ""
        if hasattr(self, "_nup_frame"):
            nup_state = "normal" if mode == "N-up" else "disabled"
            for child in self._nup_frame.winfo_children():
                try:
                    child.configure(state=nup_state)
                except tk.TclError:
                    pass
        if hasattr(self, "_sig_cb"):
            try:
                self._sig_cb.configure(state="readonly" if mode == "Booklet" else "disabled")
            except tk.TclError:
                pass

    def render_options_ui(self, parent_frame, on_change_callback=None):
        frame = ttk.Frame(parent_frame, padding=4)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Mode").grid(row=0, column=0, sticky="w", pady=1)
        self.mode_var = tk.StringVar(value="Booklet")
        mode_cb = ttk.Combobox(
            frame,
            textvariable=self.mode_var,
            values=["1-up", "2-up", "N-up", "Booklet"],
            state="readonly",
            width=14,
        )
        mode_cb.grid(row=0, column=1, sticky="ew", pady=1)
        mode_cb.bind("<<ComboboxSelected>>", self._toggle_mode_fields)

        ttk.Label(frame, text="Stitch").grid(row=1, column=0, sticky="w", pady=1)
        self.binding_var = tk.StringVar(value="Auto")
        ttk.Combobox(
            frame,
            textvariable=self.binding_var,
            values=["Auto", "Horizontal", "Vertical"],
            state="readonly",
            width=14,
        ).grid(row=1, column=1, sticky="ew", pady=1)

        ttk.Label(frame, text="Rotate").grid(row=2, column=0, sticky="w", pady=1)
        self.rotation_var = tk.StringVar(value="None")
        ttk.Combobox(
            frame,
            textvariable=self.rotation_var,
            values=["None", "Auto-Portrait", "Auto-Landscape", "Rotate 90° CW", "Rotate 90° CCW"],
            state="readonly",
            width=14,
        ).grid(row=2, column=1, sticky="ew", pady=1)

        self._nup_frame = ttk.Frame(frame)
        self._nup_frame.grid(row=3, column=0, columnspan=2, sticky="ew", pady=2)
        ttk.Label(self._nup_frame, text="Cols").pack(side=tk.LEFT)
        self.cols_var = tk.StringVar(value="2")
        ttk.Entry(self._nup_frame, textvariable=self.cols_var, width=4).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(self._nup_frame, text="Rows").pack(side=tk.LEFT)
        self.rows_var = tk.StringVar(value="2")
        ttk.Entry(self._nup_frame, textvariable=self.rows_var, width=4).pack(side=tk.LEFT, padx=2)

        ttk.Label(frame, text="Sig pages").grid(row=4, column=0, sticky="w", pady=1)
        self.signature_var = tk.StringVar(value=DEFAULT_PAGES_PER_SIGNATURE)
        self._sig_cb = ttk.Combobox(
            frame,
            textvariable=self.signature_var,
            values=list(SIGNATURE_CHOICES),
            state="readonly",
            width=14,
        )
        self._sig_cb.grid(row=4, column=1, sticky="ew", pady=1)

        ttk.Label(frame, text="Output").grid(row=5, column=0, sticky="w", pady=1)
        self.output_name_var = tk.StringVar(value="nup_output.pdf")
        ttk.Entry(frame, textvariable=self.output_name_var, width=16).grid(row=5, column=1, sticky="ew", pady=1)

        self._toggle_mode_fields()
        return frame

    def get_output_path(self, output_dir, files):
        return output_dir


# Keep old module path usable; class renamed for clarity


def _self_check() -> None:
    # One nest of 8 pages: outer (7|0), inner (1|6), then (5|2), (3|4)
    assert booklet_sheet_pairs(8, 8) == [(7, 0), (1, 6), (5, 2), (3, 4)]
    # Two signatures of 8 from 16 pages
    assert booklet_sheet_pairs(16, 8) == [
        (7, 0),
        (1, 6),
        (5, 2),
        (3, 4),
        (15, 8),
        (9, 14),
        (13, 10),
        (11, 12),
    ]
    assert parse_pages_per_signature("All", 40) == 40
    assert parse_pages_per_signature("32", 100) == 32
    assert parse_pages_per_signature("30", 100) == 28
    print("flipbook_generator self-check OK")


def cli_main():
    parser = argparse.ArgumentParser(description="N-up / Booklet page imposition")
    parser.add_argument("-i", "--inputs", nargs="+", required=False, default=[])
    parser.add_argument("-o", "--output", default="")
    parser.add_argument("--mode", choices=["1-up", "2-up", "N-up", "Booklet"], default="Booklet")
    parser.add_argument("--binding", choices=["Auto", "Horizontal", "Vertical"], default="Auto")
    parser.add_argument("--cols", default="2")
    parser.add_argument("--rows", default="2")
    parser.add_argument(
        "--pages-per-signature",
        default=DEFAULT_PAGES_PER_SIGNATURE,
        help=f"Booklet nest size: {', '.join(SIGNATURE_CHOICES)} (default {DEFAULT_PAGES_PER_SIGNATURE})",
    )
    parser.add_argument("--self-check", action="store_true", help="Run booklet signature asserts and exit")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return

    if not args.inputs:
        parser.error("the following arguments are required: -i/--inputs")

    plugin = NupBookletPlugin()
    files = plugin.filter_inputs(plugin.collect_input_files(args.inputs))
    if not files:
        print("No matching files.")
        sys.exit(1)

    plugin.mode_var = tk.StringVar(value=args.mode)
    plugin.binding_var = tk.StringVar(value=args.binding)
    plugin.rotation_var = tk.StringVar(value="None")
    plugin.cols_var = tk.StringVar(value=args.cols)
    plugin.rows_var = tk.StringVar(value=args.rows)
    plugin.signature_var = tk.StringVar(value=args.pages_per_signature)
    plugin.output_name_var = tk.StringVar(value="nup_output.pdf")

    out = args.output.strip() or str(Path(files[0]).parent)
    plugin.execute(files, out)


if __name__ == "__main__":
    plugin_entry(NupBookletPlugin, cli_main)
