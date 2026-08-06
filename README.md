# Universal File Toolkit

Modular desktop toolkit. Drop a plugin into `plugins/` — it auto-loads in the host and can also run alone.

## Run

```bash
pip install -r requirements.txt
python app.py                          # host (all plugins)
python plugins/file_renamer.py         # standalone GUI (no args)
python plugins/file_renamer.py -i a.txt --prefix x_   # CLI when args given
```

## Add a plugin

See **[DEV.md](DEV.md)** for the full plugin contract, template, and checklist.

Quick path: drop `plugins/my_tool.py` subclassing `BaseFileOperation`, implement `execute` / `render_options_ui`, end with `plugin_entry(MyPlugin, cli_main)`. Auto-discovered — no registration list.

## Output directory

Plugins with `needs_output_dir = False` hide the output folder UI (e.g. Batch File Renamer). Others default to the source files’ folder when the field is empty.
