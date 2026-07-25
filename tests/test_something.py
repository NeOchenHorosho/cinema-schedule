import argparse
import logging
import sys
import types
from datetime import date
from pathlib import Path
from unittest.mock import Mock

import pytest
from PIL import Image

import make_schedule as ms


class WidthBasedDraw:
    """Minimal ImageDraw substitute where each character is 10 px wide."""

    def textbbox(self, position, text, font=None):
        return 0, 0, len(text) * 10, 20


@pytest.fixture
def isolated_root_logger():
    """Prevent setup_logging tests from modifying pytest's root logger."""
    root_logger = logging.getLogger()
    original_handlers = root_logger.handlers[:]
    original_level = root_logger.level

    for handler in original_handlers:
        root_logger.removeHandler(handler)

    yield root_logger

    for handler in root_logger.handlers[:]:
        handler.close()
        root_logger.removeHandler(handler)

    for handler in original_handlers:
        root_logger.addHandler(handler)

    root_logger.setLevel(original_level)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("27.06.2026", date(2026, 6, 27)),
        ("2026-06-27", date(2026, 6, 27)),
        ("01.01.2025", date(2025, 1, 1)),
        ("2025-12-31", date(2025, 12, 31)),
    ],
)
def test_parse_date_arg_accepts_supported_formats(value, expected):
    assert ms.parse_date_arg(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "27/06/2026",
        "06-27-2026",
        "2026.06.27",
        "not-a-date",
        "",
    ],
)
def test_parse_date_arg_rejects_invalid_formats(value):
    with pytest.raises(argparse.ArgumentTypeError, match="Invalid date"):
        ms.parse_date_arg(value)


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        ("", ""),
        ("unknown", "unknown"),
        ("0 мин", "0 мин"),
        ("45 мин", "45 мин"),
        ("60 мин", "1 ч"),
        ("61 мин", "1 ч 1 мин"),
        ("90 minutes", "1 ч 30 мин"),
        ("125", "2 ч 5 мин"),
    ],
)
def test_format_duration(duration, expected):
    assert ms.format_duration(duration) == expected


def test_scale_uses_supersampling_factor(monkeypatch):
    monkeypatch.setattr(ms, "SCALE", 3)

    assert ms.s(10) == 30
    assert ms.s(0) == 0


def test_wrap_text_splits_text_at_maximum_width():
    draw = WidthBasedDraw()

    lines = ms.wrap_text(
        draw=draw,
        text="one two three",
        font=object(),
        max_width=70,
    )

    assert lines == ["one two", "three"]


@pytest.mark.parametrize("text", ["", None])
def test_wrap_text_returns_empty_list_for_empty_text(text):
    draw = WidthBasedDraw()

    assert ms.wrap_text(draw, text, object(), 100) == []


def test_wrap_text_preserves_a_word_wider_than_max_width():
    draw = WidthBasedDraw()

    lines = ms.wrap_text(
        draw=draw,
        text="extraordinary",
        font=object(),
        max_width=20,
    )

    assert lines == ["extraordinary"]


def test_truncate_lines_returns_original_lines_when_within_limit():
    draw = WidthBasedDraw()
    lines = ["first", "second"]

    result = ms.truncate_lines(
        draw=draw,
        lines=lines,
        max_lines=2,
        font=object(),
        max_width=100,
    )

    assert result == ["first", "second"]


def test_truncate_lines_shortens_last_line_and_adds_ellipsis():
    draw = WidthBasedDraw()

    result = ms.truncate_lines(
        draw=draw,
        lines=["alpha", "beta", "gamma"],
        max_lines=2,
        font=object(),
        max_width=40,
    )

    assert result == ["alpha", "bet…"]


def test_create_gradient_returns_supersampled_rgb_image(monkeypatch):
    monkeypatch.setattr(ms, "SCALE", 2)

    image = ms.create_gradient(
        width=4,
        height=3,
        top=(0, 0, 0),
        middle=(100, 100, 100),
        bottom=(200, 200, 200),
    )

    assert image.mode == "RGB"
    assert image.size == (8, 6)


def test_create_gradient_changes_with_distance_from_bottom_left(monkeypatch):
    monkeypatch.setattr(ms, "SCALE", 1)

    image = ms.create_gradient(
        width=10,
        height=10,
        top=(0, 0, 0),
        middle=(100, 100, 100),
        bottom=(200, 200, 200),
    )

    near_bottom_left = image.getpixel((0, 9))
    far_from_bottom_left = image.getpixel((9, 0))

    assert sum(near_bottom_left) < sum(far_from_bottom_left)


def test_rounded_rectangle_mask_has_transparent_corners(monkeypatch):
    monkeypatch.setattr(ms, "SCALE", 1)

    mask = ms.rounded_rectangle_mask((20, 10), radius=4)

    assert mask.mode == "L"
    assert mask.size == (20, 10)
    assert mask.getpixel((0, 0)) == 0
    assert mask.getpixel((10, 5)) == 255


