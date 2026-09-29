"""Compose text / QR / icon overlays onto images (file-manager port of Event-Manager poster overlay)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont

    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

try:
    import qrcode

    QRCODE_AVAILABLE = True
except Exception:
    QRCODE_AVAILABLE = False

# Toolkit root (parent of plugins/)
ROOT_DIR = Path(__file__).resolve().parent.parent
STORE_PATH = ROOT_DIR / "data" / "overlay_store.json"

# Built-in slots: all values come from fields dict or element["value"] (no event DB).
ELEMENT_DEFS = (
    ("title", "text", "title", "Title"),
    ("titleTranslated", "text", "titleTranslated", "Title (tr)"),
    ("date", "text", "date", "Date"),
    ("time", "text", "time", "Time"),
    ("location", "text", "location", "Location"),
    ("locationTranslated", "text", "locationTranslated", "Location (tr)"),
    ("notesTranslated", "text", "notesTranslated", "Description"),
    ("custom_note", "text", "custom", "Note"),
    ("qr_url", "qr", "url", "QR link"),
    ("qr_custom", "qr", "custom", "Custom QR"),
)
ICON_FIELDS = ("pin", "calendar", "link", "note", "circle", "line", "number")
ICON_LABELS = {
    "pin": "Pin",
    "calendar": "Calendar",
    "link": "Link",
    "note": "Note icon",
    "circle": "Circle",
    "line": "Line",
    "number": "Number",
}

_DEFAULT_TEXT = {
    "font_size": 28,
    "color": "#ffffff",
    "bg": "#000000",
    "bg_alpha": 160,
    "align": "left",
}
_DEFAULT_QR = {"fg": "#000000", "bg": "#ffffff"}

_STARTER_LAYOUT = {
    "title": {"x": 0.03, "y": 0.03, "w": 0.70, "h": 0.08},
    "titleTranslated": {"x": 0.03, "y": 0.12, "w": 0.70, "h": 0.08},
    "date": {"x": 0.03, "y": 0.90, "w": 0.20, "h": 0.045},
    "time": {"x": 0.24, "y": 0.90, "w": 0.12, "h": 0.045},
    "location": {"x": 0.03, "y": 0.82, "w": 0.70, "h": 0.08},
    "locationTranslated": {"x": 0.03, "y": 0.74, "w": 0.70, "h": 0.07},
    "notesTranslated": {"x": 0.03, "y": 0.22, "w": 0.70, "h": 0.12},
    "custom_note": {"x": 0.03, "y": 0.36, "w": 0.50, "h": 0.08},
    "qr_url": {"x": 0.85, "y": 0.03, "w": 0.12, "h": 0.12},
    "qr_custom": {"x": 0.85, "y": 0.16, "w": 0.12, "h": 0.12},
}

_PAGE_LAYOUT = {
    "title": {"x": 0.04, "y": 0.03, "w": 0.70, "h": 0.06},
    "titleTranslated": {"x": 0.04, "y": 0.10, "w": 0.70, "h": 0.06},
    "date": {"x": 0.04, "y": 0.90, "w": 0.20, "h": 0.04},
    "time": {"x": 0.25, "y": 0.90, "w": 0.12, "h": 0.04},
    "location": {"x": 0.04, "y": 0.82, "w": 0.70, "h": 0.07},
    "locationTranslated": {"x": 0.04, "y": 0.75, "w": 0.70, "h": 0.06},
    "notesTranslated": {"x": 0.04, "y": 0.17, "w": 0.70, "h": 0.10},
    "custom_note": {"x": 0.04, "y": 0.28, "w": 0.50, "h": 0.06},
    "qr_url": {"x": 0.85, "y": 0.82, "w": 0.12, "h": 0.12},
    "qr_custom": {"x": 0.85, "y": 0.03, "w": 0.12, "h": 0.12},
}

PACK_GAP = 0.006

# Slot ids whose values live in field presets / fields dict
FIELD_SLOT_IDS = tuple(eid for eid, _t, _f, _l in ELEMENT_DEFS)


def default_overlay_spec(*, mode="on_poster"):
    layout = _PAGE_LAYOUT if mode == "on_page" else _STARTER_LAYOUT
    elements = []
    for eid, etype, field, _label in ELEMENT_DEFS:
        box = dict(layout[eid])
        el = {"id": eid, "type": etype, "field": field, "enabled": False, **box}
        if etype == "text":
            el.update(_DEFAULT_TEXT)
            if mode == "on_page":
                el["color"] = "#111111"
                el["bg"] = "#ffffff"
                el["bg_alpha"] = 0
                el["font_size"] = 24
            el["value"] = ""
        else:
            el.update(_DEFAULT_QR)
            el["value"] = ""
        elements.append(el)
    return {
        "mode": mode if mode in ("on_poster", "on_page") else "on_poster",
        "orientation": "auto",
        "page": "a4",
        "page_dpi": 150,
        "page_bg": "#ffffff",
        "poster_margin": 0.06,
        "elements": elements,
    }


def _style_for_mode(mode, etype="text"):
    if etype == "icon":
        color = "#111111" if mode == "on_page" else "#ffffff"
        bg = "#ffffff" if mode == "on_page" else "#0f172a"
        return {"color": color, "fg": color, "bg": bg, "bg_alpha": 0}
    style = dict(_DEFAULT_TEXT)
    if mode == "on_page":
        style.update({"color": "#111111", "bg": "#ffffff", "bg_alpha": 0, "font_size": 24})
    return style


def make_custom_note(spec, *, enabled=True, value=""):
    mode = spec.get("mode") or "on_poster"
    n = 1 + sum(
        1
        for el in spec.get("elements") or []
        if el.get("type") == "text" and el.get("field") == "custom"
    )
    y = min(0.85, 0.12 + 0.08 * max(0, n - 1))
    el = {
        "id": f"note_{n}",
        "type": "text",
        "field": "custom",
        "enabled": enabled,
        "value": value,
        "x": 0.03,
        "y": y,
        "w": 0.50,
        "h": 0.08,
        **_style_for_mode(mode, "text"),
    }
    spec.setdefault("elements", []).append(el)
    return el


def make_icon_element(spec, field, *, enabled=True):
    if field not in ICON_FIELDS:
        field = "pin"
    mode = spec.get("mode") or "on_poster"
    n = 1 + sum(1 for el in spec.get("elements") or [] if el.get("type") == "icon")
    if field == "line":
        box = {"x": 0.03, "y": min(0.90, 0.08 + 0.05 * n), "w": 0.22, "h": 0.012}
    else:
        box = {"x": 0.03, "y": min(0.90, 0.04 + 0.06 * n), "w": 0.06, "h": 0.06}
    el = {
        "id": f"icon_{field}_{n}",
        "type": "icon",
        "field": field,
        "enabled": enabled,
        **box,
        **_style_for_mode(mode, "icon"),
    }
    if field == "number":
        used = []
        for item in spec.get("elements") or []:
            if item.get("type") == "icon" and item.get("field") == "number":
                try:
                    used.append(int(str(item.get("value") or "0").strip() or "0"))
                except ValueError:
                    pass
        el["value"] = str((max(used) + 1) if used else 1)
    spec.setdefault("elements", []).append(el)
    return el


def element_label(el, elements=None):
    eid = el.get("id")
    for did, _t, _f, label in ELEMENT_DEFS:
        if did == eid:
            return label
    if el.get("type") == "icon":
        field = el.get("field")
        if field == "number":
            return f"#{el.get('value') or '1'}"
        return ICON_LABELS.get(field, "Icon")
    if el.get("type") == "text" and el.get("field") == "custom":
        notes = [
            item
            for item in (elements or [])
            if item.get("type") == "text" and item.get("field") == "custom"
        ]
        try:
            idx = notes.index(el) + 1
        except ValueError:
            idx = 1
        return "Note" if idx == 1 else f"Note {idx}"
    return eid or "Element"


def _apply_box_and_style(item, target):
    target["enabled"] = bool(item.get("enabled"))
    for key in ("x", "y", "w", "h"):
        try:
            target[key] = max(0.0, min(1.0, float(item.get(key, target[key]))))
        except (TypeError, ValueError):
            pass
    if target["type"] == "text":
        try:
            target["font_size"] = max(
                8, min(200, int(item.get("font_size", target.get("font_size", 28))))
            )
        except (TypeError, ValueError):
            pass
        for key in ("color", "bg", "align"):
            if isinstance(item.get(key), str) and item[key].strip():
                target[key] = item[key].strip()
        if target.get("align") not in ("left", "center", "right"):
            target["align"] = "left"
        try:
            target["bg_alpha"] = max(
                0, min(255, int(item.get("bg_alpha", target.get("bg_alpha", 0))))
            )
        except (TypeError, ValueError):
            pass
        if "value" in item or target.get("field") == "custom":
            target["value"] = str(item.get("value") or target.get("value") or "")
    elif target["type"] == "icon":
        for key in ("color", "fg", "bg"):
            if isinstance(item.get(key), str) and item[key].strip():
                target[key] = item[key].strip()
        if target.get("field") == "number":
            target["value"] = str(item.get("value") or target.get("value") or "1")
    else:
        for key in ("fg", "bg"):
            if isinstance(item.get(key), str) and item[key].strip():
                target[key] = item[key].strip()
        if "value" in item or target.get("field") in ("custom", "url"):
            target["value"] = str(item.get("value") or target.get("value") or "")
    return target


def sanitize_overlay_spec(raw):
    if not isinstance(raw, dict):
        return default_overlay_spec()
    mode = raw.get("mode") if raw.get("mode") in ("on_poster", "on_page") else "on_poster"
    spec = default_overlay_spec(mode=mode)
    if raw.get("orientation") in ("auto", "portrait", "landscape"):
        spec["orientation"] = raw["orientation"]
    try:
        dpi = int(raw.get("page_dpi") or 150)
        spec["page_dpi"] = max(72, min(300, dpi))
    except (TypeError, ValueError):
        pass
    if isinstance(raw.get("page_bg"), str) and raw["page_bg"].strip():
        spec["page_bg"] = raw["page_bg"].strip()
    try:
        margin = float(raw.get("poster_margin", 0.06))
        spec["poster_margin"] = max(0.0, min(0.25, margin))
    except (TypeError, ValueError):
        pass

    by_id = {el["id"]: el for el in spec["elements"]}
    extras = []
    for item in raw.get("elements") or []:
        if not isinstance(item, dict):
            continue
        eid = item.get("id")
        if eid in by_id:
            _apply_box_and_style(item, by_id[eid])
            continue
        if item.get("type") == "text" and item.get("field") == "custom":
            note = {
                "id": str(eid or f"note_{len(extras) + 2}"),
                "type": "text",
                "field": "custom",
                "enabled": False,
                "value": "",
                "x": 0.03,
                "y": 0.12,
                "w": 0.50,
                "h": 0.08,
                **_style_for_mode(mode, "text"),
            }
            extras.append(_apply_box_and_style(item, note))
        elif item.get("type") == "icon" and item.get("field") in ICON_FIELDS:
            icon = {
                "id": str(eid or f"icon_{item.get('field')}_{len(extras) + 1}"),
                "type": "icon",
                "field": item.get("field"),
                "enabled": False,
                "value": str(item.get("value") or ""),
                "x": 0.03,
                "y": 0.04,
                "w": 0.05 if item.get("field") != "line" else 0.22,
                "h": 0.05 if item.get("field") != "line" else 0.012,
                **_style_for_mode(mode, "icon"),
            }
            extras.append(_apply_box_and_style(item, icon))
    spec["elements"].extend(extras)
    return spec


# --- JSON store (layouts + field presets) ---


def _empty_store():
    return {"layouts": {}, "field_presets": {}}


def load_store():
    if not STORE_PATH.is_file():
        return _empty_store()
    try:
        with open(STORE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return _empty_store()
        layouts = data.get("layouts") if isinstance(data.get("layouts"), dict) else {}
        # migrate old Event-Manager "templates" key if present
        if not layouts and isinstance(data.get("templates"), dict):
            layouts = data["templates"]
        presets = (
            data.get("field_presets") if isinstance(data.get("field_presets"), dict) else {}
        )
        cleaned_layouts = {}
        for name, spec in layouts.items():
            name = str(name or "").strip()
            if name:
                cleaned_layouts[name] = sanitize_overlay_spec(spec)
        cleaned_presets = {}
        for name, fields in presets.items():
            name = str(name or "").strip()
            if name and isinstance(fields, dict):
                cleaned_presets[name] = {
                    str(k): str(v or "") for k, v in fields.items() if str(k).strip()
                }
        return {"layouts": cleaned_layouts, "field_presets": cleaned_presets}
    except Exception:
        return _empty_store()


def _write_store(store):
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)


def list_layouts():
    return sorted(load_store()["layouts"].keys(), key=str.lower)


def load_layouts():
    return load_store()["layouts"]


def save_layout(name, spec):
    name = str(name or "").strip()
    if not name:
        return False, "Layout name is required."
    store = load_store()
    store["layouts"][name] = sanitize_overlay_spec(spec)
    try:
        _write_store(store)
    except Exception as exc:
        return False, str(exc)
    return True, name


def delete_layout(name):
    name = str(name or "").strip()
    store = load_store()
    if name not in store["layouts"]:
        return False, "Layout not found."
    del store["layouts"][name]
    try:
        _write_store(store)
    except Exception as exc:
        return False, str(exc)
    return True, name


def list_field_presets():
    return sorted(load_store()["field_presets"].keys(), key=str.lower)


def load_field_presets():
    return load_store()["field_presets"]


def save_field_preset(name, fields):
    name = str(name or "").strip()
    if not name:
        return False, "Preset name is required."
    if not isinstance(fields, dict):
        return False, "Fields must be a dict."
    store = load_store()
    store["field_presets"][name] = {
        str(k): str(v or "") for k, v in fields.items() if str(k).strip()
    }
    try:
        _write_store(store)
    except Exception as exc:
        return False, str(exc)
    return True, name


def delete_field_preset(name):
    name = str(name or "").strip()
    store = load_store()
    if name not in store["field_presets"]:
        return False, "Preset not found."
    del store["field_presets"][name]
    try:
        _write_store(store)
    except Exception as exc:
        return False, str(exc)
    return True, name


def fields_from_spec(spec):
    """Extract editable slot values from a spec's elements."""
    out = {}
    for el in spec.get("elements") or []:
        eid = el.get("id")
        if not eid:
            continue
        if el.get("type") in ("text", "qr") and el.get("field") in (
            "custom",
            "url",
            "title",
            "titleTranslated",
            "date",
            "time",
            "location",
            "locationTranslated",
            "notesTranslated",
        ):
            out[eid] = str(el.get("value") or "")
    return out


