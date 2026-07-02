# AGENTS.md — cinema-schedule

## Architecture
- `make_schedule.py` — main script: scraping + image generation.
- `magicinfo.py` — Samsung MagicINFO REST API client for uploading/scheduling images.
- No framework, no package structure. All functions are module-level.

## Commands
- `python make_schedule.py` — generate for tomorrow
- `python make_schedule.py --date 27.06.2026` — specific date
- `python make_schedule.py --output ./out --delay 0.5` — custom output/delay
- `pip install -r requirements.txt` — install dependencies (requests, beautifulsoup4, Pillow, python-dotenv)
- MagicINFO integration is controlled via `.env` — copy `.env.example` to `.env` and fill in values.
- Swagger spec at `swagger.json` documents the MagicINFO REST API v1.0.

## No test/lint/CI
- There are no tests, no linter config, no typechecker, and no CI workflows.
- Do not try to run `pytest`, `ruff`, `mypy`, etc.

## Gotchas
- **Supersampling**: all rendering uses `SCALE = 2`. Layout coordinates are doubled internally, then the image is downscaled via LANCZOS. Keep this in mind when adjusting any pixel values.
- **Hardcoded target**: `object_id=17` is hardcoded in `fetch_schedule()`. There is no CLI flag to change the cinema.
- **Font cascade**: looks in `fonts/`, then Windows/Mac/Linux system dirs, then bundled DejaVu. No system font installation needed as long as `fonts/` is present.
- **Cyrillic filenames**: output files like `27 Июня 1.jpg`. Works on modern systems but worth noting.
- **Poster cache**: `cache/` stores downloaded posters by remote filename. Stale if the server reuses filenames—delete `cache/` to force re-download.
