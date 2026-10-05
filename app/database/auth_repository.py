from contextlib import contextmanager

import mysql.connector

from app.database.connection import create_connection

USER_COLUMNS = (
    "id, name, email, password_hash, email_verified, role, status, plan, "
    "plan_expires_at, plan_source, plan_granted_by, failed_logins, "
    "locked_until, theme, auto_refresh_minutes, default_store, "
    "totp_secret, totp_enabled, totp_last_step, last_login_at"
)

SETTING_COLUMNS = {"theme", "auto_refresh_minutes", "default_store"}


@contextmanager
def db():
    connection = create_connection()
    cursor = connection.cursor(dictionary=True)

    try:
        yield cursor
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()


# ---------- users ----------

def get_user_by_email(email):
    with db() as cursor:
        cursor.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE email = %s",
            (email,),
        )
        return cursor.fetchone()


def get_user_by_id(user_id):
    with db() as cursor:
        cursor.execute(
            f"SELECT {USER_COLUMNS} FROM users WHERE id = %s",
            (user_id,),
        )
        return cursor.fetchone()


def create_user(name, email, password_hash, email_verified):
    try:
        with db() as cursor:
            cursor.execute(
                """
                INSERT INTO users (name, email, password_hash, email_verified)
                VALUES (%s, %s, %s, %s)
                """,
                (name, email, password_hash, 1 if email_verified else 0),
            )
            return cursor.lastrowid
    except mysql.connector.IntegrityError:
        return None


def update_name(user_id, name):
    with db() as cursor:
        cursor.execute(
            "UPDATE users SET name = %s WHERE id = %s",
            (name, user_id),
        )


def update_settings(user_id, updates):
    columns = [column for column in updates if column in SETTING_COLUMNS]

    if not columns:
        return

    assignments = ", ".join(f"{column} = %s" for column in columns)
    values = [updates[column] for column in columns] + [user_id]

    with db() as cursor:
        cursor.execute(
            f"UPDATE users SET {assignments} WHERE id = %s",
            values,
        )


def set_password(user_id, password_hash):
    with db() as cursor:
        cursor.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (password_hash, user_id),
        )


def mark_email_verified(user_id):
    with db() as cursor:
        cursor.execute(
            "UPDATE users SET email_verified = 1 WHERE id = %s",
            (user_id,),
        )


def touch_last_login(user_id):
    with db() as cursor:
        cursor.execute(
            "UPDATE users SET last_login_at = UTC_TIMESTAMP() WHERE id = %s",
            (user_id,),
        )


def register_failed_login(user_id, max_attempts, lock_until):
    # Order matters: locked_until is evaluated before failed_logins changes
    with db() as cursor:
        cursor.execute(
            """
            UPDATE users
            SET locked_until = IF(failed_logins + 1 >= %s, %s, locked_until),
                failed_logins = failed_logins + 1
            WHERE id = %s
            """,
            (max_attempts, lock_until, user_id),
        )


def reset_failed_logins(user_id):
    with db() as cursor:
        cursor.execute(
            "UPDATE users SET failed_logins = 0, locked_until = NULL WHERE id = %s",
            (user_id,),
        )


# ---------- two-factor authentication ----------

def save_pending_totp(user_id, encrypted_secret):
    with db() as cursor:
        cursor.execute(
            """
            UPDATE users
            SET totp_secret = %s, totp_enabled = 0, totp_last_step = NULL
            WHERE id = %s AND totp_enabled = 0
            """,
            (encrypted_secret, user_id),
        )


def enable_totp(user_id, step, code_hashes):
    with db() as cursor:
        cursor.execute(
            "UPDATE users SET totp_enabled = 1, totp_last_step = %s WHERE id = %s",
            (step, user_id),
        )
        cursor.execute(
            "DELETE FROM recovery_codes WHERE user_id = %s",
            (user_id,),
        )
        cursor.executemany(
            "INSERT INTO recovery_codes (user_id, code_hash) VALUES (%s, %s)",
            [(user_id, code_hash) for code_hash in code_hashes],
        )


def disable_totp(user_id):
    with db() as cursor:
        cursor.execute(
            """
            UPDATE users
            SET totp_secret = NULL, totp_enabled = 0, totp_last_step = NULL
            WHERE id = %s
            """,
            (user_id,),
        )
        cursor.execute(
            "DELETE FROM recovery_codes WHERE user_id = %s",
            (user_id,),
        )


def update_totp_step(user_id, step):
    """True only if this step is newer than the last one used (replay guard)."""
    with db() as cursor:
        cursor.execute(
            """
            UPDATE users SET totp_last_step = %s
            WHERE id = %s AND (totp_last_step IS NULL OR totp_last_step < %s)
            """,
            (step, user_id, step),
        )
        return cursor.rowcount == 1


