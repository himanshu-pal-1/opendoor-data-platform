"""REST API for the OpenDoor Data Platform.

This module exports the FastAPI application for serving practice
and valuation data.
"""

from src.api.main import app

__all__ = ["app"]
