import os

from dotenv import load_dotenv


load_dotenv()


def _flag(name, default="false"):
    return os.getenv(name, default).strip().lower() == "true"


DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "3306"))
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

KONGA_API_KEY = os.getenv("KONGA_API_KEY")

SCRAPER_TIMEOUT = int(os.getenv("SCRAPER_TIMEOUT", "30"))
SCRAPER_LIMIT = int(os.getenv("SCRAPER_LIMIT", "20"))

APP_NAME = os.getenv("APP_NAME", "PricePounce")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173").rstrip("/")

COOKIE_NAME = "pp_session"
COOKIE_SECURE = _flag("COOKIE_SECURE")
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "Lax")
SESSION_DAYS = int(os.getenv("SESSION_DAYS", "7"))

REQUIRE_EMAIL_VERIFICATION = _flag("REQUIRE_EMAIL_VERIFICATION", "true")

SMTP_HOST = os.getenv("SMTP_HOST", "")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_SSL = _flag("SMTP_SSL")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM = os.getenv("SMTP_FROM", "")


TOTP_ENCRYPTION_KEY = os.getenv("TOTP_ENCRYPTION_KEY", "")
REQUIRE_LOGIN_FOR_DATA = _flag("REQUIRE_LOGIN_FOR_DATA")