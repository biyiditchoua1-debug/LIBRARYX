"""
Core flyer and searchable PDF generation engine.
Uses Pillow for high-precision live image rendering/previews and ReportLab
for native vector PDF generation (enabling full text search on all devices).
"""

import io
import datetime
from pathlib import Path
import re
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps

from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.pdfbase.pdfmetrics import registerFont, stringWidth
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.utils import ImageReader

ASSETS_DIR = Path(__file__).resolve().parent.parent / 'libraryx' / 'assets'
FONTS_DIR  = ASSETS_DIR / 'fonts'

# ── Font Registration for ReportLab ──────────────────────────────────────────

_REPORTLAB_FONTS_REGISTERED = False

def _register_reportlab_fonts():
    global _REPORTLAB_FONTS_REGISTERED
    if _REPORTLAB_FONTS_REGISTERED:
        return
    fonts_to_register = [
        ("Poppins-Bold", "Poppins-Bold.ttf"),
        ("Poppins-BoldItalic", "Poppins-BoldItalic.ttf"),
        ("Poppins-ExtraBold", "Poppins-ExtraBold.ttf"),
        ("Poppins-ExtraBoldItalic", "Poppins-ExtraBoldItalic.ttf"),
        ("Poppins-Medium", "Poppins-Medium.ttf"),
        ("Poppins-MediumItalic", "Poppins-MediumItalic.ttf"),
        ("Poppins-SemiBold", "Poppins-SemiBold.ttf"),
        ("Poppins-SemiBoldItalic", "Poppins-SemiBoldItalic.ttf"),
        ("BassyRegular", "BassyRegular.ttf"),
    ]
    for font_name, filename in fonts_to_register:
        path = FONTS_DIR / filename
        if path.exists():
            try:
                registerFont(TTFont(font_name, str(path)))
            except Exception:
                pass
    _REPORTLAB_FONTS_REGISTERED = True


# ── PSD-exact layer bboxes (left, top, right, bottom) ─────────────────────────

PHOTO_BBOX        = (68, 403, 598, 933)
PHOTO_CORNER_R    = 28

NAME_BBOX   = (675, 560, 1030, 660)
NAME_FONT   = "Poppins-ExtraBold.ttf"
NAME_SIZE   = 50
NAME_COLOR  = (255, 255, 255, 255)
NAME_TRACK  = -1

THEME_BBOX  = (102, 1050, 992, 1131)
THEME_FONT  = "Poppins-SemiBold.ttf"
THEME_SIZE  = 42
THEME_COLOR = (255, 255, 255, 255)

ACAD_BBOX   = (69, 1345, 365, 1410)
ACAD_FONT   = "Poppins-BoldItalic.ttf"
ACAD_SIZE   = 23
ACAD_COLOR  = (255, 255, 255, 255)
ACAD_ALIGN  = "left"

PROF_BBOX   = (747, 1345, 1058, 1410)
PROF_FONT   = "Poppins-BoldItalic.ttf"
PROF_SIZE   = 23
PROF_COLOR  = (255, 255, 255, 255)
PROF_ALIGN  = "left"

DATE_DAY_BBOX      = (209, 1207, 304, 1283)
DATE_MONTH_BBOX    = (309, 1217, 355, 1273)
TIME_HOUR_BBOX     = (522, 1203, 615, 1279)
TIME_SUFFIX_Y      = (1218, 1264)
TIME_CONTENT_RIGHT = 672
TIME_TEXT_GAP      = 10
CLASS_VALUE_BBOX   = (838, 1208, 960, 1281)
CARD_VALUE_SIZE    = 75
CARD_SUFFIX_SIZE   = 24


# ── Font helpers ───────────────────────────────────────────────────────────────

def _load_font(filename: str, size: int) -> ImageFont.FreeTypeFont:
    path = FONTS_DIR / filename
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font) -> tuple:
    """Return (width, height) of rendered text using Pillow textbbox."""
    bb = draw.textbbox((0, 0), text, font=font)
    return bb[2] - bb[0], bb[3] - bb[1]


