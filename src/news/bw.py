"""Business Wire RSS adapter.

BW publishes industry-filtered feeds via opaque hashed URLs (e.g.
?rss=G1QFDERJXkJeGVtRVQ==). The healthcare hash should be confirmed live
before relying on this feed for cross-ref; the default URL below is BW's
firehose, which is high-volume but reliable.

BW items are simpler than PRN — title, description, link, pubDate — so the
parser is correspondingly thin. Tickers come from body extraction.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import requests

from .parsers import extract_tickers, parse_pubdate, strip_html, strip_ns
from .types import NewsItem

log = logging.getLogger(__name__)

# Firehose; replace with the verified healthcare-only feed URL once known.
DEFAULT_FEED_URL = "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtRVQ=="
USER_AGENT = "sa-monitor/0.1 (+https://github.com/jroypeterson/sa-monitor)"
TIMEOUT_SEC = 10
SOURCE = "businesswire"


def parse(xml_bytes: bytes) -> list[NewsItem]:
    items: list[NewsItem] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log.error("bw feed: XML parse error: %s", e)
        return items

    for node in root.iter():
        if strip_ns(node.tag) != "item":
            continue

        fields: dict[str, str] = {}
        for child in node:
            name = strip_ns(child.tag)
            text = (child.text or "").strip()
            if name and text and name not in fields:
                fields[name] = text

        title = fields.get("title", "")
        link = fields.get("link", "") or fields.get("guid", "")
        body = strip_html(fields.get("description", ""))
        published = parse_pubdate(fields.get("pubDate", "")) or ""

        if not title or not link:
            log.debug("bw feed: skipping item missing title/link")
            continue

        items.append(NewsItem(
            source=SOURCE,
            title=title,
            body=body,
            url=link,
            published_at=published,
            tickers=extract_tickers(f"{title} {body}"),
            industries=(),  # BW doesn't expose taxonomy on the RSS item
            raw=fields,
        ))
    return items


def fetch(url: str = DEFAULT_FEED_URL, timeout: int = TIMEOUT_SEC) -> list[NewsItem]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    log.debug("bw feed: fetching %s", url)
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return parse(resp.content)
