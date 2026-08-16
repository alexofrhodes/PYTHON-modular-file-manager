# Plugin development

How to add a tool that works in the host (`modular-file-manager.py`), as a standalone GUI, and from the CLI.

## Layout

```python
PYTHON-modular-file-manager/
  modular-file-manager.py   # BaseFileOperation, theme, host UI, StandalonePluginApp, plugin_entry
  plugins/
    __init__.py             # import_host() — loads the hyphenated host module
    my_tool.py              # one module = one (or more) plugin class(es)
    my_tool.md              # optional short docs
  requirements.txt
```

No central registry. The host scans `plugins/` with `pkgutil.iter_modules`, imports each module, and instantiates every concrete `BaseFileOperation` subclass (deduped by class object).

## Contract (`BaseFileOperation`)

Load the host via `plugins.import_host` (the host file name has a hyphen, so it is not a normal package import):

```python
try:
    from plugins import import_host
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from plugins import import_host

_host = import_host()
BaseFileOperation = _host.BaseFileOperation
plugin_entry = _host.plugin_entry
```

| Attribute / method | Required | Purpose |
| -------------------- | ---------- | --------- |
| `name` | yes | Unique label in the host tool dropdown |
| `description` | no | Human summary |
| `supported_extensions` | no | Tuple like `(".pdf", ".png")`; empty `()` = accept all |
| `needs_output_dir` | no | Default `True`. Set `False` for in-place tools (e.g. rename) so host/standalone hide the output folder |
| `execute(files, output_path, **kwargs)` | **yes** | Do the work. `files` is a list of absolute paths |
| `render_options_ui(parent, on_change_callback=None)` | no | Build ttk controls; **return** the root frame (or `None`) |
| `get_output_path(output_dir, files)` | no | Map chosen directory → final path/dir (default: return `output_dir`) |
| `get_extra_columns()` | no | Extra Treeview headers in the **host** queue |
| `get_extra_row_data(path, index)` | no | Values for those columns (live preview) |
| `filter_inputs(files)` | no | Override if filtering needs more than extension checks |

Helpers already on the base class (use them in CLI and GUI):

- `collect_input_files(inputs)` — expands globs and `.txt` pattern lists, dedupes
- `filter_inputs(files)` — keeps paths matching `supported_extensions`

### `execute` and output

- Host / standalone resolve an `output_dir` (explicit field, or first file’s parent, or cwd).
- They call `get_output_path(output_dir, files)` then `execute(files, output_path)`.
- If `needs_output_dir` is `False`, the UI hides the folder field; `output_path` is still a usable directory (usually the first file’s parent) if you need a scratch location.
- Prefer writing beside sources when no path is given; do not assume a fixed `output/` folder.

### Options UI

- Prefer **ttk** widgets; keep the panel **compact** (small padding, dense rows).
- Store settings on `self` as `tk.StringVar` / `BooleanVar` / widgets so `execute` can read them.
- Accept `on_change_callback` and call it when preview-relevant options change (host refreshes the queue). Signature: `render_options_ui(self, parent_frame, on_change_callback=None)`.
- In the host sidebar, styles like `SidebarMuted.TLabel` match the sidebar background. In standalone mode the options sit on a white card — plain `ttk.Label` is fine; avoid hard-coded grey backgrounds.
- Theme source of truth: `apply_toolkit_styles` / `DEFAULT_COLORS` in `modular-file-manager.py`. Prefer existing style names (`Accent.TButton`, `Toolbar.TButton`, `Card.*`, `Sidebar.*`) over new ones.

## Minimal template