# ── Tracking (letter-spacing) ──────────────────────────────────────────────────

def _draw_tracked_text(draw, x, y, text, font, color, tracking_px=0):
    if tracking_px == 0:
        draw.text((x, y), text, font=font, fill=color)
        return
    cx = x
    for ch in text:
        draw.text((cx, y), ch, font=font, fill=color)
        ch_bb = draw.textbbox((0, 0), ch, font=font)
        cx += (ch_bb[2] - ch_bb[0]) + tracking_px


def _tracked_text_width(draw, text, font, tracking_px=0):
    if not text:
        return 0
    total = 0
    for i, ch in enumerate(text):
        bb = draw.textbbox((0, 0), ch, font=font)
        total += (bb[2] - bb[0])
        if i < len(text) - 1:
            total += tracking_px
    return total


# ── Auto-fit + draw text centred in bbox ──────────────────────────────────────

def _draw_centered(draw, text, font_file, start_size, color, bbox,
                   align="center", tracking_px=0, wrap=True):
    left, top, right, bottom = bbox
    box_w = right - left
    box_h = bottom - top
    min_size = 8

    for pt in range(start_size, min_size - 1, -1):
        font = _load_font(font_file, pt)

        ref_bb = draw.textbbox((0, 0), "Ágj", font=font)
        line_h = ref_bb[3] - ref_bb[1]
        line_gap = max(2, int(line_h * 0.20))
        line_stride = line_h + line_gap

        if wrap:
            words = text.split()
            lines, cur = [], ""
            for word in words:
                test = (cur + " " + word).strip()
                tw = _tracked_text_width(draw, test, font, tracking_px)
                if tw <= box_w:
                    cur = test
                else:
                    if cur:
                        lines.append(cur)
                    cur = word
            if cur:
                lines.append(cur)
            if not lines:
                lines = [text]
        else:
            lines = [text]

        total_h = line_h + (len(lines) - 1) * line_stride
        all_fit = (total_h <= box_h and
                   all(_tracked_text_width(draw, l, font, tracking_px) <= box_w
                       for l in lines))
        if all_fit:
            break
    else:
        font = _load_font(font_file, min_size)
        ref_bb = draw.textbbox((0, 0), "Ágj", font=font)
        line_h = ref_bb[3] - ref_bb[1]
        line_gap = max(2, int(line_h * 0.20))
        line_stride = line_h + line_gap
        lines = [text]
        total_h = line_h

    start_y = top + (box_h - total_h) // 2

    for i, line in enumerate(lines):
        lw = _tracked_text_width(draw, line, font, tracking_px)
        if align == "center":
            x = left + (box_w - lw) // 2
        elif align == "right":
            x = right - lw
        else:
            x = left
        y = start_y + i * line_stride
        _draw_tracked_text(draw, x, y, line, font, color, tracking_px)


def _draw_badge_value(draw, text, font_file, start_size, color, bbox,
                      align="center", tracking_px=0):
    """Fit a single badge value by its actual glyph bounds and draw vertically centered."""
    if not text:
        return 0

    left, top, right, bottom = bbox
    box_w, box_h = right - left, bottom - top
    min_size = 8
    for pt in range(start_size, min_size - 1, -1):
        font = _load_font(font_file, pt)
        glyph_bbox = draw.textbbox((0, 0), text, font=font)
        text_w = _tracked_text_width(draw, text, font, tracking_px)
        text_h = glyph_bbox[3] - glyph_bbox[1]
        if text_w <= box_w and text_h <= box_h:
            break
    else:
        font = _load_font(font_file, min_size)
        glyph_bbox = draw.textbbox((0, 0), text, font=font)
        text_w = _tracked_text_width(draw, text, font, tracking_px)
        text_h = glyph_bbox[3] - glyph_bbox[1]

    if align == "center":
        x = left + (box_w - text_w) // 2
    elif align == "right":
        x = right - text_w
    else:
        x = left
    y = top + (box_h - text_h) // 2 - glyph_bbox[1]
    _draw_tracked_text(draw, x, y, text, font, color, tracking_px)
    return text_w


