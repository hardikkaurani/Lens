"""LENS Background Worker Service."""

import sys
from pathlib import Path

# Ensure services/api is accessible on sys.path for shared models and config
_api_path = str(Path(__file__).resolve().parents[2] / "api")
if _api_path not in sys.path:
    sys.path.insert(0, _api_path)
