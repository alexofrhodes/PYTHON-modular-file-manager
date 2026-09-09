# N-up & Booklet (`images_pdf_to_nup.py`)

Imposes PDF pages or images into 1-up, 2-up, N-up, or booklet layouts.

```bash
python plugins/images_pdf_to_nup.py
python plugins/images_pdf_to_nup.py -i doc.pdf --mode Booklet
python plugins/images_pdf_to_nup.py -i doc.pdf --mode Booklet --pages-per-signature 16
python plugins/images_pdf_to_nup.py -i doc.pdf --mode Booklet --pages-per-signature All
python plugins/images_pdf_to_nup.py -i pages/*.png --mode N-up --cols 2 --rows 2
python plugins/images_pdf_to_nup.py --self-check
```
