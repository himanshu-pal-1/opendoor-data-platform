"""FastAPI REST API for OpenDoor Data Platform.

This module provides the main API entry point with endpoints for
accessing physician, practice, and valuation data.
"""

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from src.api.routes import analytics, physicians, practices, valuations
from src.utils.db_connection import check_connection, get_session


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    if not check_connection():
        raise RuntimeError("Database connection failed on startup")
    yield
    # Shutdown
    pass


app = FastAPI(
    title="OpenDoor Data Platform API",
    description="API for healthcare practice data, valuations, and analytics",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Include routers
app.include_router(physicians.router, prefix="/physicians", tags=["Physicians"])
app.include_router(practices.router, prefix="/practices", tags=["Practices"])
app.include_router(valuations.router, prefix="/valuations", tags=["Valuations"])
app.include_router(analytics.router, prefix="/analytics", tags=["Analytics"])


@app.get("/")
async def root():
    """Root endpoint returning API information."""
    return {
        "name": "OpenDoor Data Platform API",
        "version": "1.0.0",
        "status": "operational",
        "documentation": "/docs",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    db_healthy = check_connection()

    return {
        "status": "healthy" if db_healthy else "degraded",
        "database": "connected" if db_healthy else "disconnected",
    }
