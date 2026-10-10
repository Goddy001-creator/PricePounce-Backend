import threading

from app.scraper.scraper import (
    scrape_all_stores,
    scrape_store,
)
from app.services.alerts_service import run_alerts
from app.services.product_service import save_products


def _trigger_alerts():
    # Runs in the background so the scrape response isn't delayed
    threading.Thread(target=run_alerts, daemon=True).start()


def run_store_scrape(store_name, limit=None):
    products = scrape_store(
        store_name,
        limit
    )

    saved = save_products(products)

    _trigger_alerts()

    return saved


def run_full_scrape(limit=None):
    results = scrape_all_stores(limit)

    saved = {
        "jumia": save_products(
            results["jumia"]
        ),
        "konga": save_products(
            results["konga"]
        ),
    }

    _trigger_alerts()

    return saved