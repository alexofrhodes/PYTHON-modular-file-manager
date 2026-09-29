# Image Overlay (`images_to_overlay.py`)

Bake text, QR codes, and icons onto images. Save **layouts** (positions/styles) and **field presets** (reusable values) in `data/overlay_store.json`.

## Run

```bash
python plugins/images_to_overlay.py
python plugins/images_to_overlay.py -i photo.jpg -o out/ --layout "My layout" --fields "Company footer"
python plugins/images_to_overlay.py --self-check
```

Requires Pillow. Optional: `qrcode` for QR elements.
