#!/usr/bin/env python3
"""
Generate cinema schedule images from supported cinema schedule sources.

Set SCHEDULE_PARSER in .env to choose the source:
    kinominska  — kinominska.by (default)
    bycard      — bycard.by

Usage:
    python make_schedule.py
    python make_schedule.py --date 27.06.2026
    python make_schedule.py --date 2026-06-27 --output ./posters
"""

import argparse
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

from parsers import get_parser

logger = logging.getLogger(__name__)

# Genitive month names used in the date label, e.g. "27 Июня"
MONTHS_GEN = [
    "Января", "Февраля", "Марта", "Апреля", "Мая", "Июня",
    "Июля", "Августа", "Сентября", "Октября", "Ноября", "Декабря",
]

# Supersampling scale: render at 2x then downscale for smooth edges
SCALE = 2

# Final image dimensions and layout (in output pixels)
IMG_W, IMG_H = 1440, 2560
MARGIN_X = 80
MARGIN_TOP = 100
HEADER_H = 240
FOOTER_H = 110
CARD_GAP_X = 50
CARD_GAP_Y = 60
POSTER_W = 230
POSTER_H = 335
COL_W = (IMG_W - 2 * MARGIN_X - CARD_GAP_X) // 2
TEXT_W = COL_W - POSTER_W - 55  # right-side padding inside the card
CARDS_PER_PAGE = 10  # 2 columns x 5 rows

# Colors sampled from the original images
COLOR_TOP = (47, 40, 118)        # dark purple
COLOR_MIDDLE = (47, 112, 154)    # teal
COLOR_BOTTOM = (49, 186, 196)    # cyan/teal
COLOR_TEXT = (255, 255, 255)
COLOR_TEXT_MUTED = (255, 255, 255)  # all text at full opacity
COLOR_TIME_BG = (125, 105, 215)
COLOR_TIME_BORDER = (205, 195, 245)
COLOR_FOOTER_TEXT = (48, 48, 48)


