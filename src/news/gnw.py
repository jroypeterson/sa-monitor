"""GlobeNewswire RSS adapter.

GNW publishes per-industry feeds. The healthcare URL below should be
verified — observed behavior was that the URL filter wasn't tight (returned
mixed-sector items). For Phase 2 first cut, use the URL as configured and
filter post-hoc by extracted ticker membership in the sa-monitor universe.

GNW exposes `<category>` and `<subject>` taxonomy tags which we surface as
industries.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import requests

from .parsers import extract_tickers, parse_pubdate, strip_html, strip_ns
from .types import NewsItem

log = logging.getLogger(__name__)

DEFAULT_FEED_URL = (
    "https://www.globenewswire.com/RssFeed/industry/9576-Health-Care/"
    "feedTitle/GlobeNewswire%20-%20Industry%20News%20on%20Health%20Care"
)
USER_AGENT = "sa-monitor/0.1 (+https://github.com/jroypeterson/sa-monitor)"
TIMEOUT_SEC = 10
SOURCE = "globenewswire"


def parse(xml_bytes: bytes) -> list[NewsItem]:
    items: list[NewsItem] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log.error("gnw feed: XML parse error: %s", e)
        return items

    for node in root.iter():
        if strip_ns(node.tag) != "item":
            continue

        fields: dict[str, str] = {}
        categories: list[str] = []
        subjects: list[str] = []
        for child in node:
            name = strip_ns(child.tag)
            text = (child.text or "").strip()
            if name == "category" and text:
                categories.append(text)
            elif name == "subject" and text:
                subjects.append(text)
            elif name and text and name not in fields:
                fields[name] = text

        title = fields.get("title", "")
        link = fields.get("link", "") or fields.get("guid", "")
        body = strip_html(fields.get("description", ""))
        published = parse_pubdate(fields.get("pubDate", "")) or ""

        if not title or not link:
            log.debug("gnw feed: skipping item missing title/link")
            continue

        items.append(NewsItem(
            source=SOURCE,
            title=title,
            body=body,
            url=link,
            published_at=published,
            tickers=extract_tickers(f"{title} {body}"),
            industries=tuple(categories + subjects),
            raw=fields,
        ))
    return items


def fetch(url: str = DEFAULT_FEED_URL, timeout: int = TIMEOUT_SEC) -> list[NewsItem]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    log.debug("gnw feed: fetching %s", url)
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return parse(resp.content)
