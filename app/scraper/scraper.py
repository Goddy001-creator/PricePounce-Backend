import requests

from app.config.settings import (
    SCRAPER_LIMIT,
    SCRAPER_TIMEOUT,
)
from app.scraper.http import fetch_page
from app.scraper.jumia import parse_jumia_product
from app.scraper.konga import (
    KONGA_SEARCH_URL,
    get_konga_headers,
    get_konga_payload,
    normalize_konga_product,
)


JUMIA_PRODUCTS_URL = (
    "https://www.jumia.com.ng/electronics/"
)


def scrape_jumia(limit=None):
    limit = limit or SCRAPER_LIMIT

    response = fetch_page(
        JUMIA_PRODUCTS_URL
    )

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(
        response.text,
        "lxml"
    )

    elements = soup.select(
        "article.prd"
    )

    products = []

    for element in elements[:limit]:
        product = parse_jumia_product(
            element
        )

        if product:
            products.append(product)

    return products


def scrape_konga(limit=None):
    limit = limit or SCRAPER_LIMIT

    response = requests.post(
        KONGA_SEARCH_URL,
        headers=get_konga_headers(),
        json=get_konga_payload(limit),
        timeout=SCRAPER_TIMEOUT,
    )

    response.raise_for_status()

    data = response.json()

    if isinstance(data, dict):
        items = (
            data.get("hits")
            or data.get("results")
            or data.get("products")
            or data.get("data")
            or []
        )
    else:
        items = data

    if isinstance(items, dict):
        items = (
            items.get("hits")
            or items.get("results")
            or items.get("products")
            or []
        )

    products = []

    for item in items[:limit]:
        product = normalize_konga_product(
            item
        )

        if product:
            products.append(product)

    return products


def scrape_store(store_name, limit=None):
    store_name = store_name.lower()

    if store_name == "jumia":
        return scrape_jumia(limit)

    if store_name == "konga":
        return scrape_konga(limit)

    raise ValueError(
        f"Unsupported store: {store_name}"
    )


def scrape_all_stores(limit=None):
    return {
        "jumia": scrape_jumia(limit),
        "konga": scrape_konga(limit),
    }