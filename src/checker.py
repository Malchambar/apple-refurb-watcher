from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

USER_AGENT = "apple-refurb-watcher/1.0 (+https://www.apple.com/shop/refurbished/mac)"
PARSER_SOURCES = ("json_ld", "html_cards", "json_feed")

RAM_PATTERN = re.compile(r"\b(\d+)\s*GB(?:\s*(?:unified\s*)?memory|\s*RAM)\b", re.IGNORECASE)
STORAGE_PATTERN = re.compile(r"\b(256GB|512GB|1TB|2TB|4TB|8TB)\s*SSD\b", re.IGNORECASE)
PRICE_PATTERN = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")
CHIP_PATTERN = re.compile(r"\b(M[1-9](?:\s*(?:Pro|Max|Ultra))?)\b", re.IGNORECASE)
CPU_CORES_PATTERN = re.compile(r"\b(\d+)\s*[- ]?core\s*CPU\b", re.IGNORECASE)
GPU_CORES_PATTERN = re.compile(r"\b(\d+)\s*[- ]?core\s*GPU\b", re.IGNORECASE)


@dataclass(frozen=True)
class ProductEntry:
    id: str
    title: str
    url: str
    price: str | None
    family: str | None
    chip: str | None
    cpu_cores: int | None
    gpu_cores: int | None
    memory: str | None
    storage: str | None
    raw_text: str
    source: str
    dwell_seconds: int | None = None


@dataclass(frozen=True)
class ParseResult:
    source: str
    products: list[ProductEntry]


def _normalize_title(text: str) -> str:
    return " ".join(text.split()).strip()


def _normalize_url(base_url: str, value: str | None) -> str:
    if not value:
        return ""
    return urljoin(base_url, value.strip())


def _stable_id(title: str, url: str, candidate_id: str | None = None) -> str:
    cleaned_candidate = (candidate_id or "").strip()
    if cleaned_candidate:
        return cleaned_candidate

    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if path:
        return path
    return f"{title}::{url}"


def _extract_memory(text: str) -> str | None:
    match = RAM_PATTERN.search(text)
    if not match:
        generic = re.search(r"\b(16|24|32|36|48|64|96|128)\s*GB\b", text, flags=re.IGNORECASE)
        if not generic:
            return None
        return f"{generic.group(1)}GB RAM"
    return f"{match.group(1)}GB RAM"


def _extract_storage(text: str) -> str | None:
    match = STORAGE_PATTERN.search(text)
    if match:
        return f"{match.group(1).upper()} SSD"

    generic = re.search(r"\b(256GB|512GB|1TB|2TB|4TB|8TB)\b", text, flags=re.IGNORECASE)
    if generic:
        return f"{generic.group(1).upper()} SSD"
    return None


def _extract_price_from_text(text: str) -> str | None:
    match = PRICE_PATTERN.search(text)
    if not match:
        return None
    return match.group(0).replace(" ", "")


def _extract_family(text: str) -> str | None:
    lowered = text.lower()
    if "mac studio" in lowered:
        return "Mac Studio"
    if "mac mini" in lowered:
        return "Mac mini"
    return None


def _extract_chip(text: str) -> str | None:
    match = CHIP_PATTERN.search(text)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _extract_cpu_cores(text: str) -> int | None:
    match = CPU_CORES_PATTERN.search(text)
    if not match:
        return None
    return int(match.group(1))


def _extract_gpu_cores(text: str) -> int | None:
    match = GPU_CORES_PATTERN.search(text)
    if not match:
        return None
    return int(match.group(1))


def _build_entry(
    *,
    base_url: str,
    title: str,
    url: str,
    price: str | None,
    raw_text: str,
    source: str,
    candidate_id: str | None = None,
) -> ProductEntry | None:
    normalized_title = _normalize_title(title)
    normalized_url = _normalize_url(base_url, url)
    if not normalized_title or not normalized_url:
        return None

    details_text = " ".join(part for part in [normalized_title, raw_text, price or ""] if part)
    family = _extract_family(details_text)
    chip = _extract_chip(details_text)
    cpu_cores = _extract_cpu_cores(details_text)
    gpu_cores = _extract_gpu_cores(details_text)
    memory = _extract_memory(details_text)
    storage = _extract_storage(details_text)
    normalized_price = (price or "").strip() or _extract_price_from_text(details_text)

    return ProductEntry(
        id=_stable_id(normalized_title, normalized_url, candidate_id=candidate_id),
        title=normalized_title,
        url=normalized_url,
        price=normalized_price,
        family=family,
        chip=chip,
        cpu_cores=cpu_cores,
        gpu_cores=gpu_cores,
        memory=memory,
        storage=storage,
        raw_text=_normalize_title(raw_text),
        source=source,
    )


def fetch_refurb_page(url: str, timeout: float) -> str:
    try:
        response = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": USER_AGENT},
        )
        response.raise_for_status()
        return response.text
    except requests.RequestException as exc:
        logger.exception("Failed to fetch Apple refurb page: %s", exc)
        raise


