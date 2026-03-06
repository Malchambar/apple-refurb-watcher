from __future__ import annotations

import logging
from dataclasses import dataclass
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProductEntry:
    title: str
    url: str


def _normalize_title(text: str) -> str:
    return " ".join(text.split()).strip()


def _matches_keywords(title: str, keywords: list[str]) -> bool:
    lowered = title.lower()
    return any(keyword.lower() in lowered for keyword in keywords)


def fetch_refurb_page(url: str, timeout: float) -> str:
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "apple-refurb-watcher/1.0 (+https://www.apple.com/shop/refurbished/mac)"
            },
        )
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        logger.exception("Failed to fetch Apple refurb page: %s", exc)
        raise


def parse_products(html: str, source_url: str, keywords: list[str]) -> list[ProductEntry]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        matches: list[ProductEntry] = []
        seen: set[tuple[str, str]] = set()

        for anchor in soup.select("a[href]"):
            raw_title = anchor.get_text(" ", strip=True)
            title = _normalize_title(raw_title)
            if not title:
                continue
            if not _matches_keywords(title, keywords):
                continue

            product_url = urljoin(source_url, anchor.get("href", ""))
            key = (title, product_url)
            if key in seen:
                continue

            seen.add(key)
            matches.append(ProductEntry(title=title, url=product_url))

        return matches
    except Exception as exc:
        logger.exception("Failed to parse Apple refurb page: %s", exc)
        raise


def check_refurb_listings(
    source_url: str, keywords: list[str], timeout: float
) -> list[ProductEntry]:
    html = fetch_refurb_page(source_url, timeout=timeout)
    products = parse_products(html, source_url=source_url, keywords=keywords)
    logger.info(
        "Parsed %s matching product(s) for keywords: %s",
        len(products),
        ", ".join(keywords),
    )
    return products
