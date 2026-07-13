"""Parser selection based on SCHEDULE_PARSER environment variable."""

from .bycard import BycardParser
from .kinominska import KinominskaParser


def get_parser(parser_name="kinominska", delay=1.0):
    if parser_name == "bycard":
        return BycardParser(delay=delay)
    return KinominskaParser(delay=delay)
