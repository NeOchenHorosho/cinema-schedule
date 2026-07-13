# AGENTS.md — cinema-schedule

## Architecture
- `make_schedule.py` — main script: image generation + orchestration.
- `magicinfo.py` — Samsung MagicINFO REST API client for uploading/scheduling images.
- `parsers/` — schedule source parsers (`base.py`, `kinominska.py`, `bycard.py`). Each parser implements `fetch_schedule()` and `fetch_movie_detail()`.
- No framework. Functions are module-level or class methods on parser classes.

## Parser selection
- Set `SCHEDULE_PARSER=kinominska` or `SCHEDULE_PARSER=bycard` in `.env`.
- Defaults to `kinominska` if unset.
- Each parser loads its own URL constants internally (not configurable via .env).

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
- **Font cascade**: looks in `fonts/`, then Windows/Mac/Linux system dirs, then bundled DejaVu. No system font installation needed as long as `fonts/` is present.
- **Cyrillic filenames**: output files like `27 Июня 1.jpg`. Works on modern systems but worth noting.
- **Poster cache**: `cache/` stores downloaded posters by remote filename. Stale if the server reuses filenames—delete `cache/` to force re-download.
- **bycard.by hall info**: hall numbers come from `GET https://abws.bycard.by/api/v2/frame/session/{sid}` (one request per session). `map.hallName` is the field (e.g. "Зал 1.").
- **bycard.by time param**: the `?time=` parameter on the schedule page is a Unix timestamp for midnight UTC+3 of the target day.
- **bycard.by session API**: some session IDs from the JSON-LD may return 404 from the session API. The parser logs a warning and sets `hall=None` in that case.
- **MagicINFO auth**: `POST /MagicInfo/restapi/v2.0/auth` with `{"username":"...","password":"...","grantType":"password"}` returns a JWT. Use it as `api_key` header for all REST API calls.
- **MagicINFO groups**: schedule groups may be nested — the code walks child groups if the target isn't found at the root level.
- **MagicINFO DataTables**: list endpoints return `items.data[]` (not bare `items[]`). Both formats are handled. Schedule items use `programName`/`programId`, not `name`/`id`.
- **MagicINFO v2 events**: schedule events are managed via `GET`/`PUT` on `/restapi/v2.0/dms/content-schedules/{programId}`. The body is the full program object with an `events` array inside `channels[].frame`. Never strip fields from the GET response — only add/replace events.
- **MagicINFO v2 POST broken**: the dedicated `POST .../schedules` endpoint for adding events has a broken `startTime` validator on this server (rejects all formats). Use the full-program PUT instead.
- **Swagger spec v2** at `swagger2.json` contains all v2 endpoints and schemas.
- **MagicINFO auth token**: obtained once per client instance and never refreshed. The script runs for seconds, so token expiry is not an issue. Do not reuse a `MagicInfoClient` across multiple script invocations.
- **Schedule group nesting**: `_get_child_schedule_groups` only searches one level deep (direct children of root groups). This is sufficient for the current server setup.
- **deviceType `LPLAYER`**: not in the swagger2.json `V2ScheduleFilter` enum but accepted by the server. Do not change this value without verifying the server accepts it.
- **contentType `IMAGE`**: not in the swagger2.json `TTV2ScheduleEventResource` enum but accepted by the server. Same caveat as above.
- **V2 schedules must be pre-created**: unlike v1 which auto-created schedules, v2 raises an error if the named schedule doesn't exist. Create schedules via the MagicINFO web UI first.
- **Duration 86399**: event duration is one second short of 24h to avoid overlap with the next day's schedule when `isAllDayPlay: true`.
- **`MAGICINFO_DEVICE_GROUP_ID_1` / `MAGICINFO_DEVICE_GROUP_ID_2`**: optional `.env` variables — one per schedule page. Each schedule is deployed to its own device group. When unset for a schedule, no device group is assigned (re-publish targets all groups associated with the schedule). Re-publish body is always `{"ids": [...]}`, never `{}`.
- **`_delete` helper**: defined but unused. Left in place for potential future use.
