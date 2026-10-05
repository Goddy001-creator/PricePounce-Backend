import json

from app.database.auth_repository import db

USER_LIST_COLUMNS = (
    "id, name, email, email_verified, role, status, plan, plan_expires_at, "
    "totp_enabled, last_login_at, created_at"
)

USER_DETAIL_SELECT = """
    SELECT
        u.id, u.name, u.email, u.email_verified, u.role, u.status, u.plan,
        u.plan_expires_at, u.plan_source, u.plan_granted_by,
        gb.email AS granted_by_email,
        u.totp_enabled, u.failed_logins, u.locked_until, u.last_login_at,
        u.created_at, u.theme, u.auto_refresh_minutes, u.default_store
    FROM users u
    LEFT JOIN users gb ON gb.id = u.plan_granted_by
    WHERE u.id = %s
"""

SORT_COLUMNS = {
    "created": "created_at",
    "name": "name",
    "email": "email",
    "last_login": "last_login_at",
}

PRO_ACTIVE = (
    "(plan = 'pro' AND "
    "(plan_expires_at IS NULL OR plan_expires_at > UTC_TIMESTAMP()))"
)

AUDIT_SELECT = """
    SELECT
        a.id, a.action, a.actor_user_id, au.email AS actor_email,
        a.target_user_id, tu.email AS target_email,
        a.details, a.ip, a.created_at
    FROM audit_log a
    LEFT JOIN users au ON au.id = a.actor_user_id
    LEFT JOIN users tu ON tu.id = a.target_user_id
"""


def _ints(row):
    return {key: int(value or 0) for key, value in (row or {}).items()}


def _parse_details(rows):
    for row in rows:
        raw = row["details"]

        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8", errors="replace")

        if isinstance(raw, str):
            try:
                row["details"] = json.loads(raw)
            except ValueError:
                row["details"] = None

    return rows


# ---------- users ----------

def list_users(page, per_page, search, role, plan, status, sort, order):
    conditions = []
    params = []

    if search:
        conditions.append("(name LIKE %s OR email LIKE %s)")
        term = f"%{search}%"
        params.extend([term, term])

    if role in ("user", "admin"):
        conditions.append("role = %s")
        params.append(role)

    if status in ("active", "suspended"):
        conditions.append("status = %s")
        params.append(status)

    if plan == "pro":
        conditions.append(PRO_ACTIVE)
    elif plan == "free":
        conditions.append(f"NOT {PRO_ACTIVE}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    column = SORT_COLUMNS.get(sort, "created_at")
    direction = "ASC" if order == "asc" else "DESC"
    offset = (page - 1) * per_page

    with db() as cursor:
        cursor.execute(f"SELECT COUNT(*) AS total FROM users {where}", params)
        total = cursor.fetchone()["total"]

        cursor.execute(
            f"""
            SELECT {USER_LIST_COLUMNS}
            FROM users
            {where}
            ORDER BY {column} IS NULL, {column} {direction}, id ASC
            LIMIT %s OFFSET %s
            """,
            params + [per_page, offset],
        )

        return cursor.fetchall(), total


def get_user_detail(user_id):
    with db() as cursor:
        cursor.execute(USER_DETAIL_SELECT, (user_id,))
        user = cursor.fetchone()

        if user is None:
            return None

        cursor.execute(
            "SELECT COUNT(*) AS n FROM watchlist WHERE user_id = %s",
            (user_id,),
        )
        user["watchlist_count"] = cursor.fetchone()["n"]

        cursor.execute(
            """
            SELECT COUNT(*) AS n FROM sessions
            WHERE user_id = %s AND expires_at > UTC_TIMESTAMP()
            """,
            (user_id,),
        )
        user["active_sessions"] = cursor.fetchone()["n"]

        return user


def set_status(user_id, status):
    with db() as cursor:
        cursor.execute(
            "UPDATE users SET status = %s WHERE id = %s",
            (status, user_id),
        )


def set_plan(user_id, plan, expires_at, source, granted_by):
    with db() as cursor:
        cursor.execute(
            """
            UPDATE users
            SET plan = %s, plan_expires_at = %s,
                plan_source = %s, plan_granted_by = %s
            WHERE id = %s
            """,
            (plan, expires_at, source, granted_by, user_id),
        )


def delete_user(user_id):
    with db() as cursor:
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))