# ── Photo with rounded corners ─────────────────────────────────────────────────

def _rounded_mask(size: tuple, radius: int) -> Image.Image:
    w, h = size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    return mask


def _paste_photo(img: Image.Image, photo_source, bbox, corner_radius: int, photo_crop=None):
    photo_left, photo_top, right, bottom = bbox
    target_w = right - photo_left
    target_h = bottom - photo_top

    if photo_source is None:
        return

    if hasattr(photo_source, 'read'):
        photo_source.seek(0)
    photo = ImageOps.exif_transpose(Image.open(photo_source)).convert("RGBA")
    src_w, src_h = photo.size

    target_ratio = target_w / target_h
    source_ratio = src_w / src_h
    if source_ratio > target_ratio:
        crop_w, crop_h = src_h * target_ratio, src_h
    else:
        crop_w, crop_h = src_w, src_w / target_ratio

    photo_crop = photo_crop or {}
    zoom = min(3, max(1, float(photo_crop.get('zoom', 1))))
    crop_w /= zoom
    crop_h /= zoom
    center_x = min(src_w - crop_w / 2, max(crop_w / 2, float(photo_crop.get('cx', 0.5)) * src_w))
    center_y = min(src_h - crop_h / 2, max(crop_h / 2, float(photo_crop.get('cy', 0.5)) * src_h))
    crop_left = center_x - crop_w / 2
    crop_top = center_y - crop_h / 2
    photo = photo.crop((round(crop_left), round(crop_top), round(crop_left + crop_w), round(crop_top + crop_h)))
    photo = photo.resize((target_w, target_h), Image.LANCZOS)

    mask = _rounded_mask((target_w, target_h), corner_radius)
    photo.putalpha(mask)

    img.paste(photo, (photo_left, photo_top), photo)


# ── Public API ─────────────────────────────────────────────────────────────────

def format_supervisor_name(name: str) -> str:
    if not name:
        return '--'
    name_str = name.strip()
    if not name_str:
        return '--'
    words = name_str.split()
    if not words:
        return '--'
    
    titles = {
        'mr', 'mister', 'mrs', 'ms', 'miss', 'dr', 'doctor', 'docteur', 'pr', 'prof', 
        'professor', 'professeur', 'm', 'mme', 'mlle', 'ing', 'ingenieur', 'engineer',
        'monsieur', 'madame', 'mademoiselle'
    }
    
    first_word = words[0]
    normalized_first = first_word.lower().rstrip('.')
    
    if normalized_first in titles:
        formatted_first = first_word.title()
        rest = [w.upper() for w in words[1:]]
        return " ".join([formatted_first] + rest)
    else:
        return name_str.upper()


def split_day_month(value: str) -> tuple[str, str]:
    """Return a large day and small '/month' string for the PSD date badge."""
    value = (value or '').strip()
    if not value:
        return '', ''

    match = re.fullmatch(r'(\d{1,2})\s*/\s*(\d{1,2})', value)
    if not match:
        raise ValueError('La date doit être au format jour/mois, par exemple 9/5.')

    day_text, month_text = match.groups()
    try:
        datetime.date(2000, int(month_text), int(day_text))
    except ValueError as exc:
        raise ValueError('La date saisie est invalide.') from exc
    return day_text.zfill(2), f'/{month_text.zfill(2)}'


