# PDF Compressor (`pdf_to_compress.py`)

Shrink PDFs with Ghostscript.

## Requirements

Portable Ghostscript under `tools/GhostScript/bin` (e.g. `gswin64c.exe`), or `gs` / `gswin64c` on PATH.

## Modes

| Mode | Quality | Resize | Notes |
|------|---------|--------|--------|
| High | high | no | `/printer` — best look |
| Mid | medium | yes | `/ebook` — default |
| Low | low | yes | `/screen` — smaller |
| Max | low | yes | strongest downsample |

Options: grayscale, quality / resize / compress overrides, skip `_compressed` suffix.

## Output

Writes `{stem}_compressed.pdf` into the host OUTPUT folder (or beside the source when that field is empty). With “No _compressed suffix”, overwrites safely via a temp file when the destination is the same path.

## Run

```bash
python modular-file-manager.py
python plugins/pdf_to_compress.py
python plugins/pdf_to_compress.py -i doc.pdf --mode mid
```
