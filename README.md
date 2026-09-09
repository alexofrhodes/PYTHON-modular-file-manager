# Universal File Toolkit

Modular desktop toolkit. Drop a plugin into `plugins/` — it auto-loads in the host and can also run alone.

Plugins use filenames `{inputs}_to_{output}` (e.g. `docs_to_markdown.py`, `pdf_to_compress.py`). Each tool is separable: `python plugins/<name>.py` opens its standalone GUI.

## Run

```bash
pip install -r requirements.txt
python modular-file-manager.py              # host (all plugins)
python plugins/files_to_rename.py           # standalone GUI (no args)
python plugins/files_to_rename.py -i a.txt --prefix x_   # CLI when args given
```

## Add a plugin

See **[DEV.md](DEV.md)** for the full plugin contract, template, and checklist.

Quick path: drop `plugins/my_tool.py` subclassing `BaseFileOperation`, implement `execute` / `render_options_ui`, end with `plugin_entry(MyPlugin, cli_main)`. Auto-discovered — no registration list.

## Output directory

Plugins with `needs_output_dir = False` hide the output folder UI (e.g. Batch File Renamer). Others default to the source files’ folder when the field is empty.

## PDF Compressor

Uses portable Ghostscript from `tools/GhostScript/bin` (or `gs` on PATH). See [plugins/pdf_to_compress.md](plugins/pdf_to_compress.md).

## Image Format Converter

Convert images beside their sources; optional folder watch. See [plugins/images_to_format.md](plugins/images_to_format.md).
