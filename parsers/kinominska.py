"""Parser for kinominska.by cinema schedule pages."""

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseParser

BASE_URL = "https://kinominska.by"
OBJECT_ID = 17


class KinominskaParser(BaseParser):
    def fetch_schedule(self, session, date_obj):
        schedule_url = f"{BASE_URL}/objects/{OBJECT_ID}?filter__by_date={date_obj:%Y-%m-%d}"
        html = self._fetch_html(session, schedule_url)
        return self._parse_schedule(html)

    def _parse_schedule(self, html):
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
                    hall_text = spans[2].get_text(strip=True) if len(spans) > 2 else ""
                    hall_match = re.search(r"(\d+)", hall_text)
                    hall = int(hall_match.group(1)) if hall_match else None

                    sessions.append({"time": time_str, "hall": hall})

                if sessions:
                    movies.append({
                        "title": title,
                        "slug": slug,
                        "href": href,
                        "sessions": sessions,
                        "poster_url": None,
                    })
                current_head = None

        return movies

    def fetch_movie_detail(self, session, href):
        detail_url = urljoin(BASE_URL, href)
        html = self._fetch_html(session, detail_url)
        return self._parse_movie_detail(html)

    def _parse_movie_detail(self, html):
        soup = BeautifulSoup(html, "html.parser")
        data = {}

        title_el = soup.find("h2", class_="trending-text")
        data["title"] = title_el.get_text(strip=True) if title_el else ""

        poster_el = soup.select_one(".trailor-video .img-box img")
        if not poster_el:
            poster_el = soup.find("img", src=re.compile(r"/uploads/events/"))
        poster_url = None
        if poster_el:
            poster_url = poster_el.get("src") or poster_el.get("data-src")
            if poster_url and poster_url.startswith("/"):
                poster_url = urljoin(BASE_URL, poster_url)
        data["poster_url"] = poster_url

        genres = [g.get_text(strip=True) for g in soup.select(".movie-tag li.trending-list a")]
        data["genres"] = genres

        badge = soup.select_one(".text-detail .badge.bg-secondary")
        data["age"] = badge.get_text(strip=True) if badge else ""

        duration_el = soup.select_one(".text-detail .genres-info")
        data["duration"] = duration_el.get_text(strip=True) if duration_el else ""

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