def split_time(value: str) -> tuple[str, str]:
    """Return a large hour and small 'Hminutes' string for the PSD time badge."""
    value = (value or '').strip()
    if not value:
        return '', ''

    match = re.fullmatch(r'(\d{1,2})\s*[:hH]\s*(\d{2})', value)
    if not match:
        raise ValueError('L’heure doit être au format 8:30 ou 11H30.')

    hour_text, minute_text = match.groups()
    hour, minute = int(hour_text), int(minute_text)
    if hour > 23 or minute > 59:
        raise ValueError('L’heure saisie est invalide.')
    return f'{hour:02d}', f'H{minute:02d}'


def generate_flyer_image(form_data: dict, photo_file=None, render_text=True, photo_crop=None) -> Image.Image:
    """
    Compose the flyer onto the PNG template using PSD-exact coordinates.
    Returns a 1080 × 1516 RGBA PIL Image.
    If render_text=False, skips drawing text onto bitmap canvas (used for PDF vector rendering).
    """
    filiere = str(form_data.get('filiere', 'SR')).strip().upper()
    niveau = str(form_data.get('niveau', 'N2')).strip().upper()
    if filiere not in {'GL', 'SE', 'SR'}:
        filiere = 'SR'
    if niveau not in {'N2', 'N3'}:
        niveau = 'N2'

    template_choice = str(form_data.get('template_choice', '')).strip().upper()
    if template_choice in {'GL-N2', 'GL-N3', 'SE-N2', 'SE-N3', 'SR-N2', 'SR-N3'}:
        filiere, niveau = template_choice.split('-', 1)
    elif template_choice in {'GL', 'SE', 'SR'}:
        filiere = template_choice

    template_files = {
        ('GL', 'N2'): 'GL-N2.png',
        ('GL', 'N3'): 'GL-N3.png',
        ('SE', 'N2'): 'SE - N2.png',
        ('SE', 'N3'): 'SE - N3.png',
        ('SR', 'N2'): 'SR - N2.png',
        ('SR', 'N3'): 'SR - N3.png',
    }
    template_filename = template_files[(filiere, niveau)]

    template_path = ASSETS_DIR / 'templates' / template_filename
    img = Image.open(template_path).convert("RGBA")

    # 1. Photo — paste BEFORE text so frame decorations stay on top
    if photo_file:
        _paste_photo(img, photo_file, PHOTO_BBOX, PHOTO_CORNER_R, photo_crop=photo_crop)

    if not render_text:
        return img

    draw = ImageDraw.Draw(img)

    # 2. Full name
    raw_name = (form_data.get('full_name') or '').strip()
    display_name = raw_name.upper() if raw_name else '--'
    _draw_centered(draw, display_name, NAME_FONT, NAME_SIZE,
                   NAME_COLOR, NAME_BBOX, align='center', tracking_px=NAME_TRACK, wrap=False)

    # 3. Theme — sentence case
    raw_theme = (form_data.get('theme') or '').strip()
    display_theme = (raw_theme[0].upper() + raw_theme[1:].lower()) if raw_theme else '--'
    _draw_centered(draw, display_theme, THEME_FONT, THEME_SIZE,
                   THEME_COLOR, THEME_BBOX, align='center')

    # 4. Academic supervisor
    raw_acad = (form_data.get('academic_supervisor') or '').strip()
    display_acad = format_supervisor_name(raw_acad)
    _draw_centered(draw, display_acad, ACAD_FONT, ACAD_SIZE,
                   ACAD_COLOR, ACAD_BBOX, align=ACAD_ALIGN)

    # 5. Professional supervisor
    raw_prof = (form_data.get('professional_supervisor') or '').strip()
    display_prof = format_supervisor_name(raw_prof)
    _draw_centered(draw, display_prof, PROF_FONT, PROF_SIZE,
                   PROF_COLOR, PROF_BBOX, align=PROF_ALIGN)

    # PSD date, time and class badges. Values use the same Poppins ExtraBold
    # face as the candidate name; the slash/month and H/minutes stay smaller.
    date_day, date_month = split_day_month(form_data.get('soutenance_date', ''))
    if date_day:
        _draw_badge_value(draw, date_day, NAME_FONT, CARD_VALUE_SIZE,
                          NAME_COLOR, DATE_DAY_BBOX, align='right',
                          tracking_px=NAME_TRACK)
        _draw_badge_value(draw, date_month, NAME_FONT, CARD_SUFFIX_SIZE,
                          NAME_COLOR, DATE_MONTH_BBOX, tracking_px=NAME_TRACK)

    time_hour, time_suffix = split_time(form_data.get('soutenance_time', ''))
    if time_hour:
        time_hour_width = _draw_badge_value(
            draw, time_hour, NAME_FONT, CARD_VALUE_SIZE, NAME_COLOR,
            TIME_HOUR_BBOX, align='left', tracking_px=NAME_TRACK,
        )
        suffix_left = TIME_HOUR_BBOX[0] + time_hour_width + TIME_TEXT_GAP
        time_suffix_bbox = (
            suffix_left, TIME_SUFFIX_Y[0], TIME_CONTENT_RIGHT, TIME_SUFFIX_Y[1]
        )
        _draw_badge_value(draw, time_suffix, NAME_FONT, CARD_SUFFIX_SIZE,
                          NAME_COLOR, time_suffix_bbox, align='left',
                          tracking_px=NAME_TRACK)

    display_class = (form_data.get('classe') or '').strip().upper()
    if display_class:
        _draw_badge_value(draw, display_class, NAME_FONT, CARD_VALUE_SIZE,
                          NAME_COLOR, CLASS_VALUE_BBOX, align='left',
                          tracking_px=NAME_TRACK)

    return img


