"""Extract prices and listing facts from fetched HTML.

Structured data first (JSON-LD `Product`/`Offer`, then Open Graph and common microdata),
falling back to text patterns only when a page carries no structured markup. Structured
markup is what the site itself declares its price to be, which is far safer than picking the
largest number on the page.

A page that yields no confident price yields nothing. There is no "best guess" path.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from selectolax.parser import HTMLParser

from app.core.logging import get_logger

log = get_logger(__name__)

CURRENCY_SYMBOLS = {
    "LKR": ("lkr", "rs.", "rs ", "රු"),
    "USD": ("usd", "$"),
    "EUR": ("eur", "€"),
    "GBP": ("gbp", "£"),
    "INR": ("inr", "₹"),
    "AED": ("aed",),
    "JPY": ("jpy", "¥"),
}

# A price with thousands separators and an optional decimal part.
_PRICE_PATTERN = re.compile(r"(?<![\d.,])(\d{1,3}(?:[ ,]\d{3})+(?:\.\d{1,2})?|\d{4,9}(?:\.\d{1,2})?)(?![\d])")
_MILEAGE_PATTERN = re.compile(r"(\d{1,3}(?:[,\s]?\d{3})*)\s*(?:km|kilometers|kilometres)", re.I)
_YEAR_PATTERN = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")

_UNAVAILABLE_MARKERS = (
    "out of stock", "sold out", "no longer available", "discontinued", "call for price",
    "price on request", "poa", "contact for price",
)


@dataclass
class ParsedListing:
    title: str | None = None
    price: float | None = None
    currency: str | None = None
    availability: str | None = None
    year: int | None = None
    mileage_km: int | None = None
    excerpt: str | None = None
    source_kind: str = "unknown"  # jsonld | microdata | opengraph | text

    @property
    def has_price(self) -> bool:
        return self.price is not None and self.price > 0


def _to_number(raw: str | float | int | None) -> float | None:
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw) if raw > 0 else None

    cleaned = re.sub(r"[^\d.,]", "", str(raw)).strip()
    if not cleaned:
        return None

    # Disambiguate 1.234,56 (European) from 1,234.56 (Anglo) by which separator is last.
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        parts = cleaned.split(",")
        # A trailing group of exactly two digits is a decimal; three is a thousands group.
        cleaned = (
            cleaned.replace(",", ".") if len(parts[-1]) == 2 else cleaned.replace(",", "")
        )

    try:
        value = float(cleaned)
    except ValueError:
        return None
    return value if value > 0 else None


def detect_currency(text: str, default: str | None = None) -> str | None:
    lowered = text.lower()
    for code, markers in CURRENCY_SYMBOLS.items():
        if code.lower() in lowered or any(marker in lowered for marker in markers):
            return code
    return default


def _walk_jsonld(node: object) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, dict):
        found.append(node)
        for value in node.values():
            found.extend(_walk_jsonld(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_walk_jsonld(item))
    return found


def _from_jsonld(tree: HTMLParser) -> ParsedListing | None:
    for script in tree.css('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.text())
        except (json.JSONDecodeError, ValueError):
            continue

        for node in _walk_jsonld(data):
            offers = node.get("offers")
            if not offers:
                continue
            offer = offers[0] if isinstance(offers, list) and offers else offers
            if not isinstance(offer, dict):
                continue

            price = _to_number(offer.get("price") or offer.get("lowPrice"))
            if price is None:
                continue

            availability = offer.get("availability")
            return ParsedListing(
                title=str(node.get("name") or "").strip() or None,
                price=price,
                currency=(offer.get("priceCurrency") or "").upper() or None,
                availability=(
                    str(availability).rsplit("/", 1)[-1] if availability else None
                ),
                source_kind="jsonld",
            )
    return None


def _from_microdata(tree: HTMLParser) -> ParsedListing | None:
    node = tree.css_first('[itemprop="price"]')
    if node is None:
        return None

    price = _to_number(node.attributes.get("content") or node.text())
    if price is None:
        return None

    currency_node = tree.css_first('[itemprop="priceCurrency"]')
    currency = None
    if currency_node is not None:
        currency = (currency_node.attributes.get("content") or currency_node.text() or "").upper()

    title_node = tree.css_first('[itemprop="name"]') or tree.css_first("h1")
    return ParsedListing(
        title=title_node.text(strip=True) if title_node else None,
        price=price,
        currency=currency or None,
        source_kind="microdata",
    )


def _from_opengraph(tree: HTMLParser) -> ParsedListing | None:
    amount_node = tree.css_first('meta[property="product:price:amount"]')
    if amount_node is None:
        return None

    price = _to_number(amount_node.attributes.get("content"))
    if price is None:
        return None

    currency_node = tree.css_first('meta[property="product:price:currency"]')
    title_node = tree.css_first('meta[property="og:title"]')
    return ParsedListing(
        title=(title_node.attributes.get("content") if title_node else None),
        price=price,
        currency=(
            (currency_node.attributes.get("content") or "").upper() if currency_node else None
        ),
        source_kind="opengraph",
    )


def _from_text(tree: HTMLParser, expected_currency: str | None) -> ParsedListing | None:
    """Last resort. Only trusted when a currency marker sits next to the number.

    Without that adjacency almost any figure on a page — a part number, a phone number, a
    year — can be misread as a price, which is exactly how fabricated data enters a system.
    """
    body = tree.body
    if body is None:
        return None

    text = " ".join(body.text(separator=" ", strip=True).split())[:8000]
    currency = detect_currency(text, expected_currency)
    if currency is None:
        return None

    markers = (currency.lower(), *CURRENCY_SYMBOLS.get(currency, ()))
    candidates: list[float] = []

    for match in _PRICE_PATTERN.finditer(text):
        window = text[max(0, match.start() - 20) : match.end() + 12].lower()
        if any(marker in window for marker in markers):
            value = _to_number(match.group(1))
            if value and value >= 100:
                candidates.append(value)

    if not candidates:
        return None

    title_node = tree.css_first("h1") or tree.css_first("title")
    return ParsedListing(
        title=title_node.text(strip=True)[:400] if title_node else None,
        # The lowest currency-adjacent figure is typically the item price rather than a
        # bundle, a total including shipping, or a crossed-out "was" price.
        price=min(candidates),
        currency=currency,
        excerpt=text[:400],
        source_kind="text",
    )


def parse_listing(html: str, *, expected_currency: str | None = None) -> ParsedListing | None:
    if not html or len(html) < 100:
        return None

    try:
        tree = HTMLParser(html)
    except Exception as exc:  # noqa: BLE001
        log.debug("parser.html_failed", error=str(exc))
        return None

    listing = (
        _from_jsonld(tree)
        or _from_microdata(tree)
        or _from_opengraph(tree)
        or _from_text(tree, expected_currency)
    )
    if listing is None:
        return None

    body_text = ""
    if tree.body is not None:
        body_text = " ".join(tree.body.text(separator=" ", strip=True).split())[:4000]

    if listing.currency is None:
        listing.currency = detect_currency(body_text, expected_currency)

    lowered = body_text.lower()
    if any(marker in lowered for marker in _UNAVAILABLE_MARKERS):
        listing.availability = listing.availability or "OutOfStock"

    year_match = _YEAR_PATTERN.search(listing.title or "") or _YEAR_PATTERN.search(body_text[:600])
    if year_match:
        listing.year = int(year_match.group(1))

    mileage_match = _MILEAGE_PATTERN.search(body_text[:2000])
    if mileage_match:
        listing.mileage_km = int(re.sub(r"[^\d]", "", mileage_match.group(1)) or 0) or None

    if listing.excerpt is None:
        listing.excerpt = body_text[:400]

    return listing if listing.has_price else None
