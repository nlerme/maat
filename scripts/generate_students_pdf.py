#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

ACADEMIC_YEAR = "2025-2026"
ADMIN_OUTPUT_FILENAME = "students_tokens_admin.pdf"
CARDS_OUTPUT_FILENAME = "students_tokens_cards.pdf"
COURSE_SUPPORTS_URL = "https://nicolaslerme.fr/"
EMOJI_PNG_SIZE = 160
EMOJI_RENDER_FONT_SIZE = 109


def unwrap(value: Any, lang: str = "fr") -> Any:
    if isinstance(value, dict):
        preferred = f"value_{lang}"
        if preferred in value:
            return value[preferred]
        if "value" in value:
            inner = value["value"]
            if isinstance(inner, dict):
                if lang in inner:
                    return inner[lang]
                for fallback_lang in ("fr", "en"):
                    if fallback_lang in inner:
                        return inner[fallback_lang]
            return inner
        if "value_fr" in value:
            return value["value_fr"]
        if "value_en" in value:
            return value["value_en"]
    return value


def default_language(cfg: dict[str, Any]) -> str:
    value = unwrap(cfg.get("interface", {}).get("language", "fr"))
    return "en" if str(value).lower().startswith("en") else "fr"


def config_value(cfg: dict[str, Any], section: str, key: str, default: str = "", lang: str | None = None) -> Any:
    selected_lang = lang or default_language(cfg)
    translations = cfg.get("translations", {}) if isinstance(cfg.get("translations"), dict) else {}
    for candidate in (selected_lang, "fr", "en"):
        block = translations.get(candidate)
        if isinstance(block, dict):
            section_block = block.get(section)
            if isinstance(section_block, dict) and key in section_block:
                return section_block[key]
    return unwrap(cfg.get(section, {}).get(key, default), selected_lang)


