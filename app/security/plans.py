from datetime import datetime, timezone

PLAN_LIMITS = {
    "free": {"watchlist_max": 10, "history_days": 30},
    "pro": {"watchlist_max": 200, "history_days": None},
}


def _utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def effective_plan(row):
    """Returns 'pro' only while the plan is active and not expired."""
    if row.get("plan") == "pro":
        expires = row.get("plan_expires_at")

        if expires is None or expires > _utcnow():
            return "pro"

    return "free"


def limits_for(row):
    return PLAN_LIMITS[effective_plan(row)]