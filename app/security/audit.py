import json
import logging

from flask import request

from app.database import auth_repository as repo

logger = logging.getLogger(__name__)


def audit(action, actor_user_id=None, target_user_id=None, **details):
    """Records a security event. Never put passwords, tokens or codes in details."""
    try:
        repo.insert_audit(
            actor_user_id,
            action,
            target_user_id,
            json.dumps(details) if details else None,
            request.remote_addr,
            (request.headers.get("User-Agent") or "")[:255],
        )
    except Exception:
        logger.exception("Failed to write audit log entry: %s", action)