# ---------- overview ----------

def get_stats():
    with db() as cursor:
        cursor.execute(f"""
            SELECT
                COUNT(*) AS total_users,
                COALESCE(SUM(email_verified = 1), 0) AS verified_users,
                COALESCE(SUM(status = 'suspended'), 0) AS suspended_users,
                COALESCE(SUM(role = 'admin'), 0) AS admins,
                COALESCE(SUM(totp_enabled = 1), 0) AS mfa_users,
                COALESCE(SUM({PRO_ACTIVE}), 0) AS pro_users,
                COALESCE(SUM(created_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY), 0) AS signups_7d,
                COALESCE(SUM(created_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY), 0) AS signups_30d,
                COALESCE(SUM(last_login_at >= UTC_TIMESTAMP() - INTERVAL 7 DAY), 0) AS active_7d
            FROM users
        """)
        users = _ints(cursor.fetchone())

        cursor.execute("""
            SELECT DATE(created_at) AS day, COUNT(*) AS signups
            FROM users
            WHERE created_at >= UTC_TIMESTAMP() - INTERVAL 30 DAY
            GROUP BY DATE(created_at)
            ORDER BY day
        """)
        signups = [
            {"day": row["day"].isoformat(), "signups": row["signups"]}
            for row in cursor.fetchall()
        ]

        cursor.execute("""
            SELECT store_name, COUNT(*) AS products, MAX(last_checked) AS last_checked
            FROM products
            GROUP BY store_name
            ORDER BY products DESC
        """)
        stores = cursor.fetchall()

        cursor.execute(
            "SELECT COUNT(*) AS entries, COUNT(DISTINCT user_id) AS watchers FROM watchlist"
        )
        watch = _ints(cursor.fetchone())

        cursor.execute("SELECT COUNT(*) AS history_rows FROM price_history")
        history = _ints(cursor.fetchone())

        cursor.execute("""
            SELECT COUNT(*) AS failed
            FROM audit_log
            WHERE action IN ('login_failed', 'mfa_failed')
              AND created_at >= UTC_TIMESTAMP() - INTERVAL 1 DAY
        """)
        failed = _ints(cursor.fetchone())

    return {
        "users": users,
        "signups": signups,
        "stores": stores,
        "content": {**watch, **history},
        "security": {"failed_logins_24h": failed["failed"]},
    }


# ---------- audit log ----------

def list_audit(page, per_page, action, user_id):
    conditions = []
    params = []

    if action:
        conditions.append("a.action = %s")
        params.append(action)

    if user_id:
        conditions.append("(a.actor_user_id = %s OR a.target_user_id = %s)")
        params.extend([user_id, user_id])

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    offset = (page - 1) * per_page

    with db() as cursor:
        cursor.execute(
            f"SELECT COUNT(*) AS total FROM audit_log a {where}",
            params,
        )
        total = cursor.fetchone()["total"]

        cursor.execute(
            f"{AUDIT_SELECT} {where} ORDER BY a.id DESC LIMIT %s OFFSET %s",
            params + [per_page, offset],
        )

        return _parse_details(cursor.fetchall()), total


def list_audit_actions():
    with db() as cursor:
        cursor.execute("SELECT DISTINCT action FROM audit_log ORDER BY action")
        return [row["action"] for row in cursor.fetchall()]


def recent_audit_for_user(user_id, limit=20):
    with db() as cursor:
        cursor.execute(
            f"""
            {AUDIT_SELECT}
            WHERE a.target_user_id = %s OR a.actor_user_id = %s
            ORDER BY a.id DESC
            LIMIT %s
            """,
            (user_id, user_id, limit),
        )
        return _parse_details(cursor.fetchall())