def _parse_json_text(value: str) -> Any | None:
    stripped = value.strip()
    if not stripped:
        return None

    if stripped.startswith("<!--"):
        stripped = stripped.replace("<!--", "").replace("-->", "").strip()

    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return None


def _discover_json_feed_urls(html: str, source_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    candidates: set[str] = set()

    attr_names = [
        "data-endpoint",
        "data-api-url",
        "data-url",
        "data-feed-url",
        "data-automodule-endpoint",
    ]
    for attr in attr_names:
        for node in soup.select(f"[{attr}]"):
            value = (node.get(attr) or "").strip()
            if value:
                candidates.add(_normalize_url(source_url, value))

    for script in soup.select('script[type="application/json"], script[type="application/ld+json"]'):
        text = script.get_text(" ", strip=True)
        if not text:
            continue
        for match in re.findall(r"['\"](https?://[^'\"]+|/[^'\"]+)['\"]", text):
            lowered = match.lower()
            if any(token in lowered for token in [".json", "api", "refurb", "inventory", "products"]):
                candidates.add(_normalize_url(source_url, match))

    filtered = [url for url in candidates if url.startswith("http")]
    return sorted(filtered)[:12]


def _as_price(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.startswith("$"):
            return text
        return _extract_price_from_text(text) or text
    if isinstance(value, (int, float)):
        return f"${value:,.2f}".rstrip("0").rstrip(".")
    return None


def _extract_price_from_object(payload: Any) -> str | None:
    if isinstance(payload, dict):
        for key in ["price", "currentPrice", "amount", "salePrice", "fullPrice", "value"]:
            if key in payload:
                priced = _as_price(payload.get(key))
                if priced:
                    return priced
        for key in ["offers", "pricing", "priceData"]:
            if key in payload:
                priced = _extract_price_from_object(payload.get(key))
                if priced:
                    return priced
    if isinstance(payload, list):
        for item in payload:
            priced = _extract_price_from_object(item)
            if priced:
                return priced
    return None


def _extract_entries_from_json(payload: Any, base_url: str, source: str) -> list[ProductEntry]:
    collected: list[ProductEntry] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            title = node.get("title") or node.get("name") or node.get("productName")
            url = node.get("url") or node.get("href") or node.get("productUrl") or node.get("link")
            if isinstance(title, str) and isinstance(url, str):
                normalized_candidate_url = _normalize_url(base_url, url)
                if "/shop/product/" not in normalized_candidate_url:
                    for value in node.values():
                        walk(value)
                    return
                entry = _build_entry(
                    base_url=base_url,
                    title=title,
                    url=url,
                    price=_extract_price_from_object(node),
                    raw_text=json.dumps(node, ensure_ascii=True),
                    source=source,
                    candidate_id=str(node.get("id") or node.get("sku") or node.get("partNumber") or "") or None,
                )
                if entry:
                    collected.append(entry)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)

    deduped: dict[str, ProductEntry] = {}
    for entry in collected:
        deduped[entry.id] = entry
    return list(deduped.values())


def try_fetch_json_feed(source_url: str, html: str, timeout: float) -> list[ProductEntry]:
    candidates = _discover_json_feed_urls(html, source_url)
    if not candidates:
        logger.info("Parser source attempt json_feed: no candidate feed URLs discovered.")
        return []

    logger.info("Parser source attempt json_feed: discovered %s candidate URL(s).", len(candidates))

    for candidate in candidates:
        try:
            response = requests.get(
                candidate,
                timeout=timeout,
                headers={
                    "User-Agent": USER_AGENT,
                    "Accept": "application/json,text/plain,*/*",
                },
            )
            if response.status_code >= 400:
                continue

            payload: Any | None = None
            content_type = (response.headers.get("content-type") or "").lower()
            body = response.text.strip()

            if "json" in content_type:
                payload = response.json()
            elif body.startswith("{") or body.startswith("["):
                payload = _parse_json_text(body)

            if payload is None:
                continue

            entries = _extract_entries_from_json(payload, base_url=source_url, source="json_feed")
            if entries:
                logger.info(
                    "Parser source selected: json_feed url=%s parsed_products=%s",
                    candidate,
                    len(entries),
                )
                return entries
        except Exception as exc:
            logger.debug("json_feed candidate failed url=%s error=%s", candidate, exc)

    logger.info("Parser source attempt json_feed: no usable structured products found.")
    return []


def _iter_nodes(value: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if isinstance(value, dict):
        nodes.append(value)
        for inner in value.values():
            nodes.extend(_iter_nodes(inner))
    elif isinstance(value, list):
        for item in value:
            nodes.extend(_iter_nodes(item))
    return nodes


def try_extract_json_ld(html: str, source_url: str) -> list[ProductEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[ProductEntry] = []

    for script in soup.select('script[type="application/ld+json"]'):
        payload = _parse_json_text(script.get_text(" ", strip=True))
        if payload is None:
            continue

        for node in _iter_nodes(payload):
            node_type = str(node.get("@type") or "").lower()
            if "product" not in node_type:
                continue

            title = node.get("name") or node.get("title")
            url = node.get("url")
            if not isinstance(title, str) or not isinstance(url, str):
                continue
            normalized_candidate_url = _normalize_url(source_url, url)
            if "/shop/product/" not in normalized_candidate_url:
                continue

            entry = _build_entry(
                base_url=source_url,
                title=title,
                url=url,
                price=_extract_price_from_object(node.get("offers") or node),
                raw_text=json.dumps(node, ensure_ascii=True),
                source="json_ld",
                candidate_id=str(node.get("sku") or node.get("productID") or node.get("mpn") or "") or None,
            )
            if entry:
                entries.append(entry)

    deduped: dict[str, ProductEntry] = {}
    for entry in entries:
        deduped[entry.id] = entry

    result = list(deduped.values())
    if result:
        logger.info("Parser source selected: json_ld parsed_products=%s", len(result))
    else:
        logger.info("Parser source attempt json_ld: no structured products found.")
    return result


def _extract_price_near_anchor(anchor: Any) -> str | None:
    card = anchor
    for _ in range(4):
        if card is None:
            break
        text = card.get_text(" ", strip=True)
        price = _extract_price_from_text(text)
        if price:
            return price
        card = card.parent
    return None


def try_extract_product_cards(html: str, source_url: str) -> list[ProductEntry]:
    soup = BeautifulSoup(html, "html.parser")
    entries: list[ProductEntry] = []

    selectors = ['a[href*="/shop/product/"]']

    for selector in selectors:
        for anchor in soup.select(selector):
            href = (anchor.get("href") or "").strip()
            title = _normalize_title(anchor.get_text(" ", strip=True))
            if not href or not title:
                continue
            if len(title) < 8:
                continue
            if "/shop/product/" not in _normalize_url(source_url, href):
                continue

            raw_text = _normalize_title(anchor.parent.get_text(" ", strip=True) if anchor.parent else title)
            entry = _build_entry(
                base_url=source_url,
                title=title,
                url=href,
                price=_extract_price_near_anchor(anchor),
                raw_text=raw_text,
                source="html_cards",
            )
            if entry:
                entries.append(entry)

    deduped: dict[str, ProductEntry] = {}
    for entry in entries:
        deduped[entry.id] = entry

    result = list(deduped.values())
    if result:
        logger.info("Parser source selected: html_cards parsed_products=%s", len(result))
    else:
        logger.info("Parser source attempt html_cards: no product cards found.")
    return result


def _build_source_order(preferred_source: str | None) -> list[str]:
    ordered = list(PARSER_SOURCES)
    if preferred_source in PARSER_SOURCES:
        ordered.remove(preferred_source)
        ordered.insert(0, preferred_source)
    return ordered


def _is_relevant_model(title: str, include_studio: bool) -> bool:
    lowered = title.lower()
    if "mac mini" in lowered:
        return True
    if include_studio and "mac studio" in lowered:
        return True
    return False


def _filter_relevant_products(products: list[ProductEntry], keywords: list[str]) -> list[ProductEntry]:
    include_studio = any("studio" in keyword.lower() for keyword in keywords)
    filtered = [item for item in products if _is_relevant_model(item.title, include_studio=include_studio)]

    deduped: dict[str, ProductEntry] = {}
    for item in filtered:
        deduped[item.id] = item
    return list(deduped.values())


def parse_products(
    html: str,
    source_url: str,
    timeout: float,
    preferred_source: str | None = None,
) -> ParseResult:
    source_order = _build_source_order(preferred_source)
    logger.info("Parser source order: %s", ", ".join(source_order))

    parser_map = {
        "json_feed": lambda: try_fetch_json_feed(source_url, html, timeout),
        "json_ld": lambda: try_extract_json_ld(html, source_url),
        "html_cards": lambda: try_extract_product_cards(html, source_url),
    }

    for source_name in source_order:
        parser = parser_map[source_name]
        try:
            products = parser()
            logger.info("Parser attempt: source=%s parsed_products=%s", source_name, len(products))
            if products:
                return ParseResult(source=source_name, products=products)
        except Exception as exc:
            logger.exception("Parser source %s failed: %s", source_name, exc)

    return ParseResult(source="none", products=[])


def check_refurb_listings(
    source_url: str,
    keywords: list[str],
    timeout: float,
    preferred_source: str | None = None,
) -> ParseResult:
    html = fetch_refurb_page(source_url, timeout=timeout)
    parse_result = parse_products(
        html,
        source_url=source_url,
        timeout=timeout,
        preferred_source=preferred_source,
    )
    relevant_products = _filter_relevant_products(parse_result.products, keywords)

    logger.info(
        "Parser summary: source=%s total_products=%s relevant_products=%s include_studio=%s",
        parse_result.source,
        len(parse_result.products),
        len(relevant_products),
        any("studio" in keyword.lower() for keyword in keywords),
    )

    return ParseResult(source=parse_result.source, products=relevant_products)