def apply_fields_to_spec(spec, fields):
    """Write field values onto matching element ids (and enable non-empty ones if disabled)."""
    fields = fields or {}
    for el in spec.get("elements") or []:
        eid = el.get("id")
        if eid in fields:
            el["value"] = str(fields[eid] or "")
    return spec


def normalize_http_url(url):
    url = (url or "").strip()
    if not url:
        return ""
    if url.startswith(("http://", "https://")):
        return url
    return "https://" + url


def resolve_element_payload(element, fields=None):
    """Return (kind, value) where kind is 'text', 'url', or 'icon', or (None, reason)."""
    fields = fields or {}
    field = element.get("field")
    etype = element.get("type")
    eid = element.get("id") or ""

    if etype == "icon" and field in ICON_FIELDS:
        return "icon", field

    # Prefer fields dict by element id, then element value
    raw = ""
    if eid in fields and str(fields[eid] or "").strip():
        raw = str(fields[eid])
    elif str(element.get("value") or "").strip():
        raw = str(element.get("value"))

    if etype == "qr":
        if not raw.strip():
            return None, "empty QR value"
        return "url", normalize_http_url(raw.strip())

    if etype == "text":
        if not raw.strip():
            return None, f"no {eid or field}"
        return "text", raw.rstrip("\n")

    return None, "unknown field"