def test_get_font_prefers_font_from_supplied_directory(tmp_path, monkeypatch):
    font_file = tmp_path / "Montserrat-Bold.ttf"
    font_file.touch()

    expected_font = object()
    truetype = Mock(return_value=expected_font)
    monkeypatch.setattr(ms.ImageFont, "truetype", truetype)

    result = ms.get_font(
        size=18,
        weight="bold",
        font_dir=tmp_path,
    )

    assert result is expected_font
    truetype.assert_called_once_with(str(font_file), ms.s(18))


def test_font_path_prefers_requested_weight_from_font_directory(tmp_path):
    expected = tmp_path / "Montserrat-SemiBold.ttf"
    expected.touch()

    result = ms.font_path("semibold", tmp_path)

    assert result == str(expected)


def test_download_poster_returns_none_for_missing_url(tmp_path):
    session = Mock()

    result = ms.download_poster(session, None, tmp_path)

    assert result is None
    session.get.assert_not_called()


def test_download_poster_uses_cached_file_without_request(tmp_path):
    cached_file = tmp_path / "poster.jpg"
    cached_file.write_bytes(b"cached-image")

    session = Mock()

    result = ms.download_poster(
        session,
        "https://example.com/images/poster.jpg?width=500",
        tmp_path,
    )

    assert result == str(cached_file)
    session.get.assert_not_called()


def test_download_poster_saves_response_content(tmp_path):
    response = Mock()
    response.content = b"downloaded-image-data"

    session = Mock()
    session.get.return_value = response

    result = ms.download_poster(
        session,
        "https://example.com/images/movie.jpg",
        tmp_path,
    )

    expected_path = tmp_path / "movie.jpg"

    assert result == str(expected_path)
    assert expected_path.read_bytes() == b"downloaded-image-data"

    session.get.assert_called_once_with(
        "https://example.com/images/movie.jpg",
        timeout=30,
    )
    response.raise_for_status.assert_called_once_with()


def test_download_poster_uses_default_name_when_url_has_no_filename(tmp_path):
    response = Mock()
    response.content = b"image"

    session = Mock()
    session.get.return_value = response

    result = ms.download_poster(
        session,
        "https://example.com/",
        tmp_path,
    )

    assert result == str(tmp_path / "poster.jpg")
    assert (tmp_path / "poster.jpg").read_bytes() == b"image"


def test_draw_poster_uses_placeholder_when_path_is_missing():
    canvas = Image.new(
        "RGB",
        (ms.s(ms.POSTER_W + 10), ms.s(ms.POSTER_H + 10)),
        (0, 0, 0),
    )

    ms.draw_poster(
        img=canvas,
        x=0,
        y=0,
        poster_path=None,
    )

    center = (
        ms.s(ms.POSTER_W) // 2,
        ms.s(ms.POSTER_H) // 2,
    )

    assert canvas.getpixel(center) == (60, 60, 90)


def test_generate_images_returns_empty_list_when_no_movies(
    tmp_path,
    monkeypatch,
    caplog,
):
    # Fonts are currently loaded before the empty-movie check.
    monkeypatch.setattr(ms, "get_font", lambda *args, **kwargs: object())

    with caplog.at_level(logging.INFO):
        result = ms.generate_images(
            movies=[],
            date_obj=date(2026, 6, 27),
            output_dir=tmp_path,
            font_dir=tmp_path / "fonts",
        )

    assert result == []
    assert "No movies to render." in caplog.text


def test_generate_images_splits_movies_and_returns_output_paths(
    tmp_path,
    monkeypatch,
):
    class FakeImage:
        def paste(self, *args, **kwargs):
            return None

        def resize(self, size, resample):
            assert size == (ms.IMG_W, ms.IMG_H)
            return self

        def save(self, path, **kwargs):
            Path(path).write_bytes(b"fake-jpeg")

    class FakeDraw:
        def text(self, *args, **kwargs):
            return None

        def textbbox(self, position, text, font=None):
            return 0, 0, len(text) * 20, 50

    drawn_movies = []

    def record_card(draw, image, movie, x, y, fonts, font_dir):
        drawn_movies.append(movie["title"])

    monkeypatch.setattr(ms, "get_font", lambda *args, **kwargs: object())
    monkeypatch.setattr(ms, "create_gradient", lambda *args: FakeImage())
    monkeypatch.setattr(ms.ImageDraw, "Draw", lambda image: FakeDraw())
    monkeypatch.setattr(ms, "load_icon", lambda *args, **kwargs: object())
    monkeypatch.setattr(ms, "draw_card", record_card)

    movies = [
        {"title": "Movie A"},
        {"title": "Movie B"},
        {"title": "Movie C"},
    ]

    result = ms.generate_images(
        movies=movies,
        date_obj=date(2026, 6, 27),
        output_dir=tmp_path,
        font_dir=tmp_path / "fonts",
    )

    assert result == [
        str(tmp_path / "27 Июня 1.jpg"),
        str(tmp_path / "27 Июня 2.jpg"),
    ]
    assert drawn_movies == ["Movie A", "Movie B", "Movie C"]

    assert (tmp_path / "27 Июня 1.jpg").exists()
    assert (tmp_path / "27 Июня 2.jpg").exists()


