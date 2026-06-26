#!/usr/bin/env python3
"""
Generate cinema schedule images for kinominska.by/objects/17.

Usage:
    python make_schedule.py
    python make_schedule.py --date 27.06.2026
    python make_schedule.py --date 2026-06-27 --output ./posters
"""

import argparse
import re
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image, ImageDraw, ImageFont

BASE_URL = "https://kinominska.by"
OBJECT_ID = 17

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
CARDS_PER_PAGE = 6  # 2 columns x 3 rows, matching the existing images

# Colors sampled from the original images
COLOR_TOP = (47, 40, 118)        # dark purple
COLOR_MIDDLE = (47, 112, 154)    # teal
COLOR_BOTTOM = (49, 186, 196)    # cyan/teal
COLOR_TEXT = (255, 255, 255)
COLOR_TEXT_MUTED = (255, 255, 255)  # all text at full opacity
COLOR_TIME_BG = (125, 105, 215)
COLOR_TIME_BORDER = (205, 195, 245)
COLOR_FOOTER_TEXT = (0, 0, 0)


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
    }.get(weight, win_candidates["bold"])
    for name in win_candidates:
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

    return ImageFont.load_default()


def fetch_html(session, url):
    """Fetch HTML with a realistic user agent."""
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.7",
    }
    r = session.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    return r.text


