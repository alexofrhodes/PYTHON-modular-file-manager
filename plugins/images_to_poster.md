# A4 Poster (`images_to_poster.py`)

Scale an image (or first PDF page) into a multi-page A4 poster for printing. Uses **pdfposter**.

## Options

| Option | Meaning |
| --- | --- |
| A4 cols × rows | Poster grid (e.g. 2×2 = 4 sheets) |
| Output | `{stem}_poster.pdf` in the OUTPUT folder |

## Run

```bash
python plugins/images_to_poster.py
python plugins/images_to_poster.py -i photo.jpg -o out/ --cols 2 --rows 2
python plugins/images_to_poster.py --self-check
```

Requires: `pdfposter`, Pillow; PyMuPDF for PDF inputs.
