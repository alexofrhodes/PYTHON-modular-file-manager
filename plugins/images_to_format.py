from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog

from PIL import Image

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:  # pragma: no cover
    Observer = None
    FileSystemEventHandler = object

try:
    from plugins import import_host
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from plugins import import_host

_host = import_host()
BaseFileOperation = _host.BaseFileOperation
plugin_entry = _host.plugin_entry

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
OUT_FORMATS = ("jpg", "png", "webp", "bmp", "tif")


def normalize_fmt(fmt: str) -> str:
    fmt = (fmt or "jpg").lower().strip()
    if fmt == "jpeg":
        return "jpg"
    return fmt


def pillow_format(fmt: str) -> str:
    fmt = normalize_fmt(fmt)
    return "JPEG" if fmt == "jpg" else fmt.upper()


def output_suffix(fmt: str) -> str:
    return ".jpg" if normalize_fmt(fmt) == "jpg" else f".{normalize_fmt(fmt)}"


def convert_one(path: str | Path, fmt: str, overwrite: bool, delete: bool) -> str:
    """Convert a single image beside the source. Returns a short status line."""
    path = Path(path)
    if path.suffix.lower() not in IMAGE_EXTS:
        return f"[SKIP] not an image: {path.name}"

    fmt = normalize_fmt(fmt)
    out = path.with_suffix(output_suffix(fmt))
    name = path.stem

    if out.exists() and not overwrite:
        return f"[SKIP] {name}"

    try:
        img = Image.open(path)
        if img.mode in ("RGBA", "P") and fmt == "jpg":
            img = img.convert("RGB")
        elif img.mode == "P":
            img = img.convert("RGBA")

        save_kw = {}
        if fmt == "jpg":
            save_kw["quality"] = 95
        img.save(out, pillow_format(fmt), **save_kw)
        msg = f"[OK] {name} -> {out.name}"

        if delete and out.resolve() != path.resolve():
            try:
                path.unlink()
                msg += f" [DEL] {path.name}"
            except OSError as e:
                msg += f" [DEL fail] {e}"
        return msg
    except Exception as e:
        return f"[ERROR] {path} -> {e}"


class _ConvertHandler(FileSystemEventHandler):
    def __init__(self, fmt: str, overwrite: bool, delete: bool, log):
        super().__init__()
        self.fmt = fmt
        self.overwrite = overwrite
        self.delete = delete
        self.log = log

    def on_created(self, event):
        if event.is_directory:
            return
        time.sleep(0.2)
        src = event.src_path
        if Path(src).suffix.lower() not in IMAGE_EXTS:
            return
        self.log(convert_one(src, self.fmt, self.overwrite, self.delete))


