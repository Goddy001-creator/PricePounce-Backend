from flask import Flask
from flask_cors import CORS


def create_app():
    app = Flask(__name__)

    CORS(app)

    from app.api.health import health_bp
    from app.api.products import products_bp
    from app.api.analytics import analytics_bp

    app.register_blueprint(health_bp, url_prefix="/api")
    app.register_blueprint(products_bp, url_prefix="/api")
    app.register_blueprint(analytics_bp, url_prefix="/api")

    return app