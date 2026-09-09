# Image Format Converter (`images_to_format.py`)

Convert images to another format beside the source. Optional recursive folder watch (GUI or CLI).

## Formats

Input: `.jpg` `.jpeg` `.png` `.webp` `.bmp` `.tif` `.tiff`  
Output: `jpg` `png` `webp` `bmp` `tif`

Options: overwrite existing output, delete original after convert.

## Run

```bash
python plugins/images_to_format.py
python plugins/images_to_format.py -i a.png b.jpg --format webp --overwrite
python plugins/images_to_format.py --watch ./inbox ./drops --format jpg --delete
python plugins/images_to_format.py -i ./batch --format png --watch ./inbox
```

Requires `watchdog` (and Pillow) — see `requirements.txt`.
