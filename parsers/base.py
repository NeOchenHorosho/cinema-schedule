"""Base parser interface for cinema schedule sources."""

import logging
from abc import ABC, abstractmethod

import requests

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    def __init__(self, delay=1.0):
        self.delay = delay

    @abstractmethod
    def fetch_schedule(self, session, date_obj):
        """Return movies with sessions for the given date.

        Each movie dict:
            title: str
            slug: str              # unique identifier (URL slug or movie ID)
            href: str              # detail page path
            sessions: [{"time": "HH:MM", "hall": int|None}, ...]
            poster_url: str|None   # from schedule page if available
        """
        ...

    @abstractmethod
    def fetch_movie_detail(self, session, href):
        """Return metadata for one movie.

        Returns dict with at least:
            title, poster_url, genres, age, duration, country
        """
        ...

    def _fetch_html(self, session, url):
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