def detect_orientation(width, height):
    return "portrait" if height >= width else "landscape"


def resolve_page_orientation(spec, poster_w, poster_h):
    orient = (spec.get("orientation") or "auto").strip().lower()
    if orient in ("portrait", "landscape"):
        return orient
    return detect_orientation(poster_w, poster_h)


def a4_pixel_size(orientation="portrait", dpi=150):
    w = int(round(210 / 25.4 * dpi))
    h = int(round(297 / 25.4 * dpi))
    if orientation == "landscape":
        return h, w
    return w, h


def _parse_color(value, default=(0, 0, 0)):
    text = (value or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        return default
    try:
        return tuple(int(text[i : i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return default


def _load_font(size):
    size = max(8, int(size))
    candidates = [
        r"C:\Windows\Fonts\segoeui.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        r"C:\Windows\Fonts\calibri.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for path in candidates:
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap_text(draw, text, font, max_width):
    paragraphs = (text or "").split("\n")
    lines = []
    for para in paragraphs:
        words = para.split()
        if not words:
            lines.append("")
            continue
        current = words[0]
        for word in words[1:]:
            trial = f"{current} {word}"
            if draw.textlength(trial, font=font) <= max_width:
                current = trial
            else:
                lines.append(current)
                current = word
        lines.append(current)
    return lines or [""]


def _make_qr_image(url, size, fg="#000000", bg="#ffffff"):
    if not QRCODE_AVAILABLE:
        raise RuntimeError("qrcode package is not installed")
    qr = qrcode.QRCode(border=1, box_size=8)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color=fg, back_color=bg).convert("RGBA")
    return img.resize((size, size), Image.Resampling.NEAREST)


def _layout_text(payload, font_size, max_w):
    font = _load_font(font_size)
    dummy = ImageDraw.Draw(Image.new("RGBA", (8, 8)))
    pad = 6
    inner = max(8, int(max_w) - 2 * pad)
    lines = _wrap_text(dummy, payload or " ", font, inner)
    line_h = int(getattr(font, "size", 14) * 1.25)
    tw = max(dummy.textlength(line, font=font) for line in lines)
    return font, lines, int(tw + 2 * pad), int(line_h * len(lines) + 2 * pad), pad, line_h


def _text_pixel_size(payload, font_size, max_w):
    _font, _lines, tw, th, _pad, _lh = _layout_text(payload, font_size, max_w)
    return tw, th


def fit_font_to_box(payload, box_w, box_h, min_size=8, max_size=200):
    box_w = max(8, int(box_w))
    box_h = max(8, int(box_h))
    lo, hi, best = min_size, max_size, min_size
    while lo <= hi:
        mid = (lo + hi) // 2
        tw, th = _text_pixel_size(payload or " ", mid, box_w)
        if tw <= box_w and th <= box_h:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _text_cap(el):
    if el.get("id") in ("location", "title") or el.get("field") in ("location", "title"):
        return 0.70
    if el.get("field") == "custom":
        return 0.70
    return min(0.55, max(0.08, float(el.get("w", 0.4))))


def autofit_element_box(el, payload, canvas_w, canvas_h):
    canvas_w = max(1, int(canvas_w))
    canvas_h = max(1, int(canvas_h))
    if el.get("type") == "qr" or (el.get("type") == "icon" and el.get("field") != "line"):
        size = max(0.04, min(float(el.get("w", 0.12)), float(el.get("h", 0.12))))
        el["w"] = el["h"] = size
        return
    if el.get("type") == "icon" and el.get("field") == "line":
        return
    cap = _text_cap(el)
    tw, th = _text_pixel_size(payload or " ", el.get("font_size", 28), cap * canvas_w)
    el["w"] = min(cap, max(0.04, tw / canvas_w))
    el["h"] = min(0.40, max(0.03, th / canvas_h))


def pack_elements_at_corner(elements, corner, fields, canvas_w, canvas_h):
    if not elements:
        return
    margin, gap = 0.03, PACK_GAP
    from_right = corner in ("top_right", "bottom_right")
    from_bottom = corner in ("bottom_left", "bottom_right")
    for el in elements:
        kind, payload = resolve_element_payload(el, fields)
        autofit_element_box(el, payload if kind else " ", canvas_w, canvas_h)

    rows = []
    current = []
    used = 0.0
    for el in elements:
        ew = float(el.get("w", 0.1))
        max_row = ew if el.get("type") in ("qr", "icon") else 0.72
        if current and used + gap + ew > max_row:
            rows.append(current)
            current = [el]
            used = ew
        else:
            current.append(el)
            used = ew if len(current) == 1 else used + gap + ew
    if current:
        rows.append(current)

    y = (1.0 - margin) if from_bottom else margin
    for row in rows:
        row_h = max(float(e.get("h", 0.04)) for e in row)
        if from_bottom:
            y -= row_h
        x = (1.0 - margin) if from_right else margin
        for el in row:
            ew = float(el.get("w", 0.1))
            if from_right:
                x -= ew
                el["x"] = max(0.0, min(1.0 - ew, x))
                x -= gap
            else:
                el["x"] = max(0.0, min(1.0 - ew, x))
                x += ew + gap
            el["y"] = max(0.0, min(1.0 - row_h, y))
        y = y - gap if from_bottom else y + row_h + gap


def pack_fresh_overlay(spec, fields, canvas_w, canvas_h):
    titles = [el for el in spec.get("elements") or [] if el.get("id") == "title"]
    texts = [el for el in spec.get("elements") or [] if el.get("id") in ("date", "time", "location")]
    qrs = [el for el in spec.get("elements") or [] if el.get("type") == "qr"]
    pack_elements_at_corner(titles, "top_left", fields, canvas_w, canvas_h)
    pack_elements_at_corner(texts, "bottom_left", fields, canvas_w, canvas_h)
    pack_elements_at_corner(qrs, "top_right", fields, canvas_w, canvas_h)


def _box_pixels(el, canvas_w, canvas_h):
    x = int(round(float(el.get("x", 0)) * canvas_w))
    y = int(round(float(el.get("y", 0)) * canvas_h))
    w = max(1, int(round(float(el.get("w", 0.1)) * canvas_w)))
    h = max(1, int(round(float(el.get("h", 0.1)) * canvas_h)))
    return x, y, w, h


def _anchor_fitted(x, y, w, h, fit_w, fit_h, canvas_w, canvas_h):
    if x + w / 2 >= canvas_w * 0.5:
        x = x + w - fit_w
    if y + h / 2 >= canvas_h * 0.5:
        y = y + h - fit_h
    return int(x), int(y), int(fit_w), int(fit_h)


def _clamp_box(x, y, w, h, canvas_w, canvas_h):
    w = max(1, min(int(w), canvas_w))
    h = max(1, min(int(h), canvas_h))
    x = max(0, min(int(x), canvas_w - w))
    y = max(0, min(int(y), canvas_h - h))
    return x, y, w, h


def _icon_font(size):
    size = max(8, int(size))
    for path in (
        r"C:\Windows\Fonts\segmdl2.ttf",
        r"C:\Windows\Fonts\SegoeIcons.ttf",
        r"C:\Windows\Fonts\Segoe Fluent Icons.ttf",
    ):
        if os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return None


_ICON_GLYPHS = {
    "pin": "\uE707",
    "calendar": "\uE787",
    "link": "\uE71B",
    "note": "\uE8A5",
}


def _centered_text(draw, text, font, cx, cy, fill):
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
    except Exception:
        try:
            bbox = font.getbbox(text)
        except Exception:
            return False
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    if tw < 2 or th < 2:
        return False
    draw.text((cx - tw / 2 - bbox[0], cy - th / 2 - bbox[1]), text, font=font, fill=fill)
    return True


def _draw_icon_fallback(draw, kind, ox, oy, size, fill):
    s = size - 1
    stroke = max(2, size // 12)
    if kind == "pin":
        cx = ox + size / 2
        r = size * 0.28
        cy = oy + size * 0.36
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=fill)
        draw.polygon(
            ((cx - r * 0.78, cy + r * 0.28), (cx + r * 0.78, cy + r * 0.28), (cx, oy + size * 0.96)),
            fill=fill,
        )
    elif kind == "calendar":
        m = max(2, size // 11)
        top = oy + m * 2
        draw.rounded_rectangle(
            (ox + m, top, ox + s - m, oy + s - m),
            radius=max(2, size // 8),
            outline=fill,
            width=stroke,
        )
        draw.rectangle((ox + m, top, ox + s - m, top + m * 2), fill=fill)
    elif kind == "link":
        w = max(2, size // 9)
        draw.arc((ox + size * 0.06, oy + size * 0.30, ox + size * 0.58, oy + size * 0.82), 40, 320, fill=fill, width=w)
        draw.arc((ox + size * 0.42, oy + size * 0.18, ox + size * 0.94, oy + size * 0.70), 220, 140, fill=fill, width=w)
    else:
        m = max(2, size // 12)
        draw.rounded_rectangle(
            (ox + m, oy + m, ox + s - m, oy + s - m),
            radius=max(2, size // 10),
            outline=fill,
            width=stroke,
        )


def _draw_icon(canvas, kind, x, y, w, h, color, bg="#000000", value=""):
    w, h = max(2, int(w)), max(2, int(h))
    fill = (*_parse_color(color, (255, 255, 255)), 255)
    ink = (*_parse_color(bg, (0, 0, 0)), 255)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    if kind == "line":
        stroke = max(2, min(w, h))
        if w >= h:
            cy = h / 2
            draw.line((0, cy, w - 1, cy), fill=fill, width=stroke)
        else:
            cx = w / 2
            draw.line((cx, 0, cx, h - 1), fill=fill, width=stroke)
        canvas.paste(overlay, (x, y), overlay)
        return
    size = min(w, h)
    ox, oy = (w - size) // 2, (h - size) // 2
    if kind == "circle":
        m = max(1, size // 14)
        width = max(2, size // 9)
        draw.ellipse(
            (ox + m, oy + m, ox + size - 1 - m, oy + size - 1 - m), outline=fill, width=width
        )
        canvas.paste(overlay, (x, y), overlay)
        return
    if kind == "number":
        m = max(1, size // 18)
        draw.ellipse((ox + m, oy + m, ox + size - 1 - m, oy + size - 1 - m), fill=fill)
        label = str(value or "1").strip() or "1"
        font = _load_font(max(8, int(size * (0.42 if len(label) > 1 else 0.54))))
        _centered_text(draw, label, font, ox + size / 2, oy + size / 2, ink)
        canvas.paste(overlay, (x, y), overlay)
        return
    glyph = _ICON_GLYPHS.get(kind)
    font = _icon_font(int(size * 0.92)) if glyph else None
    drew = bool(glyph and font and _centered_text(draw, glyph, font, ox + size / 2, oy + size / 2, fill))
    if not drew:
        _draw_icon_fallback(draw, kind, ox, oy, size, fill)
    canvas.paste(overlay, (x, y), overlay)


def _draw_elements(canvas, fields, elements, warnings):
    draw = ImageDraw.Draw(canvas, "RGBA")
    cw, ch = canvas.size
    for el in elements:
        if not el.get("enabled"):
            continue
        kind, payload = resolve_element_payload(el, fields)
        if kind is None:
            warnings.append(f"{el.get('id')}: {payload}")
            continue
        x, y, w, h = _box_pixels(el, cw, ch)
        if el.get("type") == "qr":
            size = max(16, min(w, h))
            try:
                qr_img = _make_qr_image(payload, size, fg=el.get("fg", "#000"), bg=el.get("bg", "#fff"))
            except Exception as exc:
                warnings.append(f"{el.get('id')}: QR failed ({exc})")
                continue
            x, y, w, h = _anchor_fitted(x, y, w, h, size, size, cw, ch)
            x, y, w, h = _clamp_box(x, y, w, h, cw, ch)
            canvas.paste(qr_img, (x, y), qr_img)
            continue
        if el.get("type") == "icon":
            x, y, w, h = _clamp_box(x, y, w, h, cw, ch)
            _draw_icon(
                canvas,
                payload,
                x,
                y,
                w,
                h,
                el.get("color") or el.get("fg") or "#ffffff",
                bg=el.get("bg") or "#000000",
                value=el.get("value") or "",
            )
            continue

        x, y, w, h = _clamp_box(x, y, w, h, cw, ch)
        font_size = fit_font_to_box(payload, w, h)
        font, lines, _fw, _fh, pad, line_h = _layout_text(payload, font_size, w)
        bg_alpha = int(el.get("bg_alpha", 0) or 0)
        bg_rgb = _parse_color(el.get("bg"), (0, 0, 0))
        if bg_alpha > 0:
            overlay = Image.new("RGBA", (w, h), (*bg_rgb, bg_alpha))
            canvas.paste(overlay, (x, y), overlay)
        color = _parse_color(el.get("color"), (255, 255, 255))
        align = el.get("align") or "left"
        ty = y + pad
        for line in lines:
            if ty + line_h > y + h:
                break
            tw = draw.textlength(line, font=font)
            if align == "center":
                tx = x + (w - tw) / 2
            elif align == "right":
                tx = x + w - pad - tw
            else:
                tx = x + pad
            draw.text((tx, ty), line, font=font, fill=(*color, 255))
            ty += line_h


def fit_poster_on_page(poster, page_size, margin_frac=0.06):
    page = Image.new("RGB", page_size, (255, 255, 255))
    pw, ph = page_size
    margin_x = int(pw * margin_frac)
    margin_y = int(ph * margin_frac)
    inner_w = max(1, pw - 2 * margin_x)
    inner_h = max(1, ph - 2 * margin_y)
    fitted = poster.copy()
    fitted.thumbnail((inner_w, inner_h), Image.Resampling.LANCZOS)
    ox = (pw - fitted.width) // 2
    oy = (ph - fitted.height) // 2
    if fitted.mode == "RGBA":
        page.paste(fitted, (ox, oy), fitted)
    else:
        page.paste(fitted.convert("RGB"), (ox, oy))
    return page


def compose_poster(original_path, fields=None, spec=None):
    if not PIL_AVAILABLE:
        raise RuntimeError("Pillow is required for overlays")
    if not os.path.isfile(original_path):
        raise FileNotFoundError(original_path)
    spec = sanitize_overlay_spec(spec)
    fields = dict(fields or {})
    # Merge element values into fields so resolve sees them
    for el in spec.get("elements") or []:
        eid = el.get("id")
        if eid and eid not in fields and str(el.get("value") or "").strip():
            fields[eid] = str(el.get("value"))
    warnings = []

    poster = Image.open(original_path)
    poster.load()
    poster = poster.convert("RGBA")

    mode = spec.get("mode") or "on_poster"
    if mode == "on_page":
        orientation = resolve_page_orientation(spec, poster.width, poster.height)
        page_size = a4_pixel_size(orientation, spec.get("page_dpi") or 150)
        canvas = fit_poster_on_page(poster, page_size, spec.get("poster_margin") or 0.06).convert(
            "RGBA"
        )
    else:
        canvas = poster.copy()

    _draw_elements(canvas, fields, spec.get("elements") or [], warnings)
    return canvas.convert("RGB"), warnings, spec


def compose_to_file(src, dest, spec=None, fields=None, quality=92):
    composed, warnings, spec = compose_poster(src, fields=fields, spec=spec)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    ext = dest.suffix.lower()
    if ext in {".jpg", ".jpeg"}:
        composed = composed.convert("RGB")
        composed.save(dest, quality=quality)
    elif ext == ".png":
        composed.save(dest)
    else:
        dest = dest.with_suffix(".jpg")
        composed.convert("RGB").save(dest, quality=quality)
    return str(dest), warnings, spec


def _self_check():
    assert PIL_AVAILABLE
    img = Image.new("RGB", (200, 300), (40, 40, 40))
    fields = {
        "title": "Show",
        "date": "2026-08-17",
        "time": "20:00",
        "location": "Test",
        "qr_url": "https://example.com",
    }
    spec = default_overlay_spec(mode="on_poster")
    for el in spec["elements"]:
        if el["id"] in ("title", "date"):
            el["enabled"] = True
            el["value"] = fields[el["id"]]
    path = os.path.join(tempfile.gettempdir(), "overlay_engine_selfcheck.png")
    img.save(path)
    out, warnings, _spec = compose_poster(path, fields=fields, spec=spec)
    assert out.size[0] > 0 and out.size[1] > 0
    dest = os.path.join(tempfile.gettempdir(), "overlay_engine_out.jpg")
    written, _, _ = compose_to_file(path, dest, spec=spec, fields=fields)
    assert os.path.isfile(written)
    packed = [dict(el) for el in spec["elements"] if el["id"] in ("date", "time")]
    for el in packed:
        el["value"] = fields.get(el["id"], "x")
        el["enabled"] = True
    pack_elements_at_corner(packed, "bottom_left", fields, 1000, 1400)
    assert packed[0]["y"] == packed[1]["y"]
    ok, name = save_layout("_selfcheck_layout", spec)
    assert ok and name in list_layouts()
    ok, _ = delete_layout("_selfcheck_layout")
    assert ok
    ok, pname = save_field_preset("_selfcheck_fields", fields)
    assert ok and pname in list_field_presets()
    ok, _ = delete_field_preset("_selfcheck_fields")
    assert ok
    for p in (path, written):
        try:
            os.remove(p)
        except OSError:
            pass
    print("overlay_engine self-check OK")


if __name__ == "__main__":
    _self_check()
