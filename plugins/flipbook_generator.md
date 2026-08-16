# N-up & Booklet (`flipbook_generator.py`)

Impose PDF/image pages as **1-up**, **2-up**, **N-up** (cols×rows), or **Booklet** sheets.

**Booklet** nests outer/inner sheet pairs. Use **Sig pages** (`--pages-per-signature`) to split long jobs into foldable signatures (8 / 16 / 24 / 32 / 48 / All). Default **32**. Fold and bind each signature, then stack in order.

## GUI

```bash
python plugins/flipbook_generator.py
```

## CLI

```bash
python plugins/flipbook_generator.py -i doc.pdf --mode Booklet
python plugins/flipbook_generator.py -i doc.pdf --mode Booklet --pages-per-signature 16
python plugins/flipbook_generator.py -i doc.pdf --mode Booklet --pages-per-signature All
python plugins/flipbook_generator.py -i pages/*.png --mode N-up --cols 2 --rows 2
python plugins/flipbook_generator.py --self-check
```