```python
# plugins/example_tool.py
from __future__ import annotations

import argparse
import sys
from pathlib import Path
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


class ExampleToolPlugin(BaseFileOperation):
    name = "Example Tool"
    description = "Does one clear job."
    supported_extensions = (".txt", ".md")
    needs_output_dir = True

    def execute(self, files, output_path, **kwargs):
        if not files:
            raise ValueError("No files provided.")
        out_dir = Path(output_path)
        if out_dir.suffix:
            out_dir = out_dir.parent
        out_dir.mkdir(parents=True, exist_ok=True)
        # read options created in render_options_ui
        flag = self.flag_var.get() if hasattr(self, "flag_var") else False
        for f in files:
            print(f"Processing {f} (flag={flag})")
            # ... write results under out_dir ...

    def render_options_ui(self, parent_frame, on_change_callback=None):
        frame = ttk.Frame(parent_frame, padding=4)
        self.flag_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frame, text="Example flag", variable=self.flag_var).pack(anchor=tk.W)
        return frame

    def get_output_path(self, output_dir, files):
        return output_dir


def cli_main():
    parser = argparse.ArgumentParser(description="Example Tool")
    parser.add_argument("-i", "--inputs", nargs="+", required=True)
    parser.add_argument("-o", "--output", default="", help="Output dir (default: beside first input)")
    parser.add_argument("--flag", action="store_true")
    args = parser.parse_args()

    plugin = ExampleToolPlugin()
    files = plugin.filter_inputs(plugin.collect_input_files(args.inputs))
    if not files:
        print("No matching files.")
        sys.exit(1)

    plugin.flag_var = tk.BooleanVar(value=args.flag)
    out = args.output.strip() or str(Path(files[0]).parent)
    plugin.execute(files, plugin.get_output_path(out, files))


if __name__ == "__main__":
    plugin_entry(ExampleToolPlugin, cli_main)
```

## Entry points

```python
plugin_entry(ExampleToolPlugin, cli_main)
```

| How you run it | Behavior |
| ---------------- | ---------- |
| `python plugins/example_tool.py` | No argv beyond script → `StandalonePluginApp` (compact GUI) |
| `python plugins/example_tool.py -i ...` | Calls `cli_main()` |
| `python modular-file-manager.py` | Host loads all plugins; shared queue + sidebar options |

Do **not** put argparse or GUI launch code at import time (module body). Only under `cli_main` / `if __name__ == "__main__"`. Side effects on import break host auto-load.

## Host vs standalone

| | Host (`UniversalToolkitApp`) | Standalone (`StandalonePluginApp`) |
| -- | ------------------------------ | ------------------------------------- |
| Queue | Treeview + search + optional extra columns | Simple listbox |
| Options | Scrollable left sidebar | Right-hand card |
| Output UI | Shown if `needs_output_dir` | Same |
| Profiles / multi-tool | Yes | No — one plugin only |
| Drag-and-drop | Via `windnd` when installed | Same |

Implement logic once in the plugin class; both shells only call `render_options_ui` and `execute`.

## Discovery rules

1. File must live under `plugins/` and be importable as `plugins.<module>` (no hyphens in the filename).
2. Class must subclass `BaseFileOperation` and not be abstract (implement `execute`).
3. Multiple plugin classes in one module are all loaded; use one class per module unless you have a reason.
4. Avoid class aliases that point at the same subclass twice (the host dedupes by class, but `name` collisions overwrite in the dropdown).
5. Optional deps: guard with `try/import` and degrade gracefully when a library is missing.

## Checklist for a new plugin

- [ ] `plugins/<snake_name>.py` with a unique `name`
- [ ] `needs_output_dir` set correctly
- [ ] `execute` works with vars seeded by CLI (no GUI required)
- [ ] `plugin_entry(YourClass, cli_main)` at the bottom
- [ ] No import-time GUI or `parse_args()`
- [ ] Compact `render_options_ui` returning a frame
- [ ] Optional `plugins/<snake_name>.md` for usage notes
- [ ] Extra deps documented in `requirements.txt` (required or commented optional)

## Reference plugins

| Module | Notes |
| -------- | -------- |
| `file_renamer.py` | `needs_output_dir = False`, live preview columns |
| `pdf_merger.py` | Custom `get_output_path` for a single output file |
| `pdf_compressor.py` | Ghostscript via `tools/GhostScript` (or PATH) |
| `flipbook_generator.py` | Mode-dependent options (N-up cols/rows; Booklet sig pages) |
| `pdf_to_markdown.py` | Multiple engines + OCR tabs |
| `pdf_stitcher.py` | Compact option rows + CLI seeding pattern |
