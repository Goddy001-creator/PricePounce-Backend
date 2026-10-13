import logging
import time

from app.database.connection import create_connection
from app.services.scheduler import start_digest_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("worker")


def cleanup():
    """Removes expired sessions and tokens and abandoned checkouts."""
    connection = create_connection()

    try:
        cursor = connection.cursor()
        cursor.execute("DELETE FROM sessions WHERE expires_at < UTC_TIMESTAMP()")
        cursor.execute(
            "DELETE FROM auth_tokens WHERE expires_at < UTC_TIMESTAMP() - INTERVAL 7 DAY"
        )
        cursor.execute(
            "DELETE FROM payments WHERE status = 'pending' "
            "AND created_at < NOW() - INTERVAL 7 DAY"
        )
        connection.commit()
    finally:
        connection.close()


if __name__ == "__main__":
    start_scheduler()
    start_digest_scheduler()
    logger.info("Worker started")

    while True:
        try:
            cleanup()
        except Exception:
            logger.exception("Cleanup failed")

        time.sleep(6 * 60 * 60)