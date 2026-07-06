# cinema-schedule

Generates cinema schedule images for [kinominska.by](https://kinominska.by/objects/17) and uploads them to Samsung MagicINFO digital signage.

## Quick start

```
pip install -r requirements.txt
python make_schedule.py
```

Generates tomorrow's schedule as two 1440×2560 JPG images in the current directory.

## Options

| Flag | Default | Description |
|------|---------|-------------|
| `--date DD.MM.YYYY` | tomorrow | Schedule date |
| `--output ./out` | `.` | Output directory for images |
| `--delay 0.5` | `0.3` | Seconds between detail-page requests |
| `--font-dir fonts` | `fonts` | Font files directory |
| `--cache-dir cache` | `cache` | Poster cache directory |

## MagicINFO integration

Copy `.env.example` to `.env`, fill in your MagicINFO credentials:

| Variable | Default | Description |
|----------|---------|-------------|
| `MAGICINFO_ENABLED` | `true` | Set to `false` to disable |
| `MAGICINFO_HOST` | `192.168.100.20` | MagicINFO server IP |
| `MAGICINFO_PORT` | `7001` | MagicINFO server port |
| `MAGICINFO_API_KEY` | — | API key from MagicINFO admin |
| `MAGICINFO_CONTENT_GROUP` | `default` | Content group name |
| `MAGICINFO_SCHEDULE_GROUP` | `Расписание` | Schedule group name |
| `MAGICINFO_SCHEDULE_NAME_1` | `Расписание 1` | Name for page 1 schedule |
| `MAGICINFO_SCHEDULE_NAME_2` | `Расписание 2` | Name for page 2 schedule |
| `MAGICINFO_DEVICE_TYPE` | `SPLAYER` | Device type string |
| `MAGICINFO_DEVICE_TYPE_VERSION` | `2.0` | Device type version |
| `MAGICINFO_DEBUG` | `false` | Verbose API request logging |

The script uploads generated images, creates/updates content schedules, and deploys them for the full day. Existing schedules are updated by name (no duplicates).

## Files

- `make_schedule.py` — scraping + image generation + CLI
- `magicinfo.py` — MagicINFO REST API client
- `swagger.json` — MagicINFO REST API v1.0 spec
- `.env.example` — config template
- `fonts/` — bundled Montserrat and DejaVu fonts
- `cache/` — downloaded movie posters
- `instagram.png` / `globe.png` — footer icons
