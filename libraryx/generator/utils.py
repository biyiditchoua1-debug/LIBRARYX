"""
Core flyer and searchable PDF generation engine.
Uses Pillow for high-precision live image rendering/previews and ReportLab
for native vector PDF generation (enabling full text search on all devices).
"""

import io
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter

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


# ── Photo with rounded corners ─────────────────────────────────────────────────

def _rounded_mask(size: tuple, radius: int) -> Image.Image:
    w, h = size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    return mask


def _paste_photo(img: Image.Image, photo_source, bbox, corner_radius: int):
    left, top, right, bottom = bbox
    target_w = right - left
    target_h = bottom - top

    if photo_source is None:
        return

    if hasattr(photo_source, 'read'):
        photo_source.seek(0)
    photo = Image.open(photo_source).convert("RGBA")
    src_w, src_h = photo.size

    scale = max(target_w / src_w, target_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    photo = photo.resize((new_w, new_h), Image.LANCZOS)

    cx = (new_w - target_w) // 2
    cy = (new_h - target_h) // 2
    photo = photo.crop((cx, cy, cx + target_w, cy + target_h))

    mask = _rounded_mask((target_w, target_h), corner_radius)
    photo.putalpha(mask)

    img.paste(photo, (left, top), photo)


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


def generate_flyer_image(form_data: dict, photo_file=None, render_text=True) -> Image.Image:
    """
    Compose the flyer onto the PNG template using PSD-exact coordinates.
    Returns a 1080 × 1516 RGBA PIL Image.
    If render_text=False, skips drawing text onto bitmap canvas (used for PDF vector rendering).
    """
    filiere = form_data.get('filiere', 'SR').upper()
    template_choice = form_data.get('template_choice', '').strip().upper()
    
    TEMPLATE_MAP = {
        'GL': 'GL-N3.png',
        'SE': 'SE - N3.png',
        'SR': 'SR - N3.png',
    }

    EXPLICIT_TEMPLATE_MAP = {
        'GL': 'GL-N3.png',
        'SE': 'SE - N3.png',
        'SR': 'SR - N3.png',
        'GL-N3': 'GL-N3.png',
        'SE-N3': 'SE - N3.png',
        'SR-N3': 'SR - N3.png',
    }
    
    if template_choice in EXPLICIT_TEMPLATE_MAP:
        template_filename = EXPLICIT_TEMPLATE_MAP[template_choice]
    else:
        template_filename = TEMPLATE_MAP.get(filiere, 'SR - N3.png')

    template_path = ASSETS_DIR / 'templates' / template_filename
    img = Image.open(template_path).convert("RGBA")

    # 1. Photo — paste BEFORE text so frame decorations stay on top
    if photo_file:
        _paste_photo(img, photo_file, PHOTO_BBOX, PHOTO_CORNER_R)

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

    return img


def generate_flyer_preview_bytes(form_data: dict, photo_file=None) -> bytes:
    """Return JPEG bytes at half-size for fast live preview."""
    img = generate_flyer_image(form_data, photo_file, render_text=True)
    pw = 540
    ph = int(img.height * pw / img.width)
    buf = io.BytesIO()
    img.resize((pw, ph), Image.LANCZOS).convert('RGB').save(buf, 'JPEG', quality=85)
    buf.seek(0)
    return buf.getvalue()


def generate_flyer_pdf_bytes(form_data: dict, photo_file=None) -> bytes:
    """
    Return vector A4 PDF of flyer with native searchable text streams (Ctrl+F compatible).
    Uses ReportLab canvas overlaying registered Poppins text on top of flyer background.
    """
    _register_reportlab_fonts()

    bg_img = generate_flyer_image(form_data, photo_file, render_text=False)

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