def test_setup_logging_creates_expected_handlers_and_filename(
    tmp_path,
    monkeypatch,
    isolated_root_logger,
):
    monkeypatch.chdir(tmp_path)

    ms.setup_logging(date(2026, 6, 27), debug=True)

    root_logger = isolated_root_logger

    file_handlers = [
        handler
        for handler in root_logger.handlers
        if isinstance(handler, logging.FileHandler)
    ]
    console_handlers = [
        handler
        for handler in root_logger.handlers
        if type(handler) is logging.StreamHandler
    ]

    assert root_logger.level == logging.DEBUG
    assert len(file_handlers) == 1
    assert len(console_handlers) == 1

    assert Path(file_handlers[0].baseFilename).name == "logs-27-Июня.txt"
    assert file_handlers[0].level == logging.DEBUG
    assert console_handlers[0].level == logging.INFO


def test_main_fetches_details_downloads_posters_and_generates_images(
    tmp_path,
    monkeypatch,
):
    output_dir = tmp_path / "output"
    cache_dir = tmp_path / "cache"
    font_dir = tmp_path / "fonts"

    movies = [
        {
            "title": "Movie A",
            "href": "/movie-a",
            "poster_url": "https://example.com/a.jpg",
        },
        {
            "title": "Movie B",
            "href": "/movie-b",
        },
    ]

    session = object()

    class FakeScheduleParser:
        def fetch_schedule(self, supplied_session, supplied_date):
            assert supplied_session is session
            assert supplied_date == date(2026, 6, 27)
            return movies

        def fetch_movie_detail(self, supplied_session, href):
            assert supplied_session is session

            if href == "/movie-a":
                return {
                    "genres": ["Drama"],
                    "duration": "120 мин",
                }

            raise RuntimeError("Detail page unavailable")

    schedule_parser = FakeScheduleParser()

    get_parser = Mock(return_value=schedule_parser)
    setup_logging = Mock()
    download_poster = Mock(return_value=str(cache_dir / "a.jpg"))
    generate_images = Mock(
        return_value=[
            str(output_dir / "27 Июня 1.jpg"),
            str(output_dir / "27 Июня 2.jpg"),
        ]
    )
    sleep = Mock()
    upload_schedule_images = Mock()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SCHEDULE_PARSER", "bycard")
    monkeypatch.setenv("MAGICINFO_DEBUG", "yes")

    monkeypatch.setattr(ms.requests, "Session", Mock(return_value=session))
    monkeypatch.setattr(ms, "get_parser", get_parser)
    monkeypatch.setattr(ms, "setup_logging", setup_logging)
    monkeypatch.setattr(ms, "download_poster", download_poster)
    monkeypatch.setattr(ms, "generate_images", generate_images)
    monkeypatch.setattr(ms.time, "sleep", sleep)

    fake_magicinfo = types.SimpleNamespace(
        upload_schedule_images=upload_schedule_images
    )
    monkeypatch.setitem(sys.modules, "magicinfo", fake_magicinfo)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "make_schedule.py",
            "--date",
            "27.06.2026",
            "--output",
            str(output_dir),
            "--font-dir",
            str(font_dir),
            "--cache-dir",
            str(cache_dir),
            "--delay",
            "0.25",
        ],
    )

    ms.main()

    get_parser.assert_called_once_with("bycard", delay=0.25)
    setup_logging.assert_called_once_with(date(2026, 6, 27), debug=True)

    assert output_dir.is_dir()
    assert cache_dir.is_dir()

    assert movies[0]["genres"] == ["Drama"]
    assert movies[0]["duration"] == "120 мин"
    assert movies[0]["poster_path"] == str(cache_dir / "a.jpg")

    download_poster.assert_called_once_with(
        session,
        "https://example.com/a.jpg",
        cache_dir,
    )

    sleep.assert_called_once_with(0.25)

    generate_images.assert_called_once_with(
        movies,
        date(2026, 6, 27),
        output_dir,
        font_dir,
    )

    upload_schedule_images.assert_called_once_with(
        [
            str(output_dir / "27 Июня 1.jpg"),
            str(output_dir / "27 Июня 2.jpg"),
        ],
        date(2026, 6, 27),
    )


def test_main_stops_early_when_schedule_is_empty(
    tmp_path,
    monkeypatch,
):
    class EmptyScheduleParser:
        def fetch_schedule(self, session, supplied_date):
            return []

        def fetch_movie_detail(self, session, href):
            pytest.fail("Movie details should not be requested")

    generate_images = Mock()

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ms, "setup_logging", Mock())
    monkeypatch.setattr(ms.requests, "Session", Mock(return_value=object()))
    monkeypatch.setattr(
        ms,
        "get_parser",
        Mock(return_value=EmptyScheduleParser()),
    )
    monkeypatch.setattr(ms, "generate_images", generate_images)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "make_schedule.py",
            "--date",
            "2026-06-27",
        ],
    )

    ms.main()

    generate_images.assert_not_called()