def setup_logging(date_obj, debug=False):
    month_name = MONTHS_GEN[date_obj.month - 1]
    log_filename = f"logs-{date_obj.day:02d}-{month_name}.txt"

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if debug else logging.INFO)

    file_handler = logging.FileHandler(log_filename, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    file_handler.setFormatter(file_formatter)
    root_logger.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_formatter = logging.Formatter("%(message)s")
    stream_handler.setFormatter(stream_formatter)
    root_logger.addHandler(stream_handler)


def s(value):
    """Scale a dimension for supersampled rendering."""
    return value * SCALE


def create_gradient(width, height, top, middle, bottom):
    """Create a radial gradient from bottom-left corner at supersampled size."""
    import math
    w, h = s(width), s(height)
    max_dist = math.sqrt(w * w + h * h)

    # 256-entry color lookup table for speed
    lut = []
    for i in range(256):
        t = i / 255.0
        if t < 0.5:
            lt = t * 2
            r = int(top[0] * (1 - lt) + middle[0] * lt)
            g = int(top[1] * (1 - lt) + middle[1] * lt)
            b = int(top[2] * (1 - lt) + middle[2] * lt)
        else:
            lt = (t - 0.5) * 2
            r = int(middle[0] * (1 - lt) + bottom[0] * lt)
            g = int(middle[1] * (1 - lt) + bottom[1] * lt)
            b = int(middle[2] * (1 - lt) + bottom[2] * lt)
        lut.append((r, g, b))

    dy_sq = [(h - y) * (h - y) for y in range(h)]
    data = bytearray(w * h * 3)
    idx = 0
    for y in range(h):
        dqs = dy_sq[y]
        for x in range(w):
            t = min(255, int(math.sqrt(x * x + dqs) / max_dist * 255))
            r, g, b = lut[t]
            data[idx] = r
            data[idx + 1] = g
            data[idx + 2] = b
            idx += 3

    return Image.frombytes("RGB", (w, h), bytes(data))


def rounded_rectangle_mask(size, radius):
    """Return an L-mode mask with rounded corners at supersampled size."""
    mask = Image.new("L", (s(size[0]), s(size[1])), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([(0, 0), (s(size[0]), s(size[1]))],
                           radius=s(radius), fill=255)
    return mask


def get_font(size, weight="bold", font_dir=None):
    """Return a Montserrat TrueType font, falling back to DejaVu/Arial."""
    weight_files = {
        "extrabold": ["Montserrat-ExtraBold.ttf", "Montserrat-Bold.ttf"],
        "bold": ["Montserrat-Bold.ttf", "Montserrat-SemiBold.ttf"],
        "semibold": ["Montserrat-SemiBold.ttf", "Montserrat-Bold.ttf"],
        "medium": ["Montserrat-Medium.ttf", "Montserrat-SemiBold.ttf"],
    }
    candidates = weight_files.get(weight, weight_files["bold"])

    # Bundled fonts first
    if font_dir:
        for name in candidates:
            path = Path(font_dir) / name
            if path.exists():
                return ImageFont.truetype(str(path), s(size))

    # Windows system fonts
    windows_fonts = Path("C:/Windows/Fonts")
    win_candidates = {
        "extrabold": ["Montserrat-ExtraBold.ttf", "Montserrat-Bold.ttf",
                      "arialbd.ttf", "Arial Bold.ttf"],
        "bold": ["Montserrat-Bold.ttf", "Montserrat-SemiBold.ttf",
                 "arialbd.ttf", "Arial Bold.ttf"],
        "semibold": ["Montserrat-SemiBold.ttf", "Montserrat-Bold.ttf",
                      "arial.ttf", "Arial.ttf"],
    }
    win_list = win_candidates.get(weight, win_candidates["bold"])
    for name in win_list:
        path = windows_fonts / name
        if path.exists():
            return ImageFont.truetype(str(path), s(size))

    # Linux / macOS fallback paths
    system_paths = [
        "/usr/share/fonts/truetype/montserrat",
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/TTF",
        "/System/Library/Fonts",
    ]
    for sp in system_paths:
        for name in candidates:
            path = Path(sp) / name
            if path.exists():
                return ImageFont.truetype(str(path), s(size))

    # Last resort bundled DejaVu
    if font_dir:
        dejavu = Path(font_dir) / "DejaVuSans-Bold.ttf"
        if dejavu.exists():
            return ImageFont.truetype(str(dejavu), s(size))

    raise FileNotFoundError(
        "No suitable font found. Please place Montserrat-Bold.ttf in the fonts folder."
    )


def download_poster(session, url, cache_dir):
    """Download a poster image to the cache directory, returning the local path."""
    if not url:
        return None
    filename = Path(urlparse(url).path).name
    if not filename:
        filename = "poster.jpg"
    cache_path = Path(cache_dir) / filename
    if cache_path.exists():
        return str(cache_path)

    r = session.get(url, timeout=30)
    r.raise_for_status()
    cache_path.write_bytes(r.content)
    return str(cache_path)


def wrap_text(draw, text, font, max_width):
    """Return a list of lines that fit within max_width."""
    if not text:
        return []

    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines or not text else [text]


def format_duration(duration_str):
    m = __import__("re").search(r"(\d+)", duration_str)
    if not m:
        return duration_str or ""
    minutes = int(m.group(1))
    h, mm = divmod(minutes, 60)
    if h and mm:
        return f"{h} ч {mm} мин"
    if h:
        return f"{h} ч"
    return f"{mm} мин"


def truncate_lines(draw, lines, max_lines, font, max_width):
    if len(lines) <= max_lines:
        return lines
    lines = lines[:max_lines]
    last = lines[-1]
    while draw.textbbox((0, 0), last + "…", font=font)[2] > max_width:
        last = last[:-1]
    lines[-1] = last + "…"
    return lines


def draw_poster(img, x, y, poster_path, radius=16):
    """Draw a poster with smooth rounded corners (supersampled)."""
    if not poster_path or not Path(poster_path).exists():
        placeholder = Image.new("RGB", (s(POSTER_W), s(POSTER_H)), (60, 60, 90))
        mask = rounded_rectangle_mask((POSTER_W, POSTER_H), radius)
        img.paste(placeholder, (s(x), s(y)), mask)
        return

    try:
        pimg = Image.open(poster_path).convert("RGB")
        pimg = pimg.resize((s(POSTER_W), s(POSTER_H)), Image.Resampling.LANCZOS)
        mask = rounded_rectangle_mask((POSTER_W, POSTER_H), radius)
        img.paste(pimg, (s(x), s(y)), mask)
    except Exception as e:
        logger.warning("Failed to load poster '%s': %s", poster_path, e)
        placeholder = Image.new("RGB", (s(POSTER_W), s(POSTER_H)), (60, 60, 90))
        mask = rounded_rectangle_mask((POSTER_W, POSTER_H), radius)
        img.paste(placeholder, (s(x), s(y)), mask)


def font_path(weight, font_dir):
    """Return the best available font file path for the requested weight."""
    weight_files = {
        "extrabold": ["Montserrat-ExtraBold.ttf", "Montserrat-Bold.ttf"],
        "bold": ["Montserrat-Bold.ttf", "Montserrat-SemiBold.ttf"],
        "semibold": ["Montserrat-SemiBold.ttf", "Montserrat-Bold.ttf"],
        "medium": ["Montserrat-Medium.ttf", "Montserrat-SemiBold.ttf"],
    }
    candidates = weight_files.get(weight, weight_files["bold"])

    if font_dir:
        for name in candidates:
            path = Path(font_dir) / name
            if path.exists():
                return str(path)

    windows_fonts = Path("C:/Windows/Fonts")
    win_map = {
        "extrabold": ["Montserrat-ExtraBold.ttf", "Montserrat-Bold.ttf",
                      "arialbd.ttf", "Arial Bold.ttf"],
        "bold": ["Montserrat-Bold.ttf", "Montserrat-SemiBold.ttf",
                 "arialbd.ttf", "Arial Bold.ttf"],
        "semibold": ["Montserrat-SemiBold.ttf", "Montserrat-Bold.ttf",
                     "arialbd.ttf", "Arial Bold.ttf"],
    }
    for name in win_map.get(weight, win_map["bold"]):
        path = windows_fonts / name
        if path.exists():
            return str(path)

    system_paths = [
        "/usr/share/fonts/truetype/montserrat",
        "/usr/share/fonts/truetype/dejavu",
        "/usr/share/fonts/TTF",
        "/System/Library/Fonts",
    ]
    for sp in system_paths:
        for name in candidates:
            path = Path(sp) / name
            if path.exists():
                return str(path)

    if font_dir:
        dejavu = Path(font_dir) / "DejaVuSans-Bold.ttf"
        if dejavu.exists():
            return str(dejavu)

    raise FileNotFoundError("No suitable font found. Please place Montserrat-Bold.ttf in the fonts folder.")


def load_icon(path, size):
    """Load a PNG icon and resize it smoothly."""
    icon = Image.open(path).convert("RGBA")
    icon = icon.resize((s(size), s(size)), Image.Resampling.LANCZOS)
    return icon


def draw_card(draw, img, movie, x, y, fonts, font_dir):
    """Draw a single movie card at the given top-left corner."""
    time_font, hall_font = fonts
    bold_path = font_path("bold", font_dir)
    semibold_path = font_path("semibold", font_dir)

    # Poster
    draw_poster(img, x, y, movie.get("poster_path"))

    tx = x + POSTER_W + 30
    ty = y

    # Title (uppercase, fixed size 33, max 3 lines)
    title = movie.get("title", "").upper()
    title_font = ImageFont.truetype(bold_path, s(33))
    title_lines = wrap_text(draw, title, title_font, s(TEXT_W))
    title_lines = truncate_lines(draw, title_lines, 3, title_font, s(TEXT_W))
    line_height = title_font.size + s(8)
    for i, line in enumerate(title_lines):
        draw.text((s(tx), s(ty) + i * line_height), line,
                  fill=COLOR_TEXT, font=title_font)

    # Meta lines (genre, country, age+duration) — all at size 16
    title_h = len(title_lines) * line_height
    meta_y = s(ty) + title_h + s(12)

    meta_font = ImageFont.truetype(semibold_path, s(16))
    meta_line_h = meta_font.size + s(5)

    # Genres
    genre_line = " • ".join(g.upper() for g in movie.get("genres", [])[:3])
    if genre_line:
        genre_lines = wrap_text(draw, genre_line, meta_font, s(TEXT_W))
        genre_lines = truncate_lines(draw, genre_lines, 2, meta_font, s(TEXT_W))
        for i, line in enumerate(genre_lines):
            draw.text((s(tx), meta_y + i * meta_line_h), line,
                      fill=COLOR_TEXT, font=meta_font)
        meta_y += len(genre_lines) * meta_line_h

    # Countries (split by comma, join with dots, like genres)
    country_str = movie.get("country", "")
    if country_str:
        country_parts = [c.strip().upper() for c in country_str.split(",") if c.strip()]
        country_line = " • ".join(country_parts)
    else:
        country_line = ""
    if country_line:
        country_lines = wrap_text(draw, country_line, meta_font, s(TEXT_W))
        country_lines = truncate_lines(draw, country_lines, 2, meta_font, s(TEXT_W))
        for i, line in enumerate(country_lines):
            draw.text((s(tx), meta_y + i * meta_line_h), line,
                      fill=COLOR_TEXT, font=meta_font)
        meta_y += len(country_lines) * meta_line_h

    # Age + duration
    age = movie.get("age", "")
    duration = format_duration(movie.get("duration", ""))
    info_line = f"{age} • {duration}".strip(" •")
    if info_line:
        info_lines = wrap_text(draw, info_line, meta_font, s(TEXT_W))
        info_lines = truncate_lines(draw, info_lines, 2, meta_font, s(TEXT_W))
        for i, line in enumerate(info_lines):
            draw.text((s(tx), meta_y + i * meta_line_h), line,
                      fill=COLOR_TEXT, font=meta_font)
        meta_y += len(info_lines) * meta_line_h

    # Session time buttons placed right after the meta text (top to bottom)
    sessions = sorted(movie.get("sessions", []), key=lambda s: s.get("time", ""))
    button_w = 100
    button_h = 46
    button_gap_x = 12
    button_gap_y = 36
    session_top = meta_y // SCALE + 24

    sy = session_top
    sx = tx

    for sess in sessions:
        time_str = sess.get("time", "")
        hall = sess.get("hall")

        if sx + button_w > tx + TEXT_W:
            sx = tx
            sy += button_h + button_gap_y

        # Hall label above the button
        if hall:
            label = f"Зал №{hall}"
            draw.text((s(sx + button_w // 2), s(sy) - s(3)), label,
                      fill=COLOR_TEXT, font=hall_font, anchor="mb")

        # Rounded button
        draw.rounded_rectangle(
            [(s(sx), s(sy)), (s(sx + button_w), s(sy + button_h))],
            radius=s(button_h // 2),
            fill=COLOR_TIME_BG,
            outline=COLOR_TIME_BORDER,
            width=s(2),
        )
        draw.text((s(sx + button_w // 2), s(sy + button_h // 2)), time_str,
                  fill=COLOR_TEXT, font=time_font, anchor="mm")

        sx += button_w + button_gap_x


def generate_images(movies, date_obj, output_dir, font_dir):
    """Render schedule images with supersampling, splitting into pages if needed."""
    title_font = get_font(80, weight="extrabold", font_dir=font_dir)
    date_font = get_font(60, weight="bold", font_dir=font_dir)
    time_font = get_font(23, weight="bold", font_dir=font_dir)
    hall_font = get_font(14, weight="bold", font_dir=font_dir)
    footer_font = get_font(54, weight="medium", font_dir=font_dir)
    card_fonts = (time_font, hall_font)

    date_label = f"{date_obj.day} {MONTHS_GEN[date_obj.month - 1].upper()}"
    base_name = f"{date_obj.day:02d} {MONTHS_GEN[date_obj.month - 1]}"

    if not movies:
        logger.info("No movies to render.")
        return []

    max_movies = 2 * CARDS_PER_PAGE
    if len(movies) > max_movies:
        raise ValueError(
            f"Too many movies ({len(movies)}) to fit in {max_movies} card slots across 2 pages. "
            f"Reduce the number of movies or increase CARDS_PER_PAGE."
        )

    half = (len(movies) + 1) // 2  # ceil division, so first page gets up to one extra
    pages = [movies[:half], movies[half:]]

    # Load footer icons once
    insta_icon_size = 120
    globe_icon_size = 80
    instagram_icon = load_icon("instagram.png", insta_icon_size)
    globe_icon = load_icon("globe.png", globe_icon_size)

    saved = []
    for page_idx, page in enumerate(pages, start=1):
        img = create_gradient(IMG_W, IMG_H, COLOR_BOTTOM, COLOR_MIDDLE, COLOR_TOP)
        draw = ImageDraw.Draw(img)

        # Header
        draw.text((s(IMG_W // 2), s(70)), "РАСПИСАНИЕ СЕАНСОВ",
                  fill=COLOR_TEXT, font=title_font, anchor="mt")
        draw.text((s(IMG_W // 2), s(180)), date_label,
                  fill=COLOR_TEXT, font=date_font, anchor="mt")

        # Cards
        for i, movie in enumerate(page):
            col = i % 2
            row = i // 2
            x = MARGIN_X + col * (COL_W + CARD_GAP_X)
            y = MARGIN_TOP + HEADER_H + row * (POSTER_H + CARD_GAP_Y)
            draw_card(draw, img, movie, x, y, card_fonts, font_dir)

        # Footer — centered with equal margins
        footer_y = s(IMG_H - 80)
        icon_gap = 14
        block_gap = 60

        insta_text = "@kinoteatr_moskva"
        website_text = "kinominska.by"
        insta_text_w = draw.textbbox((0, 0), insta_text, font=footer_font)[2]
        website_text_w = draw.textbbox((0, 0), website_text, font=footer_font)[2]

        left_block_w = s(insta_icon_size) + s(icon_gap) + insta_text_w
        right_block_w = s(globe_icon_size) + s(icon_gap) + website_text_w
        total_w = left_block_w + s(block_gap) + right_block_w
        start_x = (s(IMG_W) - total_w) // 2

        # Instagram icon + handle
        insta_x = start_x
        img.paste(instagram_icon, (insta_x, footer_y - s(insta_icon_size) // 2), instagram_icon)
        draw.text((insta_x + s(insta_icon_size) + s(icon_gap), footer_y), insta_text,
                  fill=COLOR_FOOTER_TEXT, font=footer_font, anchor="lm")

        # Globe icon + website
        globe_x = start_x + left_block_w + s(block_gap)
        img.paste(globe_icon, (globe_x, footer_y - s(globe_icon_size) // 2), globe_icon)
        draw.text((globe_x + s(globe_icon_size) + s(icon_gap), footer_y), website_text,
                  fill=COLOR_FOOTER_TEXT, font=footer_font, anchor="lm")

        # Downsample to final size for smooth edges
        img = img.resize((IMG_W, IMG_H), Image.Resampling.LANCZOS)

        out_path = Path(output_dir) / f"{base_name} {page_idx}.jpg"
        img.save(out_path, quality=100, subsampling=0)
        saved.append(str(out_path))
        logger.info(f"Saved {out_path}")

    return saved


def parse_date_arg(value):
    """Parse user-supplied date string into a date object."""
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"Invalid date '{value}'. Use DD.MM.YYYY or YYYY-MM-DD."
    )


def main():
    parser = argparse.ArgumentParser(
        description="Generate cinema schedule images from supported cinema sources."
    )
    parser.add_argument(
        "--date",
        type=parse_date_arg,
        help="Schedule date in DD.MM.YYYY or YYYY-MM-DD format (default: tomorrow).",
    )
    parser.add_argument(
        "--output",
        default=".",
        help="Output directory for generated images (default: current folder).",
    )
    parser.add_argument(
        "--font-dir",
        default="fonts",
        help="Directory containing fallback TrueType fonts (default: fonts).",
    )
    parser.add_argument(
        "--cache-dir",
        default="cache",
        help="Directory for cached movie posters (default: cache).",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Seconds to wait between requests (default: 1.0).",
    )
    args = parser.parse_args()

    date_obj = args.date or (datetime.now() + timedelta(days=1)).date()

    env_path = Path(".env")
    if env_path.exists():
        load_dotenv(env_path)
    debug = os.getenv("MAGICINFO_DEBUG", "").strip().lower() in ("true", "1", "yes")
    setup_logging(date_obj, debug=debug)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    font_dir = Path(args.font_dir)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    parser_name = os.getenv("SCHEDULE_PARSER", "kinominska")
    schedule_parser = get_parser(parser_name, delay=args.delay)

    logger.info(f"Using parser: {parser_name}")
    movies = schedule_parser.fetch_schedule(session, date_obj)
    logger.info(f"Found {len(movies)} movies")

    if not movies:
        logger.info("No sessions found for this date.")
        return

    for i, movie in enumerate(movies, start=1):
        logger.info(f"[{i}/{len(movies)}] Fetching details for: {movie['title']}")
        try:
            detail = schedule_parser.fetch_movie_detail(session, movie["href"])
            movie.update(detail)
        except Exception as e:
            logger.error("Failed to fetch details for '%s': %s", movie["title"], e)

        poster_url = movie.get("poster_url")
        if poster_url:
            try:
                poster_path = download_poster(session, poster_url, cache_dir)
                movie["poster_path"] = poster_path
            except Exception as e:
                logger.warning("Failed to download poster for '%s': %s", movie["title"], e)

        if i < len(movies):
            time.sleep(args.delay)

    saved_paths = generate_images(movies, date_obj, output_dir, font_dir)

    from magicinfo import upload_schedule_images
    try:
        upload_schedule_images(saved_paths, date_obj)
    except Exception as e:
        logger.error("MagicINFO upload failed: %s", e)

    logger.info("Done.")


if __name__ == "__main__":
    main()
