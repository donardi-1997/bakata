"""Single-page research operation; not registered as a live source."""
from .transport import Fetcher
from .extraction import ProductCandidate, extract_products


def research_page(fetcher: Fetcher, url: str) -> tuple[ProductCandidate, ...]:
    return extract_products(fetcher.fetch(url).body)
