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
    from app import BaseFileOperation, plugin_entry
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from app import BaseFileOperation, plugin_entry


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
            total = len(pages)
            for i in range(total // 4):
                sheets.append(self.stitch_two(pages[total - 1 - 2 * i], pages[2 * i], stitch_dir))
                sheets.append(self.stitch_two(pages[2 * i + 1], pages[total - 2 - 2 * i], stitch_dir))
        else:
            raise ValueError(f"Unknown mode: {mode}")

        dest = base_out / out_name
        if not dest.suffix.lower() == ".pdf":
            dest = dest.with_suffix(".pdf")
        sheets[0].save(dest, save_all=True, append_images=sheets[1:] if len(sheets) > 1 else [])
        print(f"Saved {mode} ({stitch_dir}) -> {dest}")

    def _toggle_nup_fields(self, *_):
        if not hasattr(self, "_nup_frame"):
            return
        state = "normal" if self.mode_var.get() == "N-up" else "disabled"
        for child in self._nup_frame.winfo_children():
            try:
                child.configure(state=state)
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
        mode_cb.bind("<<ComboboxSelected>>", self._toggle_nup_fields)

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

        ttk.Label(frame, text="Output").grid(row=4, column=0, sticky="w", pady=1)
        self.output_name_var = tk.StringVar(value="nup_output.pdf")
        ttk.Entry(frame, textvariable=self.output_name_var, width=16).grid(row=4, column=1, sticky="ew", pady=1)

        self._toggle_nup_fields()
        return frame

    def get_output_path(self, output_dir, files):
        return output_dir


# Keep old module path usable; class renamed for clarity


def cli_main():
    parser = argparse.ArgumentParser(description="N-up / Booklet page imposition")
    parser.add_argument("-i", "--inputs", nargs="+", required=True)
    parser.add_argument("-o", "--output", default="")
    parser.add_argument("--mode", choices=["1-up", "2-up", "N-up", "Booklet"], default="Booklet")
    parser.add_argument("--binding", choices=["Auto", "Horizontal", "Vertical"], default="Auto")
    parser.add_argument("--cols", default="2")
    parser.add_argument("--rows", default="2")
    args = parser.parse_args()

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
    plugin.output_name_var = tk.StringVar(value="nup_output.pdf")

    out = args.output.strip() or str(Path(files[0]).parent)
    plugin.execute(files, out)


if __name__ == "__main__":
    plugin_entry(NupBookletPlugin, cli_main)
