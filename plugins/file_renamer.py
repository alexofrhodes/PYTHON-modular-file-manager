import datetime
import re
import sys
from pathlib import Path
import tkinter as tk
from tkinter import ttk

try:
    from app import BaseFileOperation, plugin_entry
except ImportError:
    sys.path.append(str(Path(__file__).resolve().parent.parent))
    from app import BaseFileOperation, plugin_entry


class FileRenamerPlugin(BaseFileOperation):
    name = "Batch File Renamer"
    description = "Batch renames files with prefix/suffix, replace/regex, casing, counters, trimming, sanitization, and date stamps."
    supported_extensions = ()  # Accepts all files
    needs_output_dir = False

    def __init__(self):
        super().__init__()
        self.on_change_callback = None

    # --- Custom Column Plugin API ---
    def get_extra_columns(self) -> list[str]:
        """Registers 'New Name' as an additional column in the main file list."""
        return ["New Name"]

    def get_extra_row_data(self, file_path: Path, index: int) -> dict[str, str]:
        """Provides the computed target name side-by-side with the original file entry."""
        return {"New Name": self.compute_new_name(file_path, index)}

    # --- Calculation Logic ---
    def compute_new_name(self, file_path: Path, index: int) -> str:
        """Applies configured renaming rules to a file stem while keeping its original extension untouched."""
        stem = file_path.stem
        ext = file_path.suffix

        # 1. Trim Characters
        trim_start = int(self.trim_start_var.get()) if hasattr(self, "trim_start_var") and self.trim_start_var.get().isdigit() else 0
        trim_end = int(self.trim_end_var.get()) if hasattr(self, "trim_end_var") and self.trim_end_var.get().isdigit() else 0

        if trim_start > 0 and trim_start < len(stem):
            stem = stem[trim_start:]
        if trim_end > 0 and trim_end < len(stem):
            stem = stem[:-trim_end]

        # 2. Find & Replace / Regex
        use_regex = self.use_regex_var.get() if hasattr(self, "use_regex_var") else False
        find_str = self.find_var.get() if hasattr(self, "find_var") else ""
        replace_str = self.replace_var.get() if hasattr(self, "replace_var") else ""

        if find_str:
            if use_regex:
                try:
                    stem = re.sub(find_str, replace_str, stem)
                except re.error:
                    return "[Invalid Regex]"
            else:
                stem = stem.replace(find_str, replace_str)

        # 3. Case Transformation
        case_mode = self.case_var.get() if hasattr(self, "case_var") else "No Change"
        if case_mode == "lowercase":
            stem = stem.lower()
        elif case_mode == "UPPERCASE":
            stem = stem.upper()
        elif case_mode == "Title Case":
            stem = stem.title()

        # 4. Space & Special Character Sanitization
        space_mode = self.space_mode_var.get() if hasattr(self, "space_mode_var") else "Keep Spaces"
        if space_mode == "Replace with _":
            stem = stem.replace(" ", "_")
        elif space_mode == "Replace with -":
            stem = stem.replace(" ", "-")
        elif space_mode == "Remove Spaces":
            stem = stem.replace(" ", "")

        if self.clean_special_var.get() if hasattr(self, "clean_special_var") else False:
            stem = re.sub(r"[^\w\s-]", "", stem).strip()

        # 5. Date Stamp Insertion
        date_mode = self.date_mode_var.get() if hasattr(self, "date_mode_var") else "None"
        if date_mode != "None":
            if date_mode == "File Modified Date" and file_path.exists():
                mtime = file_path.stat().st_mtime
                date_str = datetime.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d")
            else:
                date_str = datetime.datetime.now().strftime("%Y-%m-%d")

            date_pos = self.date_pos_var.get() if hasattr(self, "date_pos_var") else "Prefix"
            if date_pos == "Prefix":
                stem = f"{date_str}_{stem}"
            else:
                stem = f"{stem}_{date_str}"

        # 6. Manual Prefix & Suffix
        prefix = self.prefix_var.get() if hasattr(self, "prefix_var") else ""
        suffix = self.suffix_var.get() if hasattr(self, "suffix_var") else ""
        stem = f"{prefix}{stem}{suffix}"

        # 7. Sequential Numbering Counter
        add_num = self.add_num_var.get() if hasattr(self, "add_num_var") else False
        if add_num:
            start_num = int(self.num_start_var.get()) if hasattr(self, "num_start_var") and self.num_start_var.get().isdigit() else 1
            padding = int(self.num_pad_var.get()) if hasattr(self, "num_pad_var") and self.num_pad_var.get().isdigit() else 3
            num_str = str(start_num + index).zfill(padding)

            num_pos = self.num_pos_var.get() if hasattr(self, "num_pos_var") else "Suffix"
            if num_pos == "Prefix":
                stem = f"{num_str}_{stem}"
            else:
                stem = f"{stem}_{num_str}"

        return f"{stem}{ext}"

    def execute(self, files, output_path, **kwargs):
        if not files:
            raise ValueError("No files provided for renaming.")

        renamed_count = 0
        for idx, f_str in enumerate(files):
            f_path = Path(f_str)
            if not f_path.exists():
                continue

            new_name = self.compute_new_name(f_path, idx)
            if new_name == "[Invalid Regex]":
                raise ValueError("Cannot perform rename with an invalid Regex pattern.")

            target_path = f_path.parent / new_name

            if target_path.exists() and target_path != f_path:
                print(f"Skipped (target exists): '{f_path.name}' -> '{new_name}'")
                continue

            if f_path != target_path:
                f_path.rename(target_path)
                print(f"Renamed: '{f_path.name}' -> '{new_name}'")
                renamed_count += 1

        print(f"Successfully renamed {renamed_count} of {len(files)} files.")

    def _bind_trace(self, var):
        """Attaches a write observer to notify the host application whenever options change."""
        var.trace_add("write", lambda *args: self._notify_change())
        return var

    def _notify_change(self):
        if callable(self.on_change_callback):
            self.on_change_callback()

    def render_options_ui(self, parent_frame, on_change_callback=None):
        self.on_change_callback = on_change_callback

        frame = ttk.Frame(parent_frame, padding=4)
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text="Trim").grid(row=0, column=0, sticky="w", pady=1)
        trim = ttk.Frame(frame)
        trim.grid(row=0, column=1, sticky="w")
        self.trim_start_var = self._bind_trace(tk.StringVar(value="0"))
        ttk.Entry(trim, textvariable=self.trim_start_var, width=3).pack(side=tk.LEFT)
        ttk.Label(trim, text="+").pack(side=tk.LEFT, padx=2)
        self.trim_end_var = self._bind_trace(tk.StringVar(value="0"))
        ttk.Entry(trim, textvariable=self.trim_end_var, width=3).pack(side=tk.LEFT)

        ttk.Label(frame, text="Find").grid(row=1, column=0, sticky="w", pady=1)
        self.find_var = self._bind_trace(tk.StringVar(value=""))
        ttk.Entry(frame, textvariable=self.find_var).grid(row=1, column=1, sticky="ew", pady=1)
        ttk.Label(frame, text="Replace").grid(row=2, column=0, sticky="w", pady=1)
        self.replace_var = self._bind_trace(tk.StringVar(value=""))
        ttk.Entry(frame, textvariable=self.replace_var).grid(row=2, column=1, sticky="ew", pady=1)
        self.use_regex_var = self._bind_trace(tk.BooleanVar(value=False))
        ttk.Checkbutton(frame, text="Regex", variable=self.use_regex_var).grid(row=3, column=1, sticky="w")

        ttk.Label(frame, text="Case").grid(row=4, column=0, sticky="w", pady=1)
        self.case_var = self._bind_trace(tk.StringVar(value="No Change"))
        ttk.Combobox(
            frame, textvariable=self.case_var, values=["No Change", "lowercase", "UPPERCASE", "Title Case"],
            state="readonly", width=14,
        ).grid(row=4, column=1, sticky="ew", pady=1)

        ttk.Label(frame, text="Spaces").grid(row=5, column=0, sticky="w", pady=1)
        self.space_mode_var = self._bind_trace(tk.StringVar(value="Keep Spaces"))
        ttk.Combobox(
            frame, textvariable=self.space_mode_var,
            values=["Keep Spaces", "Replace with _", "Replace with -", "Remove Spaces"],
            state="readonly", width=14,
        ).grid(row=5, column=1, sticky="ew", pady=1)

        self.clean_special_var = self._bind_trace(tk.BooleanVar(value=False))
        ttk.Checkbutton(frame, text="Strip specials", variable=self.clean_special_var).grid(row=6, column=1, sticky="w")

        ttk.Label(frame, text="Date").grid(row=7, column=0, sticky="w", pady=1)
        date_row = ttk.Frame(frame)
        date_row.grid(row=7, column=1, sticky="ew")
        self.date_mode_var = self._bind_trace(tk.StringVar(value="None"))
        ttk.Combobox(
            date_row, textvariable=self.date_mode_var,
            values=["None", "File Modified Date", "Current Date"], state="readonly", width=12,
        ).pack(side=tk.LEFT)
        self.date_pos_var = self._bind_trace(tk.StringVar(value="Prefix"))
        ttk.Combobox(date_row, textvariable=self.date_pos_var, values=["Prefix", "Suffix"], state="readonly", width=7).pack(
            side=tk.LEFT, padx=2
        )

        ttk.Label(frame, text="Prefix").grid(row=8, column=0, sticky="w", pady=1)
        self.prefix_var = self._bind_trace(tk.StringVar(value=""))
        ttk.Entry(frame, textvariable=self.prefix_var).grid(row=8, column=1, sticky="ew", pady=1)
        ttk.Label(frame, text="Suffix").grid(row=9, column=0, sticky="w", pady=1)
        self.suffix_var = self._bind_trace(tk.StringVar(value=""))
        ttk.Entry(frame, textvariable=self.suffix_var).grid(row=9, column=1, sticky="ew", pady=1)

        self.add_num_var = self._bind_trace(tk.BooleanVar(value=False))
        ttk.Checkbutton(frame, text="Counter", variable=self.add_num_var).grid(row=10, column=0, sticky="w")
        num = ttk.Frame(frame)
        num.grid(row=10, column=1, sticky="w")
        self.num_start_var = self._bind_trace(tk.StringVar(value="1"))
        ttk.Entry(num, textvariable=self.num_start_var, width=4).pack(side=tk.LEFT)
        self.num_pad_var = self._bind_trace(tk.StringVar(value="3"))
        ttk.Entry(num, textvariable=self.num_pad_var, width=3).pack(side=tk.LEFT, padx=2)
        self.num_pos_var = self._bind_trace(tk.StringVar(value="Suffix"))
        ttk.Combobox(num, textvariable=self.num_pos_var, values=["Suffix", "Prefix"], state="readonly", width=7).pack(
            side=tk.LEFT
        )

        return frame

    def get_output_path(self, output_dir, files):
        return output_dir


