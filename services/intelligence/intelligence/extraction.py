"""Conservative JSON-LD Product extraction; never guess missing commercial facts."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
import json
import re


@dataclass(frozen=True)
class ProductCandidate:
    title: str
    sku: str | None
    currency: str | None
    price_minor: int | None


class JsonLdParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.documents = []
        self.buffer = None

    def handle_starttag(self, tag, attrs):
        if tag == "script" and (dict(attrs).get("type") or "").lower() == "application/ld+json" and len(self.documents) < 20:
            self.buffer = []

    def handle_data(self, data):
        if self.buffer is not None:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.buffer is not None:
            self.documents.append("".join(self.buffer))
            self.buffer = None


def price(offer):
    if not isinstance(offer, dict) or offer.get("@type") != "Offer":
        return None, None
    currency = offer.get("priceCurrency")
    if currency not in ("COP", "USD", "EUR"):
        return None, None
    raw = offer.get("price")
    if isinstance(raw, bool) or not isinstance(raw, (str, int, Decimal)):
        return currency, None
    try:
        if not re.fullmatch(r"\d{1,13}(?:\.\d{1,2})?", str(raw)):
            return currency, None
        minor = Decimal(str(raw)) * 100
        if minor != minor.to_integral_value() or minor > 10**15:
            return currency, None
        return currency, int(minor)
    except InvalidOperation:
        return currency, None


def extract_products(body: bytes) -> tuple[ProductCandidate, ...]:
    if len(body) > 524288:
        raise ValueError("HTML exceeds limit")
    parser = JsonLdParser()
    parser.feed(body.decode("utf-8-sig", errors="strict"))
    result = []
    for document in parser.documents:
        try:
            data = json.loads(document, parse_float=Decimal)
        except (ValueError, RecursionError):
            continue
        nodes = data if isinstance(data, list) else [data]
        if isinstance(data, dict) and isinstance(data.get("@graph"), list):
            nodes = [data] + data["@graph"]
        for node in nodes[:100]:
            if not isinstance(node, dict):
                continue
            kind = node.get("@type")
            if kind != "Product" and not (isinstance(kind, list) and "Product" in kind):
                continue
            title = node.get("name")
            if not isinstance(title, str) or not title.strip() or len(title) > 300 or any(ord(c) < 32 for c in title):
                continue
            sku = node.get("sku")
            if not isinstance(sku, str) or not sku.strip() or len(sku) > 128 or any(ord(c) < 32 for c in sku):
                sku = None
            currency, minor = price(node.get("offers"))
            candidate = ProductCandidate(title.strip(), sku, currency, minor)
            if candidate not in result:
                result.append(candidate)
            if len(result) >= 100:
                return tuple(result)
    return tuple(result)
