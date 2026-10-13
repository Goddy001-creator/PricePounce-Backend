import logging

from app.config import settings

logger = logging.getLogger(__name__)


def check_production_settings():
    if not settings.IS_PRODUCTION:
        return

    problems = []

    if not settings.COOKIE_SECURE:
        problems.append("COOKIE_SECURE must be true")

    for name in ("FRONTEND_URL", "BACKEND_URL"):
        if not str(getattr(settings, name, "")).startswith("https://"):
            problems.append(f"{name} must start with https://")

    if not getattr(settings, "TOTP_ENCRYPTION_KEY", ""):
        problems.append("TOTP_ENCRYPTION_KEY is not set")

    if str(settings.DB_USER).lower() == "root":
        problems.append("Connect to MySQL with a limited user, not root")

    if not settings.DB_PASSWORD:
        problems.append("DB_PASSWORD is empty")

    if problems:
        raise RuntimeError(
            "Unsafe production configuration:\n- " + "\n- ".join(problems)
        )

    if settings.RATELIMIT_STORAGE_URI.startswith("memory"):
        logger.warning("Rate limits are stored in memory. Use Redis with several workers.")

    if "gmail.com" in str(getattr(settings, "SMTP_FROM", "")).lower():
        logger.warning("Emails are sent from a gmail.com address. Use your own domain.")

    if not str(settings.PAYSTACK_SECRET_KEY).startswith("sk_live_"):
        logger.warning("Paystack is not using a live key.")