class ImageFormatConverterPlugin(BaseFileOperation):
    name = "Image Format Converter"
    description = "Convert images to another format (beside source); optional folder watch."
    supported_extensions = tuple(sorted(IMAGE_EXTS))
    needs_output_dir = False

    def __init__(self):
        super().__init__()
        self._observers: list = []

    def _settings(self) -> tuple[str, bool, bool]:
        fmt = normalize_fmt(getattr(self, "format_var", tk.StringVar(value="jpg")).get())
        overwrite = bool(getattr(self, "overwrite_var", tk.BooleanVar(value=False)).get())
        delete = bool(getattr(self, "delete_var", tk.BooleanVar(value=False)).get())
        return fmt, overwrite, delete

    def _watch_folder_list(self) -> list[str]:
        raw = getattr(self, "watch_folders_var", tk.StringVar(value="")).get()
        return [p.strip() for p in raw.replace("\r\n", "\n").split("\n") if p.strip()]

    def _set_watch_folders(self, folders: list[str]) -> None:
        if not hasattr(self, "watch_folders_var"):
            self.watch_folders_var = tk.StringVar(value="")
        self.watch_folders_var.set("\n".join(folders))
        if hasattr(self, "_watch_listbox") and self._watch_listbox.winfo_exists():
            self._watch_listbox.delete(0, tk.END)
            for f in folders:
                self._watch_listbox.insert(tk.END, f)

    def start_watch(self, folders: list[str] | None = None, *, log=print) -> int:
        if Observer is None:
            raise RuntimeError("watchdog is not installed. pip install watchdog")

        self.stop_watch()
        fmt, overwrite, delete = self._settings()
        folders = folders if folders is not None else self._watch_folder_list()
        started = 0
        for folder in folders:
            resolved = str(Path(folder).resolve())
            if not os.path.isdir(resolved):
                log(f"[WARN] Directory not found: {folder}")
                continue
            obs = Observer()
            handler = _ConvertHandler(fmt, overwrite, delete, log)
            obs.schedule(handler, resolved, recursive=True)
            obs.start()
            self._observers.append(obs)
            log(f"[WATCHING] {resolved}")
            started += 1
        if started:
            log("[WATCH STARTED]")
        return started

    def stop_watch(self, *, log=print) -> None:
        if not self._observers:
            return
        for obs in self._observers:
            try:
                obs.stop()
            except Exception:
                pass
        for obs in self._observers:
            try:
                obs.join(timeout=2)
            except Exception:
                pass
        self._observers = []
        log("[WATCH STOPPED]")

    def execute(self, files, output_path, **kwargs):
        if not files:
            raise ValueError("No image files provided.")
        fmt, overwrite, delete = self._settings()
        for f in files:
            print(convert_one(f, fmt, overwrite, delete))
        print("Image conversion batch finished.")

    def render_options_ui(self, parent_frame, on_change_callback=None):
        frame = ttk.Frame(parent_frame, padding=4)
        frame.columnconfigure(0, weight=1)

        self.format_var = tk.StringVar(value="jpg")
        self.overwrite_var = tk.BooleanVar(value=False)
        self.delete_var = tk.BooleanVar(value=False)
        self.watch_folders_var = tk.StringVar(value="")

        ttk.Label(frame, text="Output format").pack(anchor=tk.W)
        ttk.Combobox(
            frame,
            textvariable=self.format_var,
            values=list(OUT_FORMATS),
            state="readonly",
            width=12,
        ).pack(fill=tk.X, pady=2)

        ttk.Checkbutton(frame, text="Overwrite", variable=self.overwrite_var).pack(anchor=tk.W)
        ttk.Checkbutton(frame, text="Delete original", variable=self.delete_var).pack(anchor=tk.W)

        ttk.Separator(frame, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=6)
        ttk.Label(frame, text="WATCH FOLDERS", style="SidebarSection.TLabel").pack(anchor=tk.W)

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=2)
        self._watch_listbox = tk.Listbox(list_frame, height=4, exportselection=0, font=("Segoe UI", 8))
        self._watch_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self._watch_listbox.yview)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self._watch_listbox.configure(yscrollcommand=sb.set)

        for p in self._watch_folder_list():
            self._watch_listbox.insert(tk.END, p)

        def _sync_var_from_list():
            folders = list(self._watch_listbox.get(0, tk.END))
            self.watch_folders_var.set("\n".join(folders))

        def _add_folder():
            path = filedialog.askdirectory(title="Folder to watch")
            if not path:
                return
            path = str(Path(path).resolve())
            existing = list(self._watch_listbox.get(0, tk.END))
            if path not in existing:
                self._watch_listbox.insert(tk.END, path)
                _sync_var_from_list()

        def _remove_selected():
            sel = list(self._watch_listbox.curselection())
            for i in reversed(sel):
                self._watch_listbox.delete(i)
            _sync_var_from_list()

        def _start():
            try:
                _sync_var_from_list()
                n = self.start_watch(log=print)
                if n == 0:
                    print("[WARN] No valid watch folders.")
            except Exception as e:
                print(f"[ERROR] Watch: {e}")

        def _stop():
            self.stop_watch(log=print)

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X, pady=2)
        ttk.Button(btn_row, text="Add", style="Toolbar.TButton", command=_add_folder).pack(
            side=tk.LEFT, padx=(0, 3)
        )
        ttk.Button(btn_row, text="Remove", style="Toolbar.TButton", command=_remove_selected).pack(
            side=tk.LEFT, padx=(0, 3)
        )

        watch_row = ttk.Frame(frame)
        watch_row.pack(fill=tk.X, pady=2)
        ttk.Button(watch_row, text="Start watch", style="Accent.TButton", command=_start).pack(
            side=tk.LEFT, padx=(0, 3)
        )
        ttk.Button(watch_row, text="Stop watch", style="Toolbar.TButton", command=_stop).pack(
            side=tk.LEFT
        )

        ttk.Label(
            frame,
            text="Writes beside each file.\nWatch: recursive on_created.",
            style="SidebarMuted.TLabel",
            wraplength=220,
        ).pack(anchor=tk.W, pady=(4, 0))

        # Restore listbox if watch_folders_var was set before UI (session apply)
        def _on_folders_var(*_a):
            want = self._watch_folder_list()
            have = list(self._watch_listbox.get(0, tk.END))
            if want != have:
                self._watch_listbox.delete(0, tk.END)
                for f in want:
                    self._watch_listbox.insert(tk.END, f)

        self.watch_folders_var.trace_add("write", _on_folders_var)
        return frame

    def get_output_path(self, output_dir, files):
        return output_dir


def cli_main():
    parser = argparse.ArgumentParser(description="Convert images to another format; optional folder watch")
    parser.add_argument("-i", "--inputs", nargs="+", default=[], help="Files/folders/globs to convert")
    parser.add_argument("--format", choices=list(OUT_FORMATS), default="jpg")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--delete", action="store_true", help="Delete originals after convert")
    parser.add_argument(
        "--watch",
        nargs="+",
        metavar="DIR",
        default=[],
        help="Watch folder(s); blocks until Ctrl+C",
    )
    args = parser.parse_args()

    if not args.inputs and not args.watch:
        parser.error("Provide -i/--inputs and/or --watch DIR")

    plugin = ImageFormatConverterPlugin()
    plugin.format_var = tk.StringVar(value=args.format)
    plugin.overwrite_var = tk.BooleanVar(value=args.overwrite)
    plugin.delete_var = tk.BooleanVar(value=args.delete)
    plugin.watch_folders_var = tk.StringVar(value="\n".join(str(Path(p).resolve()) for p in args.watch))

    if args.inputs:
        files = plugin.filter_inputs(plugin.collect_input_files(args.inputs))
        if not files:
            print("No matching image files for -i.")
            if not args.watch:
                sys.exit(1)
        else:
            out = str(Path(files[0]).parent)
            plugin.execute(files, out)

    if args.watch:
        if Observer is None:
            print("watchdog is not installed. pip install watchdog")
            sys.exit(1)
        folders = [str(Path(p).resolve()) for p in args.watch]
        plugin.start_watch(folders, log=print)
        print("Watching… Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("")
        finally:
            plugin.stop_watch(log=print)


if __name__ == "__main__":
    plugin_entry(ImageFormatConverterPlugin, cli_main)
