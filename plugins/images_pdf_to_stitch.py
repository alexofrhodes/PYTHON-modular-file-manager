import os
import sys
import io
from pathlib import Path
import tkinter as tk
from tkinter import ttk
from PIL import Image

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

try:
    from plugins import import_host
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from plugins import import_host

_host = import_host()
BaseFileOperation = _host.BaseFileOperation
plugin_entry = _host.plugin_entry


class DocumentAndImageStitcherPlugin(BaseFileOperation):
    name = "Image / PDF Stitcher"
    description = "Stitch images or PDF pages into Vertical, Horizontal, or Grid layouts."
    supported_extensions = (".png", ".jpg", ".jpeg", ".webp", ".pdf")
    needs_output_dir = True

    def __init__(self):
        super().__init__()
        self.on_change_callback = None

    def _bind_trace(self, var):
        """Attaches a write observer to notify the host application whenever options change."""
        var.trace_add("write", lambda *args: self._notify_change())
        return var

    def _notify_change(self):
        if callable(self.on_change_callback):
            self.on_change_callback()

    def load_file_as_images(self, file_path: Path, zoom: int = 2) -> list[Image.Image]:
        """Loads raw images or converts document pages into PIL RGB Images."""
        ext = file_path.suffix.lower()
        images = []

        # 1. Direct Image Files
        if ext in (".png", ".jpg", ".jpeg", ".webp"):
            try:
                img = Image.open(file_path).convert("RGB")
                images.append(img)
            except Exception as e:
                print(f"Error loading image {file_path.name}: {e}")

        # 2. PDF Documents via PyMuPDF
        elif ext == ".pdf":
            if not fitz:
                print("PyMuPDF (fitz) is required for PDF rendering.")
                return []
            try:
                doc = fitz.open(file_path)
                for page in doc:
                    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
                    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                    images.append(img)
                doc.close()
            except Exception as e:
                print(f"Error rendering PDF {file_path.name}: {e}")

        # 3. Placeholders for DOCX / PPTX (Extendable)
        elif ext in (".docx", ".pptx"):
            print(f"Notice: Direct visual stitching for {ext} requires explicit document rendering logic.")

        return images

    def execute(self, files, output_path, **kwargs):
        if not files:
            raise ValueError("No files provided for stitching.")

        # Read UI Options safely
        layout_mode = self.layout_var.get() if hasattr(self, "layout_var") else "Vertical"
        cols = int(self.cols_var.get()) if hasattr(self, "cols_var") and self.cols_var.get().isdigit() else 2
        rows = int(self.rows_var.get()) if hasattr(self, "rows_var") and self.rows_var.get().isdigit() else 2
        zoom_val = int(self.zoom_var.get()) if hasattr(self, "zoom_var") and self.zoom_var.get().isdigit() else 2
        quality_val = int(self.quality_var.get()) if hasattr(self, "quality_var") and self.quality_var.get().isdigit() else 85
        out_filename = self.output_name_var.get() if hasattr(self, "output_name_var") else "stitched_output.jpg"

        # Load all visual frames
        all_images = []
        for f_str in files:
            f_path = Path(f_str)
            if f_path.exists():
                print(f"Loading/Rendering: {f_path.name}")
                all_images.extend(self.load_file_as_images(f_path, zoom=zoom_val))

        if not all_images:
            raise RuntimeError("No valid images or renderable pages could be loaded.")

        widths = [img.width for img in all_images]
        heights = [img.height for img in all_images]
        max_w, max_h = max(widths), max(heights)

        # Build Canvas based on layout mode
        if layout_mode == "Horizontal":
            total_w = sum(widths)
            canvas = Image.new("RGB", (total_w, max_h), (255, 255, 255))
            x_offset = 0
            for img in all_images:
                y_offset = (max_h - img.height) // 2  # Vertical centering
                canvas.paste(img, (x_offset, y_offset))
                x_offset += img.width

        elif layout_mode == "Vertical":
            total_h = sum(heights)
            canvas = Image.new("RGB", (max_w, total_h), (255, 255, 255))
            y_offset = 0
            for img in all_images:
                x_offset = (max_w - img.width) // 2  # Horizontal centering
                canvas.paste(img, (x_offset, y_offset))
                y_offset += img.height

        elif layout_mode == "Grid (X by Y)":
            grid_w = cols * max_w
            grid_h = rows * max_h
            canvas = Image.new("RGB", (grid_w, grid_h), (255, 255, 255))
            for idx, img in enumerate(all_images[: cols * rows]):
                r = idx // cols
                c = idx % cols
                # Center inside cell grid box
                x_offset = (c * max_w) + ((max_w - img.width) // 2)
                y_offset = (r * max_h) + ((max_h - img.height) // 2)
                canvas.paste(img, (x_offset, y_offset))

        # Output Path Construction
        base_dir = Path(output_path if os.path.isdir(output_path) else os.path.dirname(output_path))
        base_dir.mkdir(parents=True, exist_ok=True)
        final_dest = base_dir / out_filename

        ext = final_dest.suffix.lower()
        if ext in (".jpg", ".jpeg"):
            canvas.save(final_dest, optimize=True, quality=quality_val)
        else:
            canvas.save(final_dest)

        print(f"Stitched file successfully saved to: {final_dest.resolve()}")

    def render_options_ui(self, parent_frame, on_change_callback=None):
        self.on_change_callback = on_change_callback
        frame = ttk.Frame(parent_frame, padding=4)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Layout").grid(row=0, column=0, sticky="w", pady=1)
        self.layout_var = self._bind_trace(tk.StringVar(value="Vertical"))
        ttk.Combobox(
            frame, textvariable=self.layout_var, values=["Vertical", "Horizontal", "Grid (X by Y)"],
            state="readonly", width=14,
        ).grid(row=0, column=1, sticky="w", pady=1)

        ttk.Label(frame, text="Filename").grid(row=1, column=0, sticky="w", pady=1)
        self.output_name_var = self._bind_trace(tk.StringVar(value="stitched_output.jpg"))
        ttk.Entry(frame, textvariable=self.output_name_var, width=16).grid(row=1, column=1, sticky="ew", pady=1)

        grid = ttk.Frame(frame)
        grid.grid(row=2, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(grid, text="Cols").pack(side=tk.LEFT)
        self.cols_var = self._bind_trace(tk.StringVar(value="2"))
        ttk.Entry(grid, textvariable=self.cols_var, width=4).pack(side=tk.LEFT, padx=(2, 8))
        ttk.Label(grid, text="Rows").pack(side=tk.LEFT)
        self.rows_var = self._bind_trace(tk.StringVar(value="2"))
        ttk.Entry(grid, textvariable=self.rows_var, width=4).pack(side=tk.LEFT, padx=2)

        qual = ttk.Frame(frame)
        qual.grid(row=3, column=0, columnspan=2, sticky="w", pady=2)
        ttk.Label(qual, text="Scale").pack(side=tk.LEFT)
        self.zoom_var = self._bind_trace(tk.StringVar(value="2"))
        ttk.Combobox(qual, textvariable=self.zoom_var, values=["1", "2", "3"], state="readonly", width=4).pack(
            side=tk.LEFT, padx=(2, 8)
        )
        ttk.Label(qual, text="JPEG").pack(side=tk.LEFT)
        self.quality_var = self._bind_trace(tk.StringVar(value="85"))
        ttk.Combobox(
            qual, textvariable=self.quality_var, values=["60", "80", "85", "95", "100"], state="readonly", width=4
        ).pack(side=tk.LEFT, padx=2)

        return frame

    def get_output_path(self, output_dir, files):
        out_filename = self.output_name_var.get() if hasattr(self, "output_name_var") else "stitched_output.jpg"
        return str(Path(output_dir) / out_filename)


def cli_main():
    import argparse

    parser = argparse.ArgumentParser(description="Stitch images / PDF pages")
    parser.add_argument("-i", "--inputs", nargs="+", required=True)
    parser.add_argument("-o", "--output", default="")
    parser.add_argument("--layout", choices=["Vertical", "Horizontal", "Grid (X by Y)"], default="Vertical")
    parser.add_argument("--cols", default="2")
    parser.add_argument("--rows", default="2")
    args = parser.parse_args()

    plugin = DocumentAndImageStitcherPlugin()
    files = plugin.filter_inputs(plugin.collect_input_files(args.inputs))
    if not files:
        print("No matching files found.")
        sys.exit(1)

    plugin.layout_var = tk.StringVar(value=args.layout)
    plugin.cols_var = tk.StringVar(value=args.cols)
    plugin.rows_var = tk.StringVar(value=args.rows)
    plugin.zoom_var = tk.StringVar(value="2")
    plugin.quality_var = tk.StringVar(value="85")
    plugin.output_name_var = tk.StringVar(value="stitched_output.jpg")

    if args.output.strip():
        out = args.output.strip()
        if Path(out).suffix:
            plugin.output_name_var.set(Path(out).name)
            out_dir = str(Path(out).parent) if str(Path(out).parent) not in (".", "") else str(Path(files[0]).parent)
        else:
            out_dir = out
    else:
        out_dir = str(Path(files[0]).parent)

    plugin.execute(files, plugin.get_output_path(out_dir, files))


if __name__ == "__main__":
    plugin_entry(DocumentAndImageStitcherPlugin, cli_main)