"""The dashboard API: a thin JSON layer over the library (specs/08-dashboard.md)."""

from masterba.api.app import create_app
from masterba.api.settings import Settings, settings_from_env

__all__ = ["Settings", "create_app", "settings_from_env"]
