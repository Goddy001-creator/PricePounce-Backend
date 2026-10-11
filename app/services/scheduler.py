import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from app.config.settings import (
    SCRAPE_INTERVAL_MINUTES,
    SCRAPE_LIMIT,
    WEEKLY_DIGEST_ENABLED,
)
from app.database.repositories import create_connection
from app.services.digest_service import run_weekly_digest
from app.services.scraper_service import run_store_scrape

logger = logging.getLogger(__name__)

STORES = ("jumia", "konga")
SCRAPE_LOCK = "pricepounce_scrape"
DIGEST_LOCK = "pricepounce_digest"

LAGOS = timezone(timedelta(hours=1))

_scrape_started = False
_digest_started = False


def _with_lock(name, job):
    """Run job only if no other process holds the named MySQL lock."""
    lock_connection = create_connection()

    try:
        cursor = lock_connection.cursor()
        cursor.execute("SELECT GET_LOCK(%s, 0)", (name,))

        if cursor.fetchone()[0] != 1:
            logger.info("%s already running elsewhere, skipping", name)
            return

        job()

        cursor.execute("SELECT RELEASE_LOCK(%s)", (name,))
        cursor.fetchone()
    finally:
        lock_connection.close()


def _scrape_all():
    for store in STORES:
        try:
            products = run_store_scrape(store, SCRAPE_LIMIT)
            logger.info("Scraped %s: %d products", store, len(products))
        except Exception:
            logger.exception("Scrape failed for %s", store)


def _scrape_loop(interval_seconds):
    time.sleep(30)

    while True:
        try:
            _with_lock(SCRAPE_LOCK, _scrape_all)
        except Exception:
            logger.exception("Scheduled scrape crashed")

        time.sleep(interval_seconds)


def _digest_loop():
    time.sleep(60)

    while True:
        try:
            now = datetime.now(LAGOS)

            # Mondays from 8am Lagos time. Users who already got one
            # this week are skipped inside run_weekly_digest.
            if now.weekday() == 0 and now.hour >= 8:
                _with_lock(DIGEST_LOCK, run_weekly_digest)
        except Exception:
            logger.exception("Weekly digest crashed")

        time.sleep(30 * 60)


def start_scheduler():
    global _scrape_started

    if _scrape_started or SCRAPE_INTERVAL_MINUTES <= 0:
        return

    _scrape_started = True

    threading.Thread(
        target=_scrape_loop,
        args=(SCRAPE_INTERVAL_MINUTES * 60,),
        daemon=True,
        name="scrape-scheduler",
    ).start()

    logger.info("Scheduled scraping every %d minutes", SCRAPE_INTERVAL_MINUTES)


def start_digest_scheduler():
    global _digest_started

    if _digest_started or not WEEKLY_DIGEST_ENABLED:
        return

    _digest_started = True

    threading.Thread(
        target=_digest_loop,
        daemon=True,
        name="digest-scheduler",
    ).start()

    logger.info("Weekly digest enabled (Mondays, 8am Lagos time)")