def generate_flyer_preview_bytes(form_data: dict, photo_file=None, photo_crop=None) -> bytes:
    """Return a low-resolution, watermarked JPEG used only by the live preview."""
    img = generate_flyer_image(form_data, photo_file, render_text=True, photo_crop=photo_crop)
    pw = 540
    ph = int(img.height * pw / img.width)
    preview = img.resize((pw, ph), Image.LANCZOS).convert('RGBA')

    # Keep the preview visibly distinct from the paid, clean download. Burn the
    # watermark into the pixels so it remains when the preview is screen-captured.
    watermark_layer = Image.new('RGBA', (pw * 2, ph * 2), (0, 0, 0, 0))
    watermark_draw = ImageDraw.Draw(watermark_layer)
    watermark_font = ImageFont.truetype(str(FONTS_DIR / 'Poppins-Bold.ttf'), 19)
    watermark_text = 'APERÇU · NON VALABLE'
    step_y = 340
    for row, y in enumerate(range(0, ph * 2, step_y)):
        x_offset = 0 if row % 2 == 0 else -170
        for x in range(x_offset, pw * 2, 600):
            watermark_draw.text(
                (x, y),
                watermark_text,
                font=watermark_font,
                fill=(255, 255, 255, 66),
                stroke_width=1,
                stroke_fill=(15, 23, 42, 68),
            )
    watermark_layer = watermark_layer.rotate(28, resample=Image.BICUBIC, expand=False)
    crop_left = (watermark_layer.width - pw) // 2
    crop_top = (watermark_layer.height - ph) // 2
    watermark_layer = watermark_layer.crop((crop_left, crop_top, crop_left + pw, crop_top + ph))
    preview = Image.alpha_composite(preview, watermark_layer).convert('RGB')

    buf = io.BytesIO()
    preview.save(buf, 'JPEG', quality=82)
    buf.seek(0)
    return buf.getvalue()


