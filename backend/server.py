"""
Backend entry point for supervisor (uvicorn).
Wraps the Django ASGI application so the existing supervisor config
(`uvicorn server:app --host 0.0.0.0 --port 8001`) keeps working.
"""
import os
import sys
from pathlib import Path

# Add project root (/app) so that `wolan Hr_hr_superapp` is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "wolan Hr_hr_superapp.settings")

from wolan Hr_hr_superapp.asgi import application as app  # noqa: E402
