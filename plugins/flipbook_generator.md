# N-up & Booklet (`flipbook_generator.py`)

Impose PDF/image pages as **1-up**, **2-up**, **N-up** (cols×rows), or **Booklet** sheets.

## GUI

```bash
python plugins/flipbook_generator.py
```

## CLI

```bash
python plugins/flipbook_generator.py -i doc.pdf --mode Booklet
python plugins/flipbook_generator.py -i pages/*.png --mode N-up --cols 2 --rows 2
```
