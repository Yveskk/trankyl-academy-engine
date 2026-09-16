"""Rate limiting shared across endpoints (public routes only : auth,
chat/matching). Uses the client IP as the key. Kept in its own module (not
in main.py) so endpoint files can import `limiter` without a circular
import."""
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
