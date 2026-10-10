from flask import Flask, jsonify, request
from flask_cors import CORS

from app.config.settings import COOKIE_SECURE, FRONTEND_URL
from app.extensions import limiter


def create_app():
    app = Flask(__name__)

    # Reject oversized request bodies
    app.config["MAX_CONTENT_LENGTH"] = 16 * 1024

    # Only your frontend may call the API with cookies
    CORS(
        app,
        origins=[FRONTEND_URL],
        supports_credentials=True,
        allow_headers=["Content-Type", "X-CSRF-Token"],
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )

    limiter.init_app(app)

    from app.api.admin import admin_bp
    from app.api.alerts import alerts_bp
    from app.api.analytics import analytics_bp
    from app.api.auth import auth_bp
    from app.api.categories import categories_bp
    from app.api.health import health_bp
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
        admin_bp,
    ):
        app.register_blueprint(blueprint, url_prefix="/api")

    @app.errorhandler(429)
    def too_many_requests(_error):
        return jsonify({
            "error": "Too many requests. Please try again later."
        }), 429

    @app.errorhandler(413)
    def payload_too_large(_error):
        return jsonify({"error": "Request too large"}), 413

    @app.after_request
    def security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"

        if request.path.startswith(
            ("/api/auth", "/api/account", "/api/watchlist",
             "/api/security", "/api/admin")
        ):
            response.headers["Cache-Control"] = "no-store"

        if COOKIE_SECURE:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        return response

    return app