def cli_main():
    import argparse

    parser = argparse.ArgumentParser(description="Batch rename files (in place)")
    parser.add_argument("-i", "--inputs", nargs="+", required=True)
    parser.add_argument("--prefix", default="")
    parser.add_argument("--suffix", default="")
    parser.add_argument("--find", default="")
    parser.add_argument("--replace", default="")
    parser.add_argument("--regex", action="store_true")
    parser.add_argument("--counter", action="store_true")
    args = parser.parse_args()

    plugin = FileRenamerPlugin()
    files = plugin.collect_input_files(args.inputs)
    if not files:
        print("No matching files found.")
        sys.exit(1)

    plugin.prefix_var = tk.StringVar(value=args.prefix)
    plugin.suffix_var = tk.StringVar(value=args.suffix)
    plugin.find_var = tk.StringVar(value=args.find)
    plugin.replace_var = tk.StringVar(value=args.replace)
    plugin.use_regex_var = tk.BooleanVar(value=args.regex)
    plugin.add_num_var = tk.BooleanVar(value=args.counter)
    plugin.trim_start_var = tk.StringVar(value="0")
    plugin.trim_end_var = tk.StringVar(value="0")
    plugin.case_var = tk.StringVar(value="No Change")
    plugin.space_mode_var = tk.StringVar(value="Keep Spaces")
    plugin.clean_special_var = tk.BooleanVar(value=False)
    plugin.date_mode_var = tk.StringVar(value="None")
    plugin.date_pos_var = tk.StringVar(value="Prefix")
    plugin.num_start_var = tk.StringVar(value="1")
    plugin.num_pad_var = tk.StringVar(value="3")
    plugin.num_pos_var = tk.StringVar(value="Suffix")
    plugin.execute(files, str(Path(files[0]).parent))


if __name__ == "__main__":
    plugin_entry(FileRenamerPlugin, cli_main)