import logging
import os

from app import create_app
from app.services.scheduler import start_digest_scheduler, start_scheduler

logging.basicConfig(level=logging.INFO)

app = create_app()

if __name__ == "__main__":
    # In debug mode Flask runs this file twice (a watcher plus the real server).
    # Only start the background jobs in the real one.
    if os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        start_scheduler()
        start_digest_scheduler()

    app.run(debug=True)