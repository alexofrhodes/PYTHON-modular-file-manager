from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import tkinter as tk
from tkinter import ttk

try:
    from plugins import import_host
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from plugins import import_host

_host = import_host()
BaseFileOperation = _host.BaseFileOperation
plugin_entry = _host.plugin_entry

PROJECT_ROOT = Path(__file__).resolve().parent.parent

GS_SETTINGS_MAP = {
    "high": "/printer",
    "medium": "/ebook",
    "low": "/screen",
}
GS_DPI_MAP = {
    "high": 150,
    "medium": 110,
    "low": 72,
}
GS_QFACTOR_MAP = {
    "high": 0.5,
    "medium": 1.2,
    "low": 2.4,
}

MODE_PRESETS = {
    "low": {"quality": "low", "resize": "yes", "compress": "yes"},
    "mid": {"quality": "medium", "resize": "yes", "compress": "yes"},
    "high": {"quality": "high", "resize": "no", "compress": "yes"},
    "max": {"quality": "low", "resize": "yes", "compress": "yes"},
}


@dataclass
class CompressSettings:
    mode: str = "mid"
    quality: str = "medium"
    resize: str = "yes"
    compress: str = "yes"
    gray: bool = False
    nosuffix: bool = False


def apply_mode_presets(settings: CompressSettings) -> CompressSettings:
    preset = MODE_PRESETS.get(settings.mode or "")
    if preset:
        settings.quality = preset["quality"]
        settings.resize = preset["resize"]
        settings.compress = preset["compress"]
    return settings


def find_ghostscript() -> Optional[str]:
    """Prefer tools/GhostScript under project root, then legacy next-to-app, then PATH."""
    exe_names = (
        "gswin64c.exe",
        "gswin32c.exe",
        "gs.exe",
        "gswin64c",
        "gswin32c",
        "gs",
    )

    def _look_in(folder: Path) -> Optional[str]:
        if not folder.is_dir():
            return None
        for name in exe_names:
            candidate = folder / name
            if candidate.is_file():
                return str(candidate)
        return None

    portable_roots = [
        PROJECT_ROOT / "tools" / "GhostScript",
        PROJECT_ROOT / "tools" / "Ghostscript",
        PROJECT_ROOT / "tools" / "ghostscript",
        PROJECT_ROOT / "GhostScript",
        PROJECT_ROOT / "Ghostscript",
        PROJECT_ROOT / "ghostscript",
    ]

    for root in portable_roots:
        found = _look_in(root / "bin") or _look_in(root)
        if found:
            return found

    for name in ("gswin64c", "gswin32c", "gs"):
        path = shutil.which(name)
        if path:
            return path
    return None


