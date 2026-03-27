"""
Invoice Processing Automation — FastAPI application entry point.

Registers all routers under /api/v1, applies middleware (correlation ID,
request logging, error handling), and configures structured JSON logging
at startup.
"""

from fastapi import FastAPI

from app.api.middleware.error_handler import ErrorHandlerMiddleware
from app.api.middleware.logging import RequestLoggingMiddleware
from app.api.routes.health import router as health_router
from app.api.routes.invoices import router as invoices_router
from app.core.logging_config import configure_logging

configure_logging()

app = FastAPI(
    title="Invoice Processing Automation",
    description="AI-powered invoice extraction, validation, and routing pipeline.",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(ErrorHandlerMiddleware)
app.add_middleware(RequestLoggingMiddleware)

app.include_router(health_router, prefix="/api/v1")
app.include_router(invoices_router, prefix="/api/v1/invoices")
