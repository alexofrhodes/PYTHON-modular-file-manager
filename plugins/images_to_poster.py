"""Image → multi-page A4 poster PDF (scale + tile via pdfposter)."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
import tkinter as tk
from tkinter import ttk

from PIL import Image

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from pypdf import PdfReader
except ImportError:
    PdfReader = None

try:
    from plugins import import_host
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from plugins import import_host

_host = import_host()
BaseFileOperation = _host.BaseFileOperation
plugin_entry = _host.plugin_entry


def find_pdfposter() -> str | None:
    return shutil.which("pdfposter")


def image_to_pdf(src: Path, dest: Path) -> None:
    """Write a single-page PDF containing the image (or first PDF page as image)."""
    ext = src.suffix.lower()
    if ext == ".pdf":
        if fitz is None:
            raise RuntimeError("PyMuPDF is required to posterize PDF inputs.")
        doc = fitz.open(src)
        try:
            page = doc[0]
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2))
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
        finally:
            doc.close()
    else:
        img = Image.open(src).convert("RGB")
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PDF", resolution=150.0)


def run_pdfposter(in_pdf: Path, out_pdf: Path, cols: int, rows: int, media: str = "A4") -> None:
    exe = find_pdfposter()
    if not exe:
        raise RuntimeError("pdfposter not found. Install with: pip install pdfposter")
    cols = max(1, int(cols))
    rows = max(1, int(rows))
    media = (media or "A4").strip().upper()
    # BOX: NxM + media name, e.g. 2x2A4
    poster_box = f"{cols}x{rows}{media}"
    cmd = [exe, "-m", media, "-p", poster_box, str(in_pdf), str(out_pdf)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip() or f"exit {proc.returncode}"
        raise RuntimeError(f"pdfposter failed: {err}")


def pdf_page_count(path: Path) -> int:
    if PdfReader is None:
        if fitz is None:
            return -1
        doc = fitz.open(path)
        n = len(doc)
        doc.close()
        return n
    return len(PdfReader(str(path)).pages)


class ImagePosterPlugin(BaseFileOperation):
    name = "A4 Poster"
    description = "Scale an image into a multi-page A4 poster PDF (pdfposter)."
    supported_extensions = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".pdf")
    needs_output_dir = True

    def __init__(self):
        super().__init__()
        self.on_change_callback = None

    def _bind_trace(self, var):
        var.trace_add("write", lambda *args: self._notify_change())
        return var

    def _notify_change(self):
        if callable(self.on_change_callback):
            self.on_change_callback()

    def execute(self, files, output_path, **kwargs):
        if not files:
            raise ValueError("No files provided.")
        if not find_pdfposter():
            raise RuntimeError("pdfposter not found. Install with: pip install pdfposter")

        out_dir = Path(output_path)
        if out_dir.suffix:
            out_dir = out_dir.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        try:
            cols = int(self.cols_var.get()) if hasattr(self, "cols_var") else 2
        except ValueError:
            cols = 2
        try:
            rows = int(self.rows_var.get()) if hasattr(self, "rows_var") else 2
        except ValueError:
            rows = 2
        cols = max(1, min(10, cols))
        rows = max(1, min(10, rows))

        done = 0
        with tempfile.TemporaryDirectory(prefix="a4_poster_") as tmp:
            tmp_dir = Path(tmp)
            for f_str in files:
                src = Path(f_str)
                if not src.is_file():
                    print(f"Skip missing: {src}")
                    continue
                one_pdf = tmp_dir / f"{src.stem}_one.pdf"
                out_pdf = out_dir / f"{src.stem}_poster.pdf"
                print(f"Posterizing {src.name} as {cols}x{rows} A4 ...")
                image_to_pdf(src, one_pdf)
                run_pdfposter(one_pdf, out_pdf, cols, rows, media="A4")
                pages = pdf_page_count(out_pdf)
                print(f"Wrote {out_pdf.name} ({pages} pages)")
                done += 1
        print(f"Done: {done} of {len(files)}")

    def render_options_ui(self, parent_frame, on_change_callback=None):
        self.on_change_callback = on_change_callback
        frame = ttk.Frame(parent_frame, padding=4)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="A4 cols").grid(row=0, column=0, sticky="w", pady=1)
        self.cols_var = self._bind_trace(tk.StringVar(value="2"))
        ttk.Spinbox(frame, from_=1, to=10, textvariable=self.cols_var, width=6).grid(
            row=0, column=1, sticky="w", pady=1
        )

        ttk.Label(frame, text="A4 rows").grid(row=1, column=0, sticky="w", pady=1)
        self.rows_var = self._bind_trace(tk.StringVar(value="2"))
        ttk.Spinbox(frame, from_=1, to=10, textvariable=self.rows_var, width=6).grid(
            row=1, column=1, sticky="w", pady=1
        )

        ttk.Label(frame, text="Output: {stem}_poster.pdf", wraplength=200).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        if not find_pdfposter():
            ttk.Label(frame, text="pdfposter not installed", foreground="#b91c1c").grid(
                row=3, column=0, columnspan=2, sticky="w"
            )
        return frame

    def get_output_path(self, output_dir, files):
        return output_dir


def _self_check() -> None:
    assert find_pdfposter(), "pdfposter must be on PATH"
    img = Image.new("RGB", (400, 600), (30, 90, 160))
    with tempfile.TemporaryDirectory(prefix="poster_self_") as tmp:
        tmp_dir = Path(tmp)
        src = tmp_dir / "src.png"
        img.save(src)
        one = tmp_dir / "one.pdf"
        out = tmp_dir / "out.pdf"
        image_to_pdf(src, one)
        assert one.is_file()
        cols, rows = 2, 2
        run_pdfposter(one, out, cols, rows)
        assert out.is_file()
        n = pdf_page_count(out)
        assert n == cols * rows, f"expected {cols * rows} pages, got {n}"

        plugin = ImagePosterPlugin()
        root = tk.Tk()
        root.withdraw()
        try:
            plugin.cols_var = tk.StringVar(value="2")
            plugin.rows_var = tk.StringVar(value="1")
            out_dir = tmp_dir / "batch"
            out_dir.mkdir()
            plugin.execute([str(src)], str(out_dir))
            posters = list(out_dir.glob("*_poster.pdf"))
            assert posters, "plugin did not write poster"
            assert pdf_page_count(posters[0]) == 2
        finally:
            root.destroy()
    print("images_to_poster self-check OK")


def cli_main():
    parser = argparse.ArgumentParser(description="A4 Poster (pdfposter)")
    parser.add_argument("-i", "--inputs", nargs="+", default=[])
    parser.add_argument("-o", "--output", default="")
    parser.add_argument("--cols", default="2")
    parser.add_argument("--rows", default="2")
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()

    if args.self_check:
        _self_check()
        return

    if not args.inputs:
        parser.error("the following arguments are required: -i/--inputs")

    plugin = ImagePosterPlugin()
    files = plugin.filter_inputs(plugin.collect_input_files(args.inputs))
    if not files:
        print("No matching files.")
        sys.exit(1)

    root = tk.Tk()
    root.withdraw()
    try:
        plugin.cols_var = tk.StringVar(value=args.cols)
        plugin.rows_var = tk.StringVar(value=args.rows)
        out = args.output.strip() or str(Path(files[0]).parent)
        plugin.execute(files, plugin.get_output_path(out, files))
    finally:
        root.destroy()


if __name__ == "__main__":
    plugin_entry(ImagePosterPlugin, cli_main)