def _run_hidden(cmd: list[str]) -> subprocess.CompletedProcess:
    kwargs: dict = {
        "capture_output": True,
        "text": True,
        "check": False,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def pdf_page_count(path: str) -> int:
    try:
        with open(path, "rb") as f:
            data = f.read()
        return len(re.findall(rb"/Type\s*/Page(?!\s*s)", data))
    except OSError:
        return 0


def compress_pdf_ghostscript(
    input_pdf: str,
    output_pdf: str,
    settings: CompressSettings,
    *,
    aggressive: bool = False,
) -> tuple[int, str]:
    gs = find_ghostscript()
    if not gs:
        raise FileNotFoundError(
            "Ghostscript not found. Place portable tools/GhostScript/bin next to the project, "
            "or install Ghostscript on PATH."
        )

    preset = GS_SETTINGS_MAP.get(settings.quality, "/screen")
    dpi = GS_DPI_MAP.get(settings.quality, 72)
    qfactor = GS_QFACTOR_MAP.get(settings.quality, 2.4)
    if settings.mode == "max" or aggressive:
        dpi = min(dpi, 72)
        qfactor = max(qfactor, 2.4)
        aggressive = True

    page_count = pdf_page_count(input_pdf)

    if settings.compress == "no":
        shutil.copy2(input_pdf, output_pdf)
        return page_count, "copy (compress=no)"

    cmd = [
        gs,
        "-sDEVICE=pdfwrite",
        "-dCompatibilityLevel=1.4",
        f"-dPDFSETTINGS={preset}",
        "-dNOPAUSE",
        "-dBATCH",
        "-dQUIET",
        "-dDetectDuplicateImages=true",
        "-dCompressFonts=true",
        "-dSubsetFonts=true",
    ]

    if settings.gray:
        cmd.extend(
            [
                "-sColorConversionStrategy=Gray",
                "-dProcessColorModel=/DeviceGray",
            ]
        )

    use_down = aggressive or settings.resize == "yes"
    threshold = 1.0 if (aggressive or settings.quality == "low") else 1.5

    if use_down:
        cmd.extend(
            [
                "-dDownsampleColorImages=true",
                "-dDownsampleGrayImages=true",
                "-dDownsampleMonoImages=true",
                "-dColorImageDownsampleType=/Bicubic",
                "-dGrayImageDownsampleType=/Bicubic",
                "-dMonoImageDownsampleType=/Bicubic",
                f"-dColorImageResolution={dpi}",
                f"-dGrayImageResolution={dpi}",
                f"-dMonoImageResolution={dpi}",
                f"-dColorImageDownsampleThreshold={threshold}",
                f"-dGrayImageDownsampleThreshold={threshold}",
                f"-dMonoImageDownsampleThreshold={threshold}",
                "-dEncodeColorImages=true",
                "-dEncodeGrayImages=true",
                "-dEncodeMonoImages=true",
                "-dAutoFilterColorImages=false",
                "-dAutoFilterGrayImages=false",
                "-dColorImageFilter=/DCTEncode",
                "-dGrayImageFilter=/DCTEncode",
            ]
        )

    cmd.append(f"-sOutputFile={output_pdf}")

    distiller = (
        f"<</ColorACSImageDict<</QFactor {qfactor} /Blend 1 "
        f"/HSamples [2 1 1 2] /VSamples [2 1 1 2]>> "
        f"/ColorImageDict<</QFactor {qfactor} /Blend 1 "
        f"/HSamples [2 1 1 2] /VSamples [2 1 1 2]>> "
        f"/GrayACSImageDict<</QFactor {qfactor} /Blend 1 "
        f"/HSamples [2 1 1 2] /VSamples [2 1 1 2]>> "
        f"/GrayImageDict<</QFactor {qfactor} /Blend 1 "
        f"/HSamples [2 1 1 2] /VSamples [2 1 1 2]>> "
        f"/DownsampleColorImages {'true' if use_down else 'false'} "
        f"/DownsampleGrayImages {'true' if use_down else 'false'} "
        f"/ColorImageResolution {dpi} /GrayImageResolution {dpi} "
        f"/ColorImageDownsampleThreshold {threshold} "
        f"/GrayImageDownsampleThreshold {threshold}>> setdistillerparams"
    )
    cmd.extend(["-c", distiller, "-f", input_pdf])

    result = _run_hidden(cmd)
    if result.returncode != 0 or not os.path.isfile(output_pdf):
        err = (result.stderr or result.stdout or "").strip() or f"exit {result.returncode}"
        raise RuntimeError(err)
    label = f"{preset} @{dpi}dpi" + (" aggressive" if aggressive else "")
    return page_count, label


class PdfCompressorPlugin(BaseFileOperation):
    name = "PDF Compressor"
    description = "Shrink PDFs with Ghostscript (tools/GhostScript or PATH)."
    supported_extensions = (".pdf",)
    needs_output_dir = True

    def __init__(self):
        super().__init__()
        self.ghostscript_exe = find_ghostscript()

    def _settings_from_ui(self) -> CompressSettings:
        mode = getattr(self, "mode_var", tk.StringVar(value="mid")).get()
        settings = CompressSettings(
            mode=mode,
            quality=getattr(self, "quality_var", tk.StringVar(value="medium")).get(),
            resize=getattr(self, "resize_var", tk.StringVar(value="yes")).get(),
            compress=getattr(self, "compress_var", tk.StringVar(value="yes")).get(),
            gray=bool(getattr(self, "gray_var", tk.BooleanVar(value=False)).get()),
            nosuffix=bool(getattr(self, "nosuffix_var", tk.BooleanVar(value=False)).get()),
        )
        # Mode presets already applied in UI when mode changes; keep explicit combo values.
        return settings

    def _output_path_for(self, input_pdf: Path, out_dir: Path, nosuffix: bool) -> Path:
        name = f"{input_pdf.stem}.pdf" if nosuffix else f"{input_pdf.stem}_compressed.pdf"
        return out_dir / name

    def execute(self, files, output_path, **kwargs):
        if not files:
            raise ValueError("No PDF files provided.")

        gs = self.ghostscript_exe or find_ghostscript()
        if not gs:
            raise FileNotFoundError(
                "Ghostscript not found. Place portable tools/GhostScript/bin under the project, "
                "or install Ghostscript on PATH."
            )

        settings = self._settings_from_ui()
        out_dir = Path(output_path)
        if out_dir.suffix.lower() == ".pdf":
            out_dir = out_dir.parent
        out_dir.mkdir(parents=True, exist_ok=True)

        ok = 0
        for file_path_str in files:
            input_pdf = Path(file_path_str)
            if not input_pdf.is_file():
                print(f"Skip missing: {input_pdf}")
                continue

            dest = self._output_path_for(input_pdf, out_dir, settings.nosuffix)
            print(f"\nCompressing: {input_pdf}")
            print(f" -> Output: {dest}")

            temp_path = None
            write_path = dest
            try:
                same = input_pdf.resolve() == dest.resolve()
                if same:
                    temp_path = Path(str(dest) + ".tmp.pdf")
                    write_path = temp_path

                pages, label = compress_pdf_ghostscript(
                    str(input_pdf),
                    str(write_path),
                    settings,
                    aggressive=settings.mode == "max",
                )
                print(f"Engine: Ghostscript {label}")

                if temp_path is not None:
                    os.replace(temp_path, dest)

                in_size = input_pdf.stat().st_size
                out_size = dest.stat().st_size
                ratio = (1 - out_size / in_size) * 100 if in_size else 0
                print(
                    f"OK Done ({pages} pages, {in_size / 1024:.0f} KB -> "
                    f"{out_size / 1024:.0f} KB, {ratio:.0f}% smaller)"
                )
                ok += 1
            except Exception as e:
                if temp_path is not None and temp_path.is_file():
                    try:
                        temp_path.unlink()
                    except OSError:
                        pass
                print(f"Error: {e}")

        print(f"\nFinished: {ok}/{len(files)} ok")

    def _on_mode_change(self, *_args):
        mode = self.mode_var.get()
        preset = MODE_PRESETS.get(mode)
        if not preset:
            return
        self.quality_var.set(preset["quality"])
        self.resize_var.set(preset["resize"])
        self.compress_var.set(preset["compress"])

    def render_options_ui(self, parent_frame, on_change_callback=None):
        frame = ttk.Frame(parent_frame, padding=4)
        frame.columnconfigure(1, weight=1)

        if not self.ghostscript_exe:
            ttk.Label(
                frame,
                text="Ghostscript not found.\nExpected: tools/GhostScript/bin\nor gs on PATH.",
                wraplength=220,
            ).pack(anchor=tk.W)
            self.mode_var = tk.StringVar(value="mid")
            self.quality_var = tk.StringVar(value="medium")
            self.resize_var = tk.StringVar(value="yes")
            self.compress_var = tk.StringVar(value="yes")
            self.gray_var = tk.BooleanVar(value=False)
            self.nosuffix_var = tk.BooleanVar(value=False)
            return frame

        self.mode_var = tk.StringVar(value="mid")
        self.quality_var = tk.StringVar(value="medium")
        self.resize_var = tk.StringVar(value="yes")
        self.compress_var = tk.StringVar(value="yes")

        ttk.Label(frame, text="Mode").grid(row=0, column=0, sticky="w", pady=1)
        mode_cb = ttk.Combobox(
            frame,
            textvariable=self.mode_var,
            values=["high", "mid", "low", "max"],
            state="readonly",
            width=12,
        )
        mode_cb.grid(row=0, column=1, sticky="ew", pady=1)
        mode_cb.bind("<<ComboboxSelected>>", lambda _e: self._on_mode_change())
        self.mode_var.trace_add("write", self._on_mode_change)

        ttk.Label(
            frame,
            text="high=look · mid=balanced\nlow=smaller · max=strongest",
            style="SidebarMuted.TLabel",
            wraplength=220,
        ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(0, 4))

        ttk.Label(frame, text="Quality").grid(row=2, column=0, sticky="w", pady=1)
        ttk.Combobox(
            frame,
            textvariable=self.quality_var,
            values=["high", "medium", "low"],
            state="readonly",
            width=12,
        ).grid(row=2, column=1, sticky="ew", pady=1)

        ttk.Label(frame, text="Resize").grid(row=3, column=0, sticky="w", pady=1)
        ttk.Combobox(
            frame,
            textvariable=self.resize_var,
            values=["yes", "no"],
            state="readonly",
            width=12,
        ).grid(row=3, column=1, sticky="ew", pady=1)

        ttk.Label(frame, text="Compress").grid(row=4, column=0, sticky="w", pady=1)
        ttk.Combobox(
            frame,
            textvariable=self.compress_var,
            values=["yes", "no"],
            state="readonly",
            width=12,
        ).grid(row=4, column=1, sticky="ew", pady=1)

        self.gray_var = tk.BooleanVar(value=False)
        self.nosuffix_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Grayscale", variable=self.gray_var).grid(
            row=5, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        ttk.Checkbutton(frame, text="No _compressed suffix", variable=self.nosuffix_var).grid(
            row=6, column=0, columnspan=2, sticky="w"
        )
        ttk.Label(
            frame,
            text="Writes name_compressed.pdf\ninto the OUTPUT folder",
            style="SidebarMuted.TLabel",
            wraplength=220,
        ).grid(row=7, column=0, columnspan=2, sticky="w", pady=(4, 0))

        self._on_mode_change()
        return frame

    def get_output_path(self, output_dir, files):
        return output_dir


def cli_main():
    parser = argparse.ArgumentParser(description="Compress PDF files with Ghostscript")
    parser.add_argument("-i", "--inputs", nargs="+", required=True)
    parser.add_argument("-o", "--output", default="", help="Output dir (default: beside first input)")
    parser.add_argument("--mode", choices=["low", "mid", "high", "max"], default="mid")
    parser.add_argument("--quality", choices=["high", "medium", "low"], default=None)
    parser.add_argument("--resize", choices=["yes", "no"], default=None)
    parser.add_argument("--compress", choices=["yes", "no"], default=None)
    parser.add_argument("--gray", action="store_true")
    parser.add_argument("--nosuffix", action="store_true")
    args = parser.parse_args()

    plugin = PdfCompressorPlugin()
    if not plugin.ghostscript_exe:
        print(
            "Ghostscript not found. Place portable tools/GhostScript/bin under the project, "
            "or install Ghostscript on PATH."
        )
        sys.exit(1)

    files = plugin.filter_inputs(plugin.collect_input_files(args.inputs))
    if not files:
        print("No matching PDF files.")
        sys.exit(1)

    settings = CompressSettings(mode=args.mode)
    apply_mode_presets(settings)
    if args.quality is not None:
        settings.quality = args.quality
    if args.resize is not None:
        settings.resize = args.resize
    if args.compress is not None:
        settings.compress = args.compress
    settings.gray = bool(args.gray)
    settings.nosuffix = bool(args.nosuffix)

    plugin.mode_var = tk.StringVar(value=settings.mode)
    plugin.quality_var = tk.StringVar(value=settings.quality)
    plugin.resize_var = tk.StringVar(value=settings.resize)
    plugin.compress_var = tk.StringVar(value=settings.compress)
    plugin.gray_var = tk.BooleanVar(value=settings.gray)
    plugin.nosuffix_var = tk.BooleanVar(value=settings.nosuffix)

    out = args.output.strip() or str(Path(files[0]).parent)
    plugin.execute(files, out)


if __name__ == "__main__":
    plugin_entry(PdfCompressorPlugin, cli_main)
