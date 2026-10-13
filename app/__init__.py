from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.middleware.proxy_fix import ProxyFix

from app.config.production_checks import check_production_settings
from app.config.settings import (
    COOKIE_SECURE,
    FRONTEND_URL,
    SENTRY_DSN,
    TRUSTED_PROXIES,
)
from app.extensions import limiter


def create_app():
    check_production_settings()

    if SENTRY_DSN:
        import sentry_sdk

        sentry_sdk.init(dsn=SENTRY_DSN, send_default_pii=False)

    app = Flask(__name__)

    # Behind a reverse proxy, trust its forwarded headers so rate limits see
    # each visitor's real IP instead of the proxy's
    if TRUSTED_PROXIES > 0:
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=TRUSTED_PROXIES,
            x_proto=TRUSTED_PROXIES,
            x_host=TRUSTED_PROXIES,
        )

    # Reject oversized request bodies (Paystack webhooks are a few KB)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024

    # Only your frontend may call the API with cookies
    CORS(
        app,
        origins=[FRONTEND_URL],
        supports_credentials=True,
        allow_headers=["Content-Type", "X-CSRF-Token"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )

    limiter.init_app(app)

    from app.api.account import account_bp
    from app.api.admin import admin_bp
    from app.api.alerts import alerts_bp
    from app.api.analytics import analytics_bp
    from app.api.auth import auth_bp
    from app.api.billing import billing_bp
    from app.api.categories import categories_bp
    from app.api.health import health_bp
    from app.api.pro import pro_bp
    from app.api.products import products_bp
    from app.api.watchlist import watchlist_bp
    from app.security.sessions import enforce_data_access

    # One switch (REQUIRE_LOGIN_FOR_DATA) decides if product data needs login
    products_bp.before_request(enforce_data_access)
    analytics_bp.before_request(enforce_data_access)
    categories_bp.before_request(enforce_data_access)

    for blueprint in (
        health_bp,
        products_bp,
        analytics_bp,
        categories_bp,
        auth_bp,
        watchlist_bp,
        alerts_bp,
        pro_bp,
        billing_bp,
        account_bp,
        admin_bp,
    ):
        app.register_blueprint(blueprint, url_prefix="/api")

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(429)
    def too_many_requests(_error):
        return jsonify({
            "error": "Too many requests. Please try again later."
        }), 429

    @app.errorhandler(413)
    def payload_too_large(_error):
        return jsonify({"error": "Request too large"}), 413

    @app.errorhandler(500)
    def server_error(_error):
        # Never show stack traces to visitors
        return jsonify({"error": "Something went wrong on our side."}), 500

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        # The API only returns JSON, so it needs no scripts, frames or styles
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; frame-ancestors 'none'"
        )

        if request.path.startswith(
            ("/api/auth", "/api/account", "/api/watchlist",
             "/api/security", "/api/admin", "/api/billing")
        ):
            response.headers["Cache-Control"] = "no-store"

        if COOKIE_SECURE:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response

    return app