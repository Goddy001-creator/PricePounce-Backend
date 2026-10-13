from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from app.config.settings import RATELIMIT_STORAGE_URI

# Switch RATELIMIT_STORAGE_URI to Redis in production, so limits are shared
# between all server processes
limiter = Limiter(key_func=get_remote_address, storage_uri=RATELIMIT_STORAGE_URI)