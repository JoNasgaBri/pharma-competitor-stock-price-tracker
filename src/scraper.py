"""Modular HTTP scraper with pagination, realistic headers, and rate-limiting.

Extracts pharmacy product cards from paginated HTML category pages (either the
built-in local sandbox catalog server or any authorized static-HTML pharmacy portal)
and persists raw records to ``data/raw_products.json`` to keep the network layer
isolated from downstream transformation.
"""

from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
}

DEFAULT_CATEGORY_PATHS: list[str] = [
    "/categoria/medicamentos-genericos",
    "/categoria/vitaminas",
    "/categoria/dermocosmeticos",
]


@dataclass(frozen=True)
class SelectorConfig:
    """CSS selectors used to parse static HTML pharmacy product listings."""

    product_card: str = "article.product-card"
    sku_attr: str = "data-sku"
    title: str = ".product-title"
    link: str = "a.product-link"
    active_ingredient: str = ".product-active-ingredient"
    brand: str = ".product-brand"
    category: str = ".product-category"
    price_from: str = ".price-list"
    price_to: str = ".price-sale"
    installment: str = ".price-installment"
    availability: str = ".stock-status"
    next_page: str = "a.pagination-next"


def _extract_text(parent: Tag, selector: str) -> str | None:
    node = parent.select_one(selector)
    if node is None:
        return None
    text = " ".join(node.get_text(" ", strip=True).split())
    return text or None


def _fallback_sku(product_url: str, title: str) -> str:
    digest = hashlib.sha1(f"{product_url}|{title}".encode("utf-8")).hexdigest()[:10]
    return f"SKU-{digest.upper()}"


