import logging
import smtplib
import ssl
import threading
from email.message import EmailMessage
from html import escape

from app.config.settings import (
    APP_NAME,
    FRONTEND_URL,
    SMTP_FROM,
    SMTP_HOST,
    SMTP_PASSWORD,
    SMTP_PORT,
    SMTP_SSL,
    SMTP_USER,
)

logger = logging.getLogger(__name__)


def _deliver(to_address, subject, text, html):
    if not SMTP_HOST:
        logger.warning(
            "SMTP not configured, email not sent.\nTo: %s\nSubject: %s\n%s",
            to_address,
            subject,
            text,
        )
        return

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = SMTP_FROM or SMTP_USER
    message["To"] = to_address
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    context = ssl.create_default_context()

    try:
        if SMTP_SSL:
            with smtplib.SMTP_SSL(
                SMTP_HOST, SMTP_PORT, context=context, timeout=15
            ) as server:
                if SMTP_USER:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(message)
        else:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
                server.starttls(context=context)
                if SMTP_USER:
                    server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(message)
    except Exception:
        logger.exception("Failed to send email to %s", to_address)


def _send(to_address, subject, name, lines, button_label=None, url=None):
    greeting = f"Hi {name}," if name else "Hi,"

    text_parts = [greeting, ""] + lines

    if url:
        text_parts += ["", f"{button_label}: {url}"]

    text_parts += ["", f"- The {APP_NAME} team"]

    html_lines = "".join(
        f"<p style='margin:0 0 12px'>{escape(line)}</p>" for line in lines
    )

    html_button = ""

    if url:
        html_button = (
            f"<p style='margin:20px 0'><a href='{escape(url)}' "
            "style='background:#5c3aed;color:#ffffff;padding:11px 20px;"
            "border-radius:8px;text-decoration:none;display:inline-block'>"
            f"{escape(button_label)}</a></p>"
            "<p style='color:#64748b;font-size:12px'>If the button doesn't "
            f"work, copy this link: {escape(url)}</p>"
        )

    html = (
        "<div style='font-family:Arial,sans-serif;font-size:14px;"
        "color:#0f172a;max-width:480px'>"
        f"<p style='margin:0 0 12px'>{escape(greeting)}</p>"
        f"{html_lines}{html_button}"
        f"<p style='color:#64748b'>The {escape(APP_NAME)} team</p></div>"
    )

    # Sent in the background so response time never reveals whether
    # an email address exists.
    threading.Thread(
        target=_deliver,
        args=(to_address, subject, "\n".join(text_parts), html),
        daemon=True,
    ).start()


def send_verification_email(name, email, token):
    _send(
        email,
        f"Verify your {APP_NAME} email",
        name,
        [
            f"Welcome to {APP_NAME}. Please confirm your email address.",
            "This link expires in 24 hours.",
        ],
        "Verify email",
        f"{FRONTEND_URL}/verify-email?token={token}",
    )


def send_reset_email(name, email, token):
    _send(
        email,
        f"Reset your {APP_NAME} password",
        name,
        [
            "We received a request to reset your password.",
            "This link expires in 1 hour. If you didn't ask for this, you can ignore this email.",
        ],
        "Reset password",
        f"{FRONTEND_URL}/reset-password?token={token}",
    )


def send_account_exists_email(name, email):
    _send(
        email,
        f"Someone tried to sign up to {APP_NAME} with your email",
        name,
        [
            "Someone tried to create an account with this email address, but you already have one.",
            "If it was you, just log in or use 'Forgot password'. If it wasn't, you can ignore this email.",
        ],
        "Go to login",
        f"{FRONTEND_URL}/login",
    )