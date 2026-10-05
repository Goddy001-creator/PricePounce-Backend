from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# In-memory storage is fine for one server process.
# With several workers, switch storage_uri to Redis.
limiter = Limiter(key_func=get_remote_address, storage_uri="memory://")