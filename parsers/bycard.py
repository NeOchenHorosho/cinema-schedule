"""Parser for bycard.by cinema schedule pages (JSON-LD + session API)."""

import json
import re
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base import BaseParser, logger

SCHEDULE_URL = "https://bycard.by/objects/minsk/2/100-kinoteatr-moskva"
BASE_URL = "https://bycard.by"
SESSION_API = "https://abws.bycard.by/api/v2/frame/session"

TZ = timezone(timedelta(hours=3))


class BycardParser(BaseParser):
    def fetch_schedule(self, session, date_obj):
        ts = self._date_to_timestamp(date_obj)
        url = f"{SCHEDULE_URL}?time={ts}"
        logger.info("Fetching schedule: %s", url)
        html = self._fetch_html(session, url)

        events = self._extract_jsonld_events(html, date_obj)
        movies = self._group_by_movie(events)

        for movie in movies:
            valid = []
            for sess in movie["sessions"]:
                sid = sess.pop("sid", None)
                if sid is not None:
                    time.sleep(self.delay)
                    time_str, hall, exists = self._fetch_session_hall(session, sid)
                    if not exists:
                        continue
                    if time_str:
                        sess["time"] = time_str
                    sess["hall"] = hall
                valid.append(sess)
            movie["sessions"] = valid

        return movies

    def _date_to_timestamp(self, date_obj):
        dt = datetime(date_obj.year, date_obj.month, date_obj.day, tzinfo=TZ)
        return int(dt.timestamp())

    def _extract_jsonld_events(self, html, target_date):
        date_prefix = target_date.strftime("%Y-%m-%d")
        soup = BeautifulSoup(html, "html.parser")
        events = []

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue

            if isinstance(data, dict):
                items = [data]
            elif isinstance(data, list):
                items = data
            else:
                continue

            for item in items:
                if item.get("@type") != "ScreeningEvent":
                    continue
                start_date = item.get("startDate", "")
                if not start_date.startswith(date_prefix):
                    continue

                sid_match = re.search(r"sid=(\d+)", item.get("@id", ""))
                events.append({
                    "name": item.get("name", ""),
                    "image": item.get("image"),
                    "startDate": start_date,
                    "detail_url": self._clean_detail_url(item.get("url", "")),
                    "sid": int(sid_match.group(1)) if sid_match else None,
                })

        return events

    def _clean_detail_url(self, url):
        parsed = urlparse(url)
        return parsed.path or url

    def _group_by_movie(self, events):
        movies = {}
        movie_order = []

        for event in events:
            name = event["name"]
            if name not in movies:
                movie_id = event["detail_url"].rstrip("/").split("/")[-1]
                movies[name] = {
                    "title": name,
                    "slug": movie_id,
                    "href": event["detail_url"],
                    "sessions": [],
                    "poster_url": event["image"],
                }
                movie_order.append(name)

            time_str = self._extract_time(event["startDate"])
            session_data = {"time": time_str}
            if event["sid"] is not None:
                session_data["sid"] = event["sid"]
            movies[name]["sessions"].append(session_data)

        return [movies[name] for name in movie_order]

    def _extract_time(self, start_date_str):
        idx = start_date_str.find("T")
        if idx == -1:
            return ""
        return start_date_str[idx + 1 : idx + 6]

    def _fetch_session_hall(self, session, sid):
        try:
            r = session.get(f"{SESSION_API}/{sid}", timeout=30)
            if r.status_code == 404:
                return (None, None, False)
            r.raise_for_status()
            data = r.json()
            time_str = data.get("timeSpendingTimeStr", "")
            hall_name = data.get("map", {}).get("hallName", "")
            hall_match = re.search(r"(\d+)", hall_name)
            hall = int(hall_match.group(1)) if hall_match else None
            return (time_str, hall, True)
        except Exception as e:
            logger.warning("Failed to fetch hall for session %s: %s", sid, e)
            return (None, None, True)

    def fetch_movie_detail(self, session, href):
        detail_url = urljoin(BASE_URL, href)
        html = self._fetch_html(session, detail_url)
        data = self._parse_jsonld_movie(html)
        if not data.get("country"):
            data["country"] = self._extract_country(html)
        return data

    def _parse_jsonld_movie(self, html):
        soup = BeautifulSoup(html, "html.parser")
        data = {}

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                item = json.loads(script.string)
            except (json.JSONDecodeError, TypeError):
                continue
            if isinstance(item, dict) and item.get("@type") == "Movie":
                data["title"] = item.get("name", "")
                data["poster_url"] = item.get("image")
                data["genres"] = item.get("genre", [])
                data["age"] = self._format_age(item.get("typicalAgeRange"))
                data["duration"] = self._format_duration(item.get("duration", ""))
                data["country"] = ""
                break

        return data

    def _format_age(self, age):
        if age is None:
            return ""
        return f"{age}+"

    def _format_duration(self, iso_duration):
        match = re.search(r"PT(\d+)M", iso_duration)
        if match:
            return f"{match.group(1)} мин"
        return ""

    def _extract_country(self, html):
        match = re.search(r"Страна:</strong>\s*([^<]+)", html)
        if match:
            return match.group(1).strip()
        return ""