def _parse_json_ld_products(
    soup: BeautifulSoup, page_url: str, fallback_category: str, scraped_at: str
) -> list[dict[str, Any]]:
    """Fallback parser for external portals exposing Schema.org JSON-LD Product data."""
    records: list[dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue

        candidates: list[dict[str, Any]] = []
        if isinstance(payload, list):
            candidates.extend(item for item in payload if isinstance(item, dict))
        elif isinstance(payload, dict):
            if payload.get("@type") == "ItemList" and isinstance(
                payload.get("itemListElement"), list
            ):
                for entry in payload["itemListElement"]:
                    if isinstance(entry, dict):
                        item = entry.get("item", entry)
                        if isinstance(item, dict):
                            candidates.append(item)
            else:
                candidates.append(payload)

        for item in candidates:
            if item.get("@type") != "Product":
                continue
            offers = item.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            name = str(item.get("name", "")).strip()
            url = urljoin(page_url, str(item.get("url", page_url)))
            sku = str(item.get("sku") or _fallback_sku(url, name)).strip()
            brand_obj = item.get("brand")
            brand = (
                brand_obj.get("name")
                if isinstance(brand_obj, dict)
                else (str(brand_obj) if brand_obj else None)
            )
            avail_raw = str(offers.get("availability", ""))
            availability = (
                "Em estoque" if "InStock" in avail_raw else "Indisponível"
            )
            records.append(
                {
                    "sku": sku,
                    "product_name": name,
                    "active_ingredient": None,
                    "brand": brand,
                    "category": fallback_category,
                    "price_from_raw": (
                        str(offers.get("highPrice"))
                        if offers.get("highPrice") is not None
                        else None
                    ),
                    "price_to_raw": (
                        str(offers.get("price"))
                        if offers.get("price") is not None
                        else None
                    ),
                    "installment_raw": None,
                    "availability_raw": availability,
                    "product_url": url,
                    "source_page_url": page_url,
                    "scraped_at": scraped_at,
                }
            )
    return records


def parse_category_page(
    html_text: str,
    page_url: str,
    base_url: str,
    selectors: SelectorConfig,
    fallback_category: str = "Geral",
) -> tuple[list[dict[str, Any]], str | None]:
    """Parse product cards and optional next-page URL from an HTML category page."""
    soup = BeautifulSoup(html_text, "html.parser")
    scraped_at = datetime.now(timezone.utc).isoformat()
    records: list[dict[str, Any]] = []

    cards = soup.select(selectors.product_card)
    for card in cards:
        title = _extract_text(card, selectors.title)
        if not title:
            continue

        link_node = card.select_one(selectors.link)
        href = link_node.get("href") if link_node else None
        product_url = urljoin(base_url, str(href)) if href else page_url

        sku_attr = card.get(selectors.sku_attr)
        sku = str(sku_attr).strip() if sku_attr else _fallback_sku(product_url, title)

        records.append(
            {
                "sku": sku,
                "product_name": title,
                "active_ingredient": _extract_text(card, selectors.active_ingredient),
                "brand": _extract_text(card, selectors.brand),
                "category": _extract_text(card, selectors.category) or fallback_category,
                "price_from_raw": _extract_text(card, selectors.price_from),
                "price_to_raw": _extract_text(card, selectors.price_to),
                "installment_raw": _extract_text(card, selectors.installment),
                "availability_raw": _extract_text(card, selectors.availability)
                or "Indisponível",
                "product_url": product_url,
                "source_page_url": page_url,
                "scraped_at": scraped_at,
            }
        )

    if not records:
        records = _parse_json_ld_products(soup, page_url, fallback_category, scraped_at)

    next_node = soup.select_one(selectors.next_page)
    next_href = next_node.get("href") if next_node else None
    next_url = urljoin(page_url, str(next_href)) if next_href else None
    return records, next_url


def _fetch_with_retries(
    client: httpx.Client, url: str, max_retries: int = 3
) -> httpx.Response:
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = client.get(url)
            if response.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(
                    f"Transient HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt == max_retries:
                break
            backoff = min(4.0, 0.5 * (2 ** (attempt - 1)))
            logger.warning(
                "Attempt %d/%d failed for %s (%s). Retrying in %.1fs...",
                attempt,
                max_retries,
                url,
                exc,
                backoff,
            )
            time.sleep(backoff)
    assert last_error is not None
    raise last_error


def scrape_catalog(
    base_url: str,
    category_paths: list[str] | None = None,
    output_path: Path | str = Path("data/raw_products.json"),
    selectors: SelectorConfig | None = None,
    min_delay: float = 1.0,
    max_delay: float = 2.0,
    max_pages_per_category: int = 20,
    timeout: float = 15.0,
) -> list[dict[str, Any]]:
    """Scrape paginated pharmacy category listings and save raw JSON records."""
    paths = category_paths or DEFAULT_CATEGORY_PATHS
    selector_cfg = selectors or SelectorConfig()
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    all_records: list[dict[str, Any]] = []
    request_count = 0

    with httpx.Client(
        headers=DEFAULT_HEADERS,
        timeout=timeout,
        follow_redirects=True,
    ) as client:
        for path in paths:
            category_label = path.rstrip("/").split("/")[-1].replace("-", " ").title()
            current_url: str | None = (
                path if path.startswith(("http://", "https://")) else urljoin(base_url, path)
            )
            visited: set[str] = set()
            page_num = 0

            while current_url and current_url not in visited and page_num < max_pages_per_category:
                if request_count > 0 and max_delay > 0:
                    delay = random.uniform(min_delay, max_delay)
                    logger.info("Rate-limiting: sleeping %.2fs before next page", delay)
                    time.sleep(delay)

                page_num += 1
                visited.add(current_url)
                logger.info("Fetching %s (page %d)", current_url, page_num)
                response = _fetch_with_retries(client, current_url)
                request_count += 1

                page_records, next_url = parse_category_page(
                    html_text=response.text,
                    page_url=str(response.url),
                    base_url=base_url,
                    selectors=selector_cfg,
                    fallback_category=category_label,
                )
                logger.info(
                    "Extracted %d product cards from %s", len(page_records), response.url
                )
                all_records.extend(page_records)
                current_url = next_url

    payload = {
        "metadata": {
            "base_url": base_url,
            "categories_scraped": paths,
            "total_raw_records": len(all_records),
            "extracted_at": datetime.now(timezone.utc).isoformat(),
        },
        "products": all_records,
    }
    output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info("Saved %d raw records to %s", len(all_records), output)
    return all_records
