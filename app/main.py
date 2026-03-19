"""
Invoice Processing Automation — FastAPI application entry point.

Registers all routers and configures startup logging.
"""

import logging
import logging.config

from fastapi import FastAPI

from app.routes.health import router as health_router
from app.routes.invoices import router as invoices_router

logging.config.dictConfig(
    {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "format": "%(asctime)s %(levelname)s %(name)s %(message)s",
            },
        },
        "handlers": {
            "console": {
                "class": "logging.StreamHandler",
                "formatter": "default",
            },
        },
        "root": {
            "handlers": ["console"],
            "level": "INFO",
        },
    }
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Invoice Processing Automation",
    description="AI-powered invoice extraction, validation, and routing pipeline.",
    version="1.0.0",
)

app.include_router(health_router, tags=["health"])
app.include_router(invoices_router, tags=["invoices"])

logger.info("Application started")