def resolve(root: Path, path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (root / path).resolve()


def find_font(name: str) -> Path | None:
    candidates = [
        Path("/usr/share/fonts/truetype/dejavu") / name,
        Path("/usr/share/fonts/dejavu") / name,
        Path("/usr/local/share/fonts") / name,
        Path.home() / ".fonts" / name,
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def find_color_emoji_font() -> Path | None:
    candidates = [
        Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
        Path("/usr/share/fonts/noto/NotoColorEmoji.ttf"),
        Path("/usr/local/share/fonts/NotoColorEmoji.ttf"),
        Path.home() / ".fonts" / "NotoColorEmoji.ttf",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def register_fonts() -> tuple[str, str]:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    regular = find_font("DejaVuSans.ttf")
    bold = find_font("DejaVuSans-Bold.ttf")
    if regular is not None:
        pdfmetrics.registerFont(TTFont("MAAT-Regular", str(regular)))
        regular_name = "MAAT-Regular"
    else:
        regular_name = "Helvetica"
    if bold is not None:
        pdfmetrics.registerFont(TTFont("MAAT-Bold", str(bold)))
        bold_name = "MAAT-Bold"
    else:
        bold_name = "Helvetica-Bold"
    return regular_name, bold_name


def shorten(text: str, font_name: str, font_size: float, max_width: float) -> str:
    from reportlab.pdfbase import pdfmetrics

    text = text or ""
    if pdfmetrics.stringWidth(text, font_name, font_size) <= max_width:
        return text
    suffix = "..."
    available = max_width - pdfmetrics.stringWidth(suffix, font_name, font_size)
    if available <= 0:
        return suffix
    result = ""
    for char in text:
        if pdfmetrics.stringWidth(result + char, font_name, font_size) > available:
            break
        result += char
    return result + suffix


def emoji_asset_name(emoji_text: str) -> str:
    return "emoji_" + "-".join(f"{ord(char):x}" for char in emoji_text) + ".png"


def bundled_emoji_asset(root: Path, emoji_text: str) -> Path | None:
    path = root / "assets" / "emoji" / emoji_asset_name(emoji_text)
    return path if path.exists() else None


def render_emoji_asset(root: Path, emoji_text: str) -> Path | None:
    """Render a color emoji to a cached PNG when the bundled asset is missing.

    ReportLab/TrueType fonts cannot reliably embed color emoji glyphs in PDF files.
    The PDF table therefore draws emoji as PNG images.  The bundle ships assets for
    the generated symbol list; this fallback only covers manually edited CSV files.
    """

    font_path = find_color_emoji_font()
    if font_path is None:
        return None
    try:
        from PIL import Image, ImageDraw, ImageFont
    except Exception:
        return None
    try:
        font = ImageFont.truetype(str(font_path), EMOJI_RENDER_FONT_SIZE)
    except Exception:
        return None

    cache_dir = root / ".install-cache" / "emoji-cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_path = cache_dir / emoji_asset_name(emoji_text)
    if output_path.exists():
        return output_path

    image = Image.new("RGBA", (EMOJI_PNG_SIZE, EMOJI_PNG_SIZE), (255, 255, 255, 0))
    draw = ImageDraw.Draw(image)
    draw.text((16, 16), emoji_text, font=font, embedded_color=True)
    bbox = image.getbbox()
    if bbox is None:
        return None
    cropped = image.crop(bbox)
    canvas = Image.new("RGBA", (EMOJI_PNG_SIZE, EMOJI_PNG_SIZE), (255, 255, 255, 0))
    cropped.thumbnail((EMOJI_PNG_SIZE - 16, EMOJI_PNG_SIZE - 16), Image.Resampling.LANCZOS)
    canvas.alpha_composite(cropped, ((EMOJI_PNG_SIZE - cropped.width) // 2, (EMOJI_PNG_SIZE - cropped.height) // 2))
    canvas.save(output_path)
    return output_path


def emoji_image_path(root: Path, emoji_text: str) -> Path | None:
    if not emoji_text:
        return None
    bundled = bundled_emoji_asset(root, emoji_text)
    if bundled is not None:
        return bundled
    return render_emoji_asset(root, emoji_text)


def draw_centered(c, text: str, y: float, font_name: str, font_size: float, page_width: float) -> None:
    c.setFont(font_name, font_size)
    c.drawCentredString(page_width / 2.0, y, text)


def draw_group_page(
    c,
    root: Path,
    group: str,
    rows: list[dict[str, str]],
    title_lines: list[str],
    fonts: tuple[str, str],
) -> None:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader

    regular_font, bold_font = fonts
    page_width, page_height = A4
    top = page_height - 34.0

    draw_centered(c, title_lines[0], top, bold_font, 13.0, page_width)
    draw_centered(c, title_lines[1], top - 18.0, regular_font, 11.0, page_width)
    draw_centered(c, title_lines[2], top - 34.0, regular_font, 11.0, page_width)

    table_top = top - 70.0
    table_bottom = 42.0
    columns = ["Groupe", "Prénom", "Nom", "Token", "Symbole"]
    keys = ["group", "first_name", "last_name", "token", "animal"]
    widths = [58.0, 112.0, 126.0, 124.0, 118.0]
    table_width = sum(widths)
    left = (page_width - table_width) / 2.0

    row_count = max(1, len(rows) + 1)
    row_height = (table_top - table_bottom) / row_count
    row_height = min(18.0, row_height)
    font_size = max(5.0, min(9.5, row_height * 0.55))
    header_font_size = max(5.5, min(9.8, font_size + 0.4))
    y = table_top

    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)

    def draw_animal_value(animal_text: str, x: float, y_top: float, width: float) -> bool:
        image_path = emoji_image_path(root, animal_text)
        if image_path is None:
            return False
        try:
            image = ImageReader(str(image_path))
            size = min(row_height - 3.0, width - 8.0)
            c.drawImage(
                image,
                x + (width - size) / 2.0,
                y_top - row_height + (row_height - size) / 2.0,
                width=size,
                height=size,
                mask="auto",
                preserveAspectRatio=True,
                anchor="c",
            )
            return True
        except Exception:
            return False

    def draw_row(values: list[str], y_top: float, is_header: bool = False) -> None:
        x = left
        c.setFont(bold_font if is_header else regular_font, header_font_size if is_header else font_size)
        if is_header:
            c.setFillColor(colors.lightgrey)
            c.rect(left, y_top - row_height, table_width, row_height, stroke=0, fill=1)
            c.setFillColor(colors.black)
        for col_index, (value, width) in enumerate(zip(values, widths)):
            c.rect(x, y_top - row_height, width, row_height, stroke=1, fill=0)
            text_y = y_top - row_height + max(2.0, (row_height - font_size) / 2.0)
            if not is_header and col_index == len(widths) - 1 and draw_animal_value(value, x, y_top, width):
                x += width
                continue
            display = shorten(value, bold_font if is_header else regular_font, header_font_size if is_header else font_size, width - 8.0)
            c.drawString(x + 4.0, text_y, display)
            x += width

    draw_row(columns, y, True)
    y -= row_height
    for row in rows:
        values = [row.get(key, "") for key in keys]
        if not values[-1]:
            values[-1] = row.get("animal_entity", "")
        draw_row(values, y, False)
        y -= row_height

    if not rows:
        c.setFont(regular_font, 10.0)
        c.drawCentredString(page_width / 2.0, table_top - 2.0 * row_height, f"Aucun étudiant pour le groupe {group}.")



def draw_centered_in_box(c, text: str, x: float, y: float, width: float, font_name: str, font_size: float) -> None:
    c.setFont(font_name, font_size)
    c.drawCentredString(x + width / 2.0, y, shorten(text, font_name, font_size, width - 12.0))


def load_rows(csv_path: Path) -> list[dict[str, str]]:
    if not csv_path.exists():
        return []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    rows.sort(key=lambda r: (r.get("group", ""), r.get("last_name", ""), r.get("first_name", "")))
    return rows


def display_value(cfg: dict[str, Any], key: str, fallback: str = "") -> str:
    if key in cfg:
        return str(cfg.get(key) or fallback)
    if "." in key:
        section, name = key.split(".", 1)
        return str(config_value(cfg, section, name, fallback))
    return fallback


def make_title_lines(cfg: dict[str, Any]) -> list[str]:
    return [
        f"{display_value(cfg, 'app_title', 'MAAT')} - {display_value(cfg, 'school_name')}",
        f"{display_value(cfg, 'course_name')} - {display_value(cfg, 'student_level')}",
        ACADEMIC_YEAR,
    ]


def natural_group_key(value: str) -> list[Any]:
    import re
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", (value or "").casefold())]


def make_groups(cfg: dict[str, Any], rows_by_group: dict[str, list[dict[str, str]]]) -> list[str]:
    groups = sorted((g for g in rows_by_group if g), key=natural_group_key)
    return groups or ["Groupe"]


def generate_admin_pdf(root: Path, cfg: dict[str, Any], rows: list[dict[str, str]], output_path: Path) -> None:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4

    rows_by_group: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        rows_by_group[row.get("group", "")].append(row)
    for group_rows in rows_by_group.values():
        group_rows.sort(key=lambda r: (r.get("last_name", ""), r.get("first_name", "")))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    title_lines = make_title_lines(cfg)
    groups = make_groups(cfg, rows_by_group)
    fonts = register_fonts()
    c = canvas.Canvas(str(output_path), pagesize=A4)
    c.setTitle("MAAT - étudiants et tokens - enseignant")
    c.setAuthor(str(config_value(cfg, "interface", "developer_name", "MAAT")))

    for index, group in enumerate(groups):
        if index > 0:
            c.showPage()
        draw_group_page(c, root, group, list(rows_by_group.get(group, [])), title_lines, fonts)
    c.save()



def draw_qr_code(c, url: str, x: float, y: float, size: float) -> None:
    from reportlab.graphics import renderPDF
    from reportlab.graphics.barcode import qr
    from reportlab.graphics.shapes import Drawing

    widget = qr.QrCodeWidget(url)
    bounds = widget.getBounds()
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    drawing = Drawing(size, size, transform=[size / width, 0, 0, size / height, 0, 0])
    drawing.add(widget)
    renderPDF.draw(drawing, c, x, y)

def draw_card(c, root: Path, row: dict[str, str], x: float, y: float, width: float, height: float, title_lines: list[str], fonts: tuple[str, str]) -> None:
    from reportlab.lib import colors
    from reportlab.lib.utils import ImageReader

    regular_font, bold_font = fonts
    c.setDash(3, 2)
    c.setStrokeColor(colors.grey)
    c.setLineWidth(0.7)
    c.roundRect(x, y, width, height, 5.0, stroke=1, fill=0)
    c.setDash()
    c.setStrokeColor(colors.black)

    # Header: compact, centered, and kept inside the card.
    top = y + height - 13.0
    draw_centered_in_box(c, title_lines[0], x, top, width, bold_font, 7.8)
    draw_centered_in_box(c, title_lines[1], x, top - 10.5, width, regular_font, 6.9)
    draw_centered_in_box(c, title_lines[2], x, top - 20.5, width, regular_font, 6.9)

    full_name = f"{row.get('first_name', '').strip()} {row.get('last_name', '').strip()}".strip()
    draw_centered_in_box(c, full_name, x, y + height - 49.0, width, bold_font, 10.8)

    left_pad = 17.0
    label_x = x + left_pad
    value_x = x + 73.0
    info_y = y + height - 78.0
    line_gap = 15.0

    c.setFont(regular_font, 8.8)
    c.setFillColor(colors.black)
    c.drawString(label_x, info_y, "Groupe :")
    c.drawString(label_x, info_y - line_gap, "Token :")
    c.drawString(label_x, info_y - 2 * line_gap, "Symbole :")

    c.setFont(bold_font, 9.3)
    c.drawString(value_x, info_y, shorten(row.get("group", ""), bold_font, 9.3, width - (value_x - x) - 14.0))
    c.setFont(bold_font, 8.7)
    c.drawString(value_x, info_y - line_gap, shorten(row.get("token", ""), bold_font, 8.7, width - (value_x - x) - 14.0))

    animal = row.get("animal", "") or row.get("animal_entity", "")
    image_path = emoji_image_path(root, animal)
    if image_path is not None:
        try:
            image = ImageReader(str(image_path))
            size = 17.0
            c.drawImage(
                image,
                value_x,
                info_y - 2 * line_gap - 3.0,
                width=size,
                height=size,
                mask="auto",
                preserveAspectRatio=True,
                anchor="c",
            )
        except Exception:
            c.setFont(bold_font, 9.0)
            c.drawString(value_x, info_y - 2 * line_gap, animal)
    else:
        c.setFont(bold_font, 9.0)
        c.drawString(value_x, info_y - 2 * line_gap, animal)

    # Course-support QR code: public URL only, no token or personal data.
    qr_size = 42.0
    qr_x = x + width - qr_size - 15.0
    qr_y = y + 22.0
    draw_qr_code(c, COURSE_SUPPORTS_URL, qr_x, qr_y, qr_size)
    c.setFont(regular_font, 5.6)
    c.setFillColor(colors.black)
    c.drawCentredString(qr_x + qr_size / 2.0, qr_y - 6.2, "Supports")

    c.setFont(bold_font, 6.7)
    c.setFillColor(colors.darkred)
    c.drawString(x + left_pad, y + 21.5, "Ne pas partager ce coupon")
    c.setFont(regular_font, 6.2)
    c.setFillColor(colors.black)
    c.drawString(x + left_pad, y + 11.0, "URL du serveur affichée au tableau")

def generate_cards_pdf(root: Path, cfg: dict[str, Any], rows: list[dict[str, str]], output_path: Path) -> None:
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4

    output_path.parent.mkdir(parents=True, exist_ok=True)
    title_lines = make_title_lines(cfg)
    fonts = register_fonts()
    c = canvas.Canvas(str(output_path), pagesize=A4)
    c.setTitle("MAAT - coupons étudiants")
    c.setAuthor(str(config_value(cfg, "interface", "developer_name", "MAAT")))

    page_width, page_height = A4
    margin_x = 28.0
    margin_y = 30.0
    gutter_x = 18.0
    gutter_y = 10.0
    cols = 2
    rows_per_page = 5
    cards_per_page = cols * rows_per_page
    card_width = (page_width - 2.0 * margin_x - (cols - 1) * gutter_x) / cols
    card_height = (page_height - 2.0 * margin_y - (rows_per_page - 1) * gutter_y) / rows_per_page

    if not rows:
        c.setFont(fonts[0], 11.0)
        c.drawCentredString(page_width / 2.0, page_height / 2.0, "Aucun étudiant trouvé.")
        c.save()
        return

    for index, row in enumerate(rows):
        if index > 0 and index % cards_per_page == 0:
            c.showPage()
        pos = index % cards_per_page
        col = pos % cols
        row_index = pos // cols
        x = margin_x + col * (card_width + gutter_x)
        y = page_height - margin_y - (row_index + 1) * card_height - row_index * gutter_y
        draw_card(c, root, row, x, y, card_width, card_height, title_lines, fonts)
    c.save()


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    import sys
    sys.path.insert(0, str(root))
    from maat_app.config import load_config
    cfg = load_config()
    csv_path = Path(str(cfg.get("students_csv_abs")))
    rows = load_rows(csv_path)
    documents_dir = Path(str(cfg.get("documents_dir_abs")))
    admin_path = documents_dir / ADMIN_OUTPUT_FILENAME
    cards_path = documents_dir / CARDS_OUTPUT_FILENAME
    generate_admin_pdf(root, cfg, rows, admin_path)
    generate_cards_pdf(root, cfg, rows, cards_path)
    print(f"PDF enseignant complet: {admin_path}")
    print(f"PDF étudiants à découper: {cards_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
