"""HTTPS settings layered on the image-owned Superset configuration."""
from pathlib import Path
import os

_base = Path("/app/bootstrap/superset_config.py")
exec(compile(_base.read_text(), str(_base), "exec"))
SESSION_COOKIE_SECURE = True
SESSION_COOKIE_PATH = os.environ["SUPERSET_APP_ROOT"]
ENABLE_PROXY_FIX = True
PROXY_FIX_CONFIG = {"x_for": 1, "x_proto": 1, "x_host": 0, "x_port": 0, "x_prefix": 0}
