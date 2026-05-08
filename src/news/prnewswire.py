"""PR Newswire RSS adapter.

Default feed: healthcare-latest. PRN tags items with `<industry>` (e.g.
'Biotechnology', 'Pharmaceuticals') and `<subject>` codes ('PDT' = Products
& Services, 'TRI' = Clinical Trials, etc.). We surface those as `industries`
on NewsItem so cross-ref filtering can use them.

Tickers are not in a structured field on PRN — extracted from body via
shared exchange-prefix regex.
"""
from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

import requests

from .parsers import extract_tickers, parse_pubdate, strip_html, strip_ns
from .types import NewsItem

log = logging.getLogger(__name__)

DEFAULT_FEED_URL = "https://www.prnewswire.com/rss/health-latest-news/health-latest-news-list.rss"
USER_AGENT = "sa-monitor/0.1 (+https://github.com/jroypeterson/sa-monitor)"
TIMEOUT_SEC = 10
SOURCE = "prnewswire"


def parse(xml_bytes: bytes) -> list[NewsItem]:
    items: list[NewsItem] = []
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as e:
        log.error("prn feed: XML parse error: %s", e)
        return items

    for node in root.iter():
        if strip_ns(node.tag) != "item":
            continue

        fields: dict[str, str] = {}
        industries: list[str] = []
        for child in node:
            name = strip_ns(child.tag)
            text = (child.text or "").strip()
            if name == "industry" and text:
                industries.append(text)
            elif name and text and name not in fields:
                fields[name] = text

        title = fields.get("title", "")
        link = fields.get("link", "") or fields.get("guid", "")
        body = strip_html(fields.get("description", "") or fields.get("content", ""))
        published = parse_pubdate(fields.get("pubDate", "")) or ""

        if not title or not link:
            log.debug("prn feed: skipping item missing title/link")
            continue

        items.append(NewsItem(
            source=SOURCE,
            title=title,
            body=body,
            url=link,
            published_at=published,
            tickers=extract_tickers(f"{title} {body}"),
            industries=tuple(industries),
            raw=fields,
        ))
    return items


def fetch(url: str = DEFAULT_FEED_URL, timeout: int = TIMEOUT_SEC) -> list[NewsItem]:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    }
    log.debug("prn feed: fetching %s", url)
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return parse(resp.content)
