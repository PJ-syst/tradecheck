"""Bounded financial-news ingestion from configured RSS/Atom feeds.

The aggregator treats publisher text as untrusted evidence. It strips active
HTML, rejects arbitrary fetch targets, and never follows embedded instructions.
No feed is enabled by default: configure sources in data/news-config.json.
"""

import html
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from backend.market import PAIRS

DEFAULT_ASSETS = ["BNB", "BTC", "ETH"]
MAX_BODY_BYTES = 524288
DEFAULT_TIMEOUT = 10


class NewsError(ValueError):
    pass


def strip_html(value):
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<[^>]+>", " ", value)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def parse_rfc822(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    # Try common RSS date formats
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z",
                "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue
    return None


def canonical_link(link):
    if not isinstance(link, str):
        return None
    try:
        parsed = urlparse(link.strip())
    except ValueError:
        return None
    if parsed.scheme not in {"https"}:
        return None
    if not parsed.netloc or "." not in parsed.netloc:
        return None
    # Drop common tracking/query noise; keep path
    return f"{parsed.scheme}://{parsed.netloc.lower()}{parsed.path}"


def extract_assets(text, assets):
    if not text:
        return []
    lower = text.lower()
    found = []
    for asset in assets:
        # Match whole word; BTC also matches "bitcoin" only if configured as tag
        aliases = {"BTC": "bitcoin", "ETH": "ethereum", "BNB": "binance coin"}
        if re.search(rf"\b({re.escape(asset.lower())}|{re.escape(aliases.get(asset, asset.lower()))})\b", lower):
            found.append(asset)
    return sorted(set(found))


def fetch_url(url, timeout=DEFAULT_TIMEOUT):
    if not isinstance(url, str):
        raise NewsError("Invalid URL.")
    parsed = urlparse(url)
    if parsed.scheme not in {"https"}:
        raise NewsError("Only HTTPS feeds are allowed.")
    if not parsed.netloc or "." not in parsed.netloc:
        raise NewsError("Invalid feed host.")
    request = Request(url, headers={"Accept": "application/rss+xml, application/xml, text/xml", "User-Agent": "TradeCheck/0.3"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_BODY_BYTES + 1)
            if len(body) > MAX_BODY_BYTES:
                raise NewsError("Feed body too large.")
            return body.decode("utf-8", errors="replace")
    except (HTTPError, URLError, OSError, UnicodeDecodeError) as exc:
        raise NewsError(f"Feed unavailable: {exc}") from exc


def parse_rss(body, feed_id, assets, clock):
    try:
        root = ET.fromstring(body.encode("utf-8"))
    except ET.ParseError as exc:
        raise NewsError(f"Invalid RSS/Atom feed: {exc}") from exc
    channel = root.find("channel") if root.tag == "rss" else root
    if channel is None:
        raise NewsError("No channel element found.")
    items = []
    seen = set()
    now = clock()
    for item in channel.findall("item"):
        title = strip_html(item.findtext("title", default=""))
        link = canonical_link(item.findtext("link", default=""))
        if not link:
            continue
        if link in seen:
            continue
        seen.add(link)
        pub_text = item.findtext("pubDate", default="") or item.findtext("pub_date", default="") or item.findtext("published", default="")
        pub_ts = parse_rfc822(pub_text)
        if pub_ts is None:
            continue
        # Reject implausible future dates (>1h ahead)
        if pub_ts > now + 3600:
            continue
        desc = strip_html(item.findtext("description", default=""))
        summary = (desc[:400] + "...") if len(desc) > 400 else desc
        matched = extract_assets(f"{title} {summary}", assets)
        items.append({
            "id": f"news-{feed_id}-{hashlib.sha256(link.encode()).hexdigest()[:16]}",
            "source": feed_id,
            "publisher": (channel.findtext("title", default=feed_id))[:80],
            "headline": title[:200],
            "canonical_url": link,
            "published_at": pub_ts,
            "retrieved_at": now,
            "summary": summary,
            "assets": matched,
            "relevance": "asset-specific" if matched else "broad",
        })
    return items


class NewsAggregator:
    def __init__(self, config=None, fetch=None, clock=None):
        self.config = config or {}
        self.fetch = fetch or fetch_url
        self.clock = clock or time.time
        self.assets = self.config.get("asset_tags", DEFAULT_ASSETS)
        self.feeds = self.config.get("feeds", [])
        self.max_items = self.config.get("max_items", 30)

    def fetch_all(self):
        results = []
        feed_status = []
        for feed in self.feeds:
            feed_id = feed.get("id") or feed.get("url", "")
            feed_type = feed.get("type", "rss")
            if feed_type != "rss":
                feed_status.append({"id": feed_id, "status": "unsupported_type"})
                continue
            try:
                body = self.fetch(feed["url"])
                items = parse_rss(body, feed_id, self.assets, self.clock)
                feed_status.append({"id": feed_id, "status": "ok", "items": len(items)})
                results.extend(items)
            except NewsError as exc:
                feed_status.append({"id": feed_id, "status": "error", "error": str(exc)})
        # Deduplicate across feeds by canonical link
        seen = {}
        for item in results:
            if item["canonical_url"] not in seen:
                seen[item["canonical_url"]] = item
        deduped = sorted(seen.values(), key=lambda x: x["published_at"], reverse=True)[:self.max_items]
        return {"items": deduped, "feed_status": feed_status, "retrieved_at": self.clock()}

    def evidence_for_assets(self, assets):
        all_news = self.fetch_all()
        return {
            **all_news,
            "items": [i for i in all_news["items"] if any(a in assets for a in i["assets"])
                      and 0 <= self.clock() - i["published_at"] <= 72 * 3600],
        }
