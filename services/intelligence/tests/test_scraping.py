import json
import socket
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from intelligence.transport import Fetcher, SourcePolicy, Response, FetchError, PolicyError, public_ip
from intelligence.extraction import extract_products
from intelligence.engine import research_page


class TransportTests(unittest.TestCase):
    def setUp(self):
        self.policy = SourcePolicy("catalog.invalid", True,
            "User-agent: *\nDisallow: /private\nCrawl-delay: 3",
            datetime.now(timezone.utc) + timedelta(hours=1))
        self.now = 0
        self.calls = []
        self.responses = []
        self.url = "https://catalog.invalid/product"

    def sleep(self, seconds):
        self.now += seconds

    def transport(self, url, host, timeout, max_bytes):
        self.calls.append((url, self.now))
        return self.responses.pop(0)

    def fetcher(self, policy=None):
        return Fetcher(policy or self.policy, self.transport, lambda: self.now, self.sleep)

    def test_policy_denies_before_transport(self):
        for url in ("http://catalog.invalid/product", "https://evil.invalid/product",
                    "https://catalog.invalid:8443/product", "https://catalog.invalid/private/a",
                    "https://user@catalog.invalid/product", "https://catalog.invalid/\\" ):
            with self.subTest(url=url), self.assertRaises(PolicyError):
                self.fetcher().fetch(url)
        for policy in (replace(self.policy, terms_approved=False),
                       replace(self.policy, robots_valid_until=datetime.now(timezone.utc) - timedelta(seconds=1)),
                       replace(self.policy, robots_text="")):
            with self.assertRaises(PolicyError):
                self.fetcher(policy).fetch(self.url)
        self.assertEqual(self.calls, [])

    def test_dns_denies_nonpublic_and_mixed(self):
        def resolver(*ips):
            return lambda *a, **kw: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip,443)) for ip in ips]
        for ips in (("127.0.0.1",), ("169.254.169.254",), ("10.0.0.1",),
                    ("8.8.8.8", "192.168.0.1"), ("::ffff:8.8.8.8",), ("224.0.0.1",), ()):
            with self.subTest(ips=ips), self.assertRaises(PolicyError):
                public_ip("catalog.invalid", resolver(*ips))
        self.assertEqual(public_ip("catalog.invalid", resolver("8.8.8.8")), "8.8.8.8")

    def test_rate_limit_and_retry_after(self):
        ok = Response(200, {"content-type":"text/html"}, b"ok")
        self.responses = [Response(429, {"retry-after":"5"}, b""), ok, ok]
        fetcher = self.fetcher()
        self.assertEqual(fetcher.fetch(self.url), ok)
        fetcher.fetch(self.url)
        self.assertEqual([t for _,t in self.calls], [0,5,8])

    def test_redirect_revalidated(self):
        self.responses = [Response(302, {"location":"https://evil.invalid/a"}, b"")]
        with self.assertRaises(PolicyError):
            self.fetcher().fetch(self.url)
        self.assertEqual(len(self.calls), 1)

    def test_response_limits_and_deferral(self):
        for response in (Response(429, {"retry-after":"600"}, b""),
                         Response(403, {}, b""),
                         Response(200, {"content-type":"application/json"}, b"{}"),
                         Response(200, {"content-type":"text/html"}, b"x"*524289)):
            self.responses = [response]
            with self.assertRaises(FetchError):
                self.fetcher().fetch(self.url)

    def test_end_to_end_synthetic_page(self):
        html = b'<script type="application/ld+json">{"@type":"Product","name":"Fixture","sku":"demo","offers":{"@type":"Offer","priceCurrency":"COP","price":"1000"}}</script>'
        self.responses = [Response(200, {"content-type":"text/html"}, html)]
        candidates = research_page(self.fetcher(), self.url)
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].price_minor, 100000)

    def test_retry_budget(self):
        self.responses = [Response(503, {}, b"")]*3
        with self.assertRaises(FetchError):
            self.fetcher().fetch(self.url)
        self.assertEqual(len(self.calls), 3)


class ExtractionTests(unittest.TestCase):
    def html(self, data):
        return ('<script type="application/ld+json">'+json.dumps(data)+'</script>').encode()

    def test_exact_price_and_graph(self):
        item = {"@type":"Product","name":"Fixture","sku":"abc",
                "offers":{"@type":"Offer","priceCurrency":"COP","price":"49900.25"}}
        result = extract_products(self.html({"@graph":[item,item]}))
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].price_minor,4990025)
        self.assertEqual(result[0].sku,"abc")

    def test_ambiguous_price_is_unknown(self):
        for offer in ({"@type":"AggregateOffer","lowPrice":"10","priceCurrency":"COP"},
                      {"@type":"Offer","priceCurrency":"COP","price":"1.001"},
                      {"@type":"Offer","priceCurrency":"XXX","price":"10"},
                      {"@type":"Offer","priceCurrency":"COP","price":True},
                      [{"@type":"Offer","priceCurrency":"COP","price":"10"}]):
            result=extract_products(self.html({"@type":"Product","name":"Fixture","offers":offer}))
            self.assertIsNone(result[0].price_minor)
            self.assertIsNone(result[0].sku)

    def test_invalid_and_oversized_html(self):
        self.assertEqual(extract_products(b'<script type></script><script type="application/ld+json">{bad</script>'), ())
        with self.assertRaises(ValueError):
            extract_products(b'x'*524289)