def generate_flyer_pdf_bytes(form_data: dict, photo_file=None, photo_crop=None) -> bytes:
    """
    Return vector A4 PDF of flyer with native searchable text streams (Ctrl+F compatible).
    Uses ReportLab canvas overlaying registered Poppins text on top of flyer background.
    """
    _register_reportlab_fonts()

    bg_img = generate_flyer_image(form_data, photo_file, render_text=False, photo_crop=photo_crop)

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    page_w, page_h = A4  # 595.27, 841.89 pt

    # Draw background template + candidate photo
    c.drawImage(ImageReader(bg_img), 0, 0, width=page_w, height=page_h)

    # Scaling metrics from PSD 1080 x 1516 px -> PDF A4 595.27 x 841.89 pt
    sx = page_w / 1080.0
    sy = page_h / 1516.0

    # 1. Full name
    raw_name = (form_data.get('full_name') or '').strip()
    display_name = raw_name.upper() if raw_name else '--'
    name_cx = (NAME_BBOX[0] + NAME_BBOX[2]) / 2.0 * sx
    name_cy = page_h - ((NAME_BBOX[1] + NAME_BBOX[3]) / 2.0 * sy) - (4.0 * sy)
    f_name = "Poppins-ExtraBold" if _REPORTLAB_FONTS_REGISTERED else "Helvetica-Bold"
    c.setFont(f_name, NAME_SIZE * sy * 0.95)
    c.setFillColor(colors.HexColor('#FFFFFF'))
    c.drawCentredString(name_cx, name_cy, display_name)

    # 2. Theme
    raw_theme = (form_data.get('theme') or '').strip()
    display_theme = (raw_theme[0].upper() + raw_theme[1:].lower()) if raw_theme else '--'
    theme_cx = (THEME_BBOX[0] + THEME_BBOX[2]) / 2.0 * sx
    theme_cy = page_h - ((THEME_BBOX[1] + THEME_BBOX[3]) / 2.0 * sy) - (4.0 * sy)
    f_theme = "Poppins-SemiBold" if _REPORTLAB_FONTS_REGISTERED else "Helvetica"
    font_sz = THEME_SIZE * sy * 0.95
    c.setFont(f_theme, font_sz)
    c.setFillColor(colors.HexColor('#FFFFFF'))

    theme_box_w = (THEME_BBOX[2] - THEME_BBOX[0]) * sx
    words = display_theme.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        if stringWidth(test, f_theme, font_sz) <= theme_box_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    if not lines:
        lines = [display_theme]

    line_h = font_sz * 1.25
    start_y = theme_cy + ((len(lines) - 1) * line_h / 2.0)
    for i, line in enumerate(lines):
        c.drawCentredString(theme_cx, start_y - (i * line_h), line)

    # 3. Academic supervisor
    raw_acad = (form_data.get('academic_supervisor') or '').strip()
    display_acad = format_supervisor_name(raw_acad)
    acad_x = ACAD_BBOX[0] * sx
    acad_cy = page_h - ((ACAD_BBOX[1] + ACAD_BBOX[3]) / 2.0 * sy) - (2.0 * sy)
    f_acad = "Poppins-BoldItalic" if _REPORTLAB_FONTS_REGISTERED else "Helvetica-BoldOblique"
    c.setFont(f_acad, ACAD_SIZE * sy)
    c.setFillColor(colors.HexColor('#FFFFFF'))
    c.drawString(acad_x, acad_cy, display_acad)

    # 4. Professional supervisor
    raw_prof = (form_data.get('professional_supervisor') or '').strip()
    display_prof = format_supervisor_name(raw_prof)
    prof_x = PROF_BBOX[0] * sx
    prof_cy = page_h - ((PROF_BBOX[1] + PROF_BBOX[3]) / 2.0 * sy) - (2.0 * sy)
    f_prof = "Poppins-BoldItalic" if _REPORTLAB_FONTS_REGISTERED else "Helvetica-BoldOblique"
    c.setFont(f_prof, PROF_SIZE * sy)
    c.setFillColor(colors.HexColor('#FFFFFF'))
    c.drawString(prof_x, prof_cy, display_prof)

    c.showPage()
    c.save()
    buf.seek(0)
    return buf.getvalue()