def replace_recovery_codes(user_id, code_hashes):
    with db() as cursor:
        cursor.execute(
            "DELETE FROM recovery_codes WHERE user_id = %s",
            (user_id,),
        )
        cursor.executemany(
            "INSERT INTO recovery_codes (user_id, code_hash) VALUES (%s, %s)",
            [(user_id, code_hash) for code_hash in code_hashes],
        )


def consume_recovery_code(user_id, code_hash, now):
    with db() as cursor:
        cursor.execute(
            """
            UPDATE recovery_codes SET used_at = %s
            WHERE user_id = %s AND code_hash = %s AND used_at IS NULL
            """,
            (now, user_id, code_hash),
        )
        return cursor.rowcount == 1


# ---------- sessions ----------

def create_session(user_id, token_hash, csrf_token, expires_at, mfa_verified=False):
    with db() as cursor:
        cursor.execute(
            """
            INSERT INTO sessions
                (user_id, token_hash, csrf_token, mfa_verified, expires_at)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, token_hash, csrf_token, 1 if mfa_verified else 0, expires_at),
        )


def get_session(token_hash):
    with db() as cursor:
        cursor.execute(
            """
            SELECT
                s.token_hash,
                s.csrf_token,
                s.mfa_verified,
                s.expires_at,
                u.id,
                u.name,
                u.email,
                u.email_verified,
                u.role,
                u.status,
                u.plan,
                u.plan_expires_at,
                u.totp_enabled,
                u.theme,
                u.auto_refresh_minutes,
                u.default_store
            FROM sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.token_hash = %s
            """,
            (token_hash,),
        )
        return cursor.fetchone()


def set_session_mfa_verified(token_hash):
    with db() as cursor:
        cursor.execute(
            "UPDATE sessions SET mfa_verified = 1 WHERE token_hash = %s",
            (token_hash,),
        )


def delete_session(token_hash):
    with db() as cursor:
        cursor.execute(
            "DELETE FROM sessions WHERE token_hash = %s",
            (token_hash,),
        )


def delete_user_sessions(user_id):
    with db() as cursor:
        cursor.execute(
            "DELETE FROM sessions WHERE user_id = %s",
            (user_id,),
        )


def delete_other_sessions(user_id, keep_token_hash):
    with db() as cursor:
        cursor.execute(
            "DELETE FROM sessions WHERE user_id = %s AND token_hash <> %s",
            (user_id, keep_token_hash),
        )


def delete_expired_sessions():
    with db() as cursor:
        cursor.execute(
            "DELETE FROM sessions WHERE expires_at < UTC_TIMESTAMP()"
        )


# ---------- one-time tokens (verification, reset, 2FA login) ----------

def create_token(user_id, token_hash, purpose, expires_at, now):
    with db() as cursor:
        # Only the newest link of each kind stays valid
        cursor.execute(
            """
            UPDATE auth_tokens SET used_at = %s
            WHERE user_id = %s AND purpose = %s AND used_at IS NULL
            """,
            (now, user_id, purpose),
        )

        cursor.execute(
            """
            INSERT INTO auth_tokens (user_id, token_hash, purpose, expires_at)
            VALUES (%s, %s, %s, %s)
            """,
            (user_id, token_hash, purpose, expires_at),
        )


def find_token_user(token_hash, purpose, now):
    with db() as cursor:
        cursor.execute(
            """
            SELECT u.id, u.email, u.name
            FROM auth_tokens t
            JOIN users u ON u.id = t.user_id
            WHERE t.token_hash = %s
              AND t.purpose = %s
              AND t.used_at IS NULL
              AND t.expires_at > %s
            """,
            (token_hash, purpose, now),
        )
        return cursor.fetchone()


def consume_token(token_hash, purpose, now):
    with db() as cursor:
        cursor.execute(
            """
            UPDATE auth_tokens SET used_at = %s
            WHERE token_hash = %s
              AND purpose = %s
              AND used_at IS NULL
              AND expires_at > %s
            """,
            (now, token_hash, purpose, now),
        )

        if cursor.rowcount != 1:
            return None

        cursor.execute(
            "SELECT user_id FROM auth_tokens WHERE token_hash = %s",
            (token_hash,),
        )

        return cursor.fetchone()["user_id"]


# ---------- audit log ----------

def insert_audit(actor_user_id, action, target_user_id, details, ip, user_agent):
    with db() as cursor:
        cursor.execute(
            """
            INSERT INTO audit_log
                (actor_user_id, action, target_user_id, details, ip, user_agent)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (actor_user_id, action, target_user_id, details, ip, user_agent),
        )