def parse_schedule(html):
    """Parse the object schedule page into a list of movies with sessions."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", class_="custom-table")
    if not table:
        return []

    movies = []
    current_head = None

    for child in table.children:
        name = getattr(child, "name", None)
        if name == "thead":
            current_head = child
        elif name == "tbody" and current_head is not None:
            a = current_head.find("a", href=re.compile(r"^/events/"))
            if not a:
                current_head = None
                continue

            title = a.get_text(strip=True)
            href = a["href"]
            slug = href.strip("/").split("/")[-1]

            sessions = []
            for div in child.select(".widgets-wrapper > div"):
                if "disabled_click" in div.get("class", []):
                    continue
                sess_a = div.find("a", href=True)
                if not sess_a:
                    continue
                spans = sess_a.find_all("span", class_="button-text")
                if not spans:
                    continue

                time_str = spans[0].get_text(strip=True)
                fmt = spans[1].get_text(strip=True) if len(spans) > 1 else ""
                hall_text = spans[2].get_text(strip=True) if len(spans) > 2 else ""
                hall_match = re.search(r"(\d+)", hall_text)
                hall = int(hall_match.group(1)) if hall_match else None

                sessions.append({"time": time_str, "format": fmt, "hall": hall})

            if sessions:
                movies.append({
                    "title": title,
                    "slug": slug,
                    "href": href,
                    "sessions": sessions,
                })
            current_head = None

    return movies


def parse_movie_detail(html):
    """Parse a movie detail page for metadata and poster URL."""
    soup = BeautifulSoup(html, "html.parser")
    data = {}

    title_el = soup.find("h2", class_="trending-text")
    data["title"] = title_el.get_text(strip=True) if title_el else ""

    # Poster: prefer the dedicated trailer/poster box, fall back to any event image
    poster_el = soup.select_one(".trailor-video .img-box img")
    if not poster_el:
        poster_el = soup.find("img", src=re.compile(r"/uploads/events/"))
    poster_url = None
    if poster_el:
        poster_url = poster_el.get("src") or poster_el.get("data-src")
        if poster_url and poster_url.startswith("/"):
            poster_url = urljoin(BASE_URL, poster_url)
    data["poster_url"] = poster_url

    # Genres
    genres = [g.get_text(strip=True) for g in soup.select(".movie-tag li.trending-list a")]
    data["genres"] = genres

    # Age rating and duration
    badge = soup.select_one(".text-detail .badge.bg-secondary")
    data["age"] = badge.get_text(strip=True) if badge else ""

    duration_el = soup.select_one(".text-detail .genres-info")
    data["duration"] = duration_el.get_text(strip=True) if duration_el else ""

    # Country
    country = ""
    for tag in soup.select(".iq-blogtag"):
        label = tag.find("li", class_="iq-tag-title")
        if label and "Страна:" in label.get_text():
            a = tag.find("a", class_="title")
            if a:
                country = a.get_text(strip=True)
                break
    data["country"] = country

    return data


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
    return lines if lines else [text]


def fit_wrapped_text(draw, text, max_width, max_lines, font_path, start_size, min_size):
    """
    Find the largest font size <= start_size such that `text` wraps into
    at most `max_lines` of width <= max_width. Return (font, lines).
    """
    for size in range(start_size, min_size - 1, -1):
        font = ImageFont.truetype(font_path, s(size))
        lines = wrap_text(draw, text, font, max_width)
        if len(lines) <= max_lines:
            return font, lines
    # Fallback: smallest size, truncate if still too many lines
    font = ImageFont.truetype(font_path, s(min_size))
    lines = wrap_text(draw, text, font, max_width)[:max_lines]
    if len(lines) == max_lines:
        last = lines[-1]
        if draw.textbbox((0, 0), last + "…", font=font)[2] <= max_width:
            lines[-1] = last + "…"
    return font, lines


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
    except Exception:
        placeholder = Image.new("RGB", (s(POSTER_W), s(POSTER_H)), (60, 60, 90))
        mask = rounded_rectangle_mask((POSTER_W, POSTER_H), radius)
        img.paste(placeholder, (s(x), s(y)), mask)


def font_path(weight, font_dir):
    """Return the best available font file path for the requested weight."""
    weight_files = {
        "extrabold": ["Montserrat-ExtraBold.ttf", "Montserrat-Bold.ttf"],
        "bold": ["Montserrat-Bold.ttf", "Montserrat-SemiBold.ttf"],
        "semibold": ["Montserrat-SemiBold.ttf", "Montserrat-Bold.ttf"],
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

    tx = x + POSTER_W + 20
    ty = y

    # Title (uppercase, fitted, max 3 lines)
    title = movie.get("title", "").upper()
    title_font, title_lines = fit_wrapped_text(
        draw, title, s(TEXT_W), max_lines=3,
        font_path=bold_path, start_size=38, min_size=22
    )
    line_height = title_font.size + s(8)
    for i, line in enumerate(title_lines):
        draw.text((s(tx), s(ty) + i * line_height), line,
                  fill=COLOR_TEXT, font=title_font)

    # Meta lines (genre, country, age+duration) with decreasing sizes
    title_h = len(title_lines) * line_height
    meta_y = s(ty) + title_h + s(12)

    genre_line = " • ".join(g.upper() for g in movie.get("genres", [])[:3])
    country_line = movie.get("country", "").upper()
    age = movie.get("age", "")
    duration = movie.get("duration", "")
    info_line = f"{age} • {duration}".strip(" •")

    # Genre (smaller than title)
    genre_font, genre_lines = fit_wrapped_text(
        draw, genre_line, s(TEXT_W), max_lines=2,
        font_path=semibold_path, start_size=21, min_size=16
    )
    genre_line_height = genre_font.size + s(5)
    for i, line in enumerate(genre_lines):
        draw.text((s(tx), meta_y + i * genre_line_height), line,
                  fill=COLOR_TEXT, font=genre_font)

    # Country (same size as genre)
    meta_y += len(genre_lines) * genre_line_height
    country_font, country_lines = fit_wrapped_text(
        draw, country_line, s(TEXT_W), max_lines=2,
        font_path=semibold_path, start_size=21, min_size=16
    )
    country_line_height = country_font.size + s(5)
    for i, line in enumerate(country_lines):
        draw.text((s(tx), meta_y + i * country_line_height), line,
                  fill=COLOR_TEXT, font=country_font)

    # Age + duration (smaller than genre)
    meta_y += len(country_lines) * country_line_height
    info_font, info_lines = fit_wrapped_text(
        draw, info_line, s(TEXT_W), max_lines=2,
        font_path=semibold_path, start_size=19, min_size=15
    )
    info_line_height = info_font.size + s(5)
    for i, line in enumerate(info_lines):
        draw.text((s(tx), meta_y + i * info_line_height), line,
                  fill=COLOR_TEXT, font=info_font)

    # Session time buttons placed right after the meta text (top to bottom)
    sessions = sorted(movie.get("sessions", []), key=lambda s: s.get("time", ""))
    button_w = 100
    button_h = 46
    button_gap_x = 12
    button_gap_y = 36
    session_top = (meta_y + len(info_lines) * info_line_height) // SCALE + 24

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
    title_font = get_font(92, weight="extrabold", font_dir=font_dir)
    date_font = get_font(72, weight="bold", font_dir=font_dir)
    time_font = get_font(22, weight="bold", font_dir=font_dir)
    hall_font = get_font(17, weight="semibold", font_dir=font_dir)
    footer_font = get_font(42, weight="bold", font_dir=font_dir)
    card_fonts = (time_font, hall_font)

    date_label = f"{date_obj.day} {MONTHS_GEN[date_obj.month - 1].upper()}"
    base_name = f"{date_obj.day:02d} {MONTHS_GEN[date_obj.month - 1]}"

    pages = [movies[i:i + CARDS_PER_PAGE] for i in range(0, len(movies), CARDS_PER_PAGE)]
    if not pages:
        print("No movies to render.")
        return []

    # Load footer icons once
    icon_size = 64
    instagram_icon = load_icon("instagram.png", icon_size)
    globe_icon = load_icon("globe.png", icon_size)

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

        # Footer
        icon_gap = 14
        footer_y = s(IMG_H - 65)

        # Instagram icon + handle
        insta_x = s(80)
        img.paste(instagram_icon, (insta_x, footer_y - s(icon_size) // 2), instagram_icon)
        draw.text((insta_x + s(icon_size) + s(icon_gap), footer_y), "@kinoteatr_moskva",
                  fill=COLOR_FOOTER_TEXT, font=footer_font, anchor="lm")

        # Globe icon + website
        website_text_width = draw.textbbox((0, 0), "kinominska.by", font=footer_font)[2]
        text_x = s(IMG_W - 80)
        draw.text((text_x, footer_y), "kinominska.by",
                  fill=COLOR_FOOTER_TEXT, font=footer_font, anchor="rm")
        globe_x = text_x - website_text_width - s(icon_gap) - s(icon_size)
        img.paste(globe_icon, (globe_x, footer_y - s(icon_size) // 2), globe_icon)

        # Downsample to final size for smooth edges
        img = img.resize((IMG_W, IMG_H), Image.Resampling.LANCZOS)

        out_path = Path(output_dir) / f"{base_name} {page_idx}.jpg"
        img.save(out_path, quality=95)
        saved.append(str(out_path))
        print(f"Saved {out_path}")

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
        description="Generate cinema schedule images for KinoMinska objects/17."
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
        default=0.3,
        help="Seconds to wait between detail-page requests (default: 0.3).",
    )
    args = parser.parse_args()

    date_obj = args.date or (datetime.now() + timedelta(days=1)).date()
    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)
    font_dir = Path(args.font_dir)
    cache_dir = Path(args.cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()

    schedule_url = f"{BASE_URL}/objects/{OBJECT_ID}?filter__by_date={date_obj:%Y-%m-%d}"
    print(f"Fetching schedule: {schedule_url}")
    html = fetch_html(session, schedule_url)
    movies = parse_schedule(html)
    print(f"Found {len(movies)} movies")

    if not movies:
        print("No sessions found for this date.")
        return

    # Enrich each movie with detail-page metadata
    for i, movie in enumerate(movies, start=1):
        detail_url = urljoin(BASE_URL, movie["href"])
        print(f"[{i}/{len(movies)}] Fetching details: {detail_url}")
        detail_html = fetch_html(session, detail_url)
        detail = parse_movie_detail(detail_html)
        movie.update(detail)

        if detail.get("poster_url"):
            poster_path = download_poster(session, detail["poster_url"], cache_dir)
            movie["poster_path"] = poster_path

        if i < len(movies):
            time.sleep(args.delay)

    generate_images(movies, date_obj, output_dir, font_dir)
    print("Done.")


if __name__ == "__main__":
    main()
