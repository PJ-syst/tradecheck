import unittest
import xml.etree.ElementTree as ET

from backend.news import NewsAggregator, strip_html


def make_rss(items):
    root = ET.Element("rss")
    channel = ET.SubElement(root, "channel")
    for it in items:
        item = ET.SubElement(channel, "item")
        ET.SubElement(item, "title").text = it.get("title", "")
        ET.SubElement(item, "description").text = it.get("description", "")
        ET.SubElement(item, "pubDate").text = it.get("pubDate", "Mon, 01 Jan 2024 00:00:00 GMT")
        ET.SubElement(item, "link").text = it.get("link", "https://a.test/1")
        ET.SubElement(item, "guid").text = it.get("guid", "g1")
    return ET.tostring(root, encoding="unicode")


class NewsTests(unittest.TestCase):
    def test_strip_html_removes_tags(self):
        self.assertEqual(strip_html("<p>Hello <b>BTC</b></p>"), "Hello BTC")

    def test_aggregator_parses_rss_and_tags_assets(self):
        body = make_rss([{"title": "Bitcoin ETFs approved", "description": "BTC surge after ETF news", "link": "https://a.test/1"}])
        def fetch(url):
            return body
        agg = NewsAggregator(config={"feeds": [{"id": "coin", "url": "https://a.test/feed", "type": "rss"}]}, fetch=fetch, clock=lambda: 1705000000)
        result = agg.fetch_all()
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["assets"], ["BTC"])
        self.assertEqual(result["items"][0]["relevance"], "asset-specific")

    def test_aggregator_rejects_http_links_for_security(self):
        body = make_rss([{"title": "bad", "link": "http://a.test/1"}])
        def fetch(url):
            return body
        agg = NewsAggregator(config={"feeds": [{"id": "coin", "url": "https://a.test/feed", "type": "rss"}]}, fetch=fetch, clock=lambda: 1705000000)
        result = agg.fetch_all()
        self.assertEqual(len(result["items"]), 0)

    def test_aggregator_unsupported_feed_type(self):
        agg = NewsAggregator(config={"feeds": [{"id": "x", "url": "https://a.test/feed", "type": "atom"}]}, fetch=None, clock=lambda: 1)
        result = agg.fetch_all()
        self.assertEqual(result["feed_status"][0]["status"], "unsupported_type")


if __name__ == "__main__":
    unittest.main()
