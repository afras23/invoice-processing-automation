"""
Integration tests for observability: correlation ID, metrics, and health/ready.

Covers:
- Correlation ID present in response header
- Custom correlation ID echoed back in response header
- GET /api/v1/metrics returns real pipeline data
- Metrics reflect invoices recorded by the tracker
- GET /api/v1/health/ready reports database status
- GET /api/v1/health returns healthy
"""

from __future__ import annotations

from fastapi.testclient import TestClient

# ── Correlation ID ────────────────────────────────────────────────────────────


def test_response_includes_correlation_id_header(test_client: TestClient):
    """Every response carries an X-Correlation-ID header."""
    response = test_client.get("/api/v1/health")
    assert "x-correlation-id" in response.headers


def test_custom_correlation_id_echoed_in_response(test_client: TestClient):
    """A client-supplied X-Correlation-ID is echoed back unchanged."""
    response = test_client.get(
        "/api/v1/health",
        headers={"X-Correlation-ID": "my-trace-id-123"},
    )
    assert response.headers.get("x-correlation-id") == "my-trace-id-123"


# ── Health endpoints ──────────────────────────────────────────────────────────


def test_health_returns_healthy(test_client: TestClient):
    """GET /api/v1/health returns 200 with status 'healthy'."""
    response = test_client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_health_ready_reports_database_status(test_client: TestClient):
    """GET /api/v1/health/ready includes a 'database' key in checks."""
    response = test_client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert "checks" in body
    assert "database" in body["checks"]
    # Without DATABASE_URL configured in tests, database is 'not configured'
    assert body["checks"]["database"] == "not configured"


def test_health_ready_reports_ai_provider_status(test_client: TestClient):
    """GET /api/v1/health/ready reports AI provider check."""
    response = test_client.get("/api/v1/health/ready")
    body = response.json()
    assert "ai_provider" in body["checks"]


# ── Metrics endpoint ──────────────────────────────────────────────────────────


def test_metrics_returns_200(test_client: TestClient):
    """GET /api/v1/metrics returns 200."""
    response = test_client.get("/api/v1/metrics")
    assert response.status_code == 200


def test_metrics_contains_pipeline_section(test_client: TestClient):
    """Metrics response has a 'pipeline' section with required keys."""
    response = test_client.get("/api/v1/metrics")
    body = response.json()
    pipeline = body.get("pipeline", {})
    assert "invoices_processed_today" in pipeline
    assert "avg_extraction_accuracy" in pipeline
    assert "cost_today_usd" in pipeline
    assert "pending_review_count" in pipeline
    assert "export_count_today" in pipeline


def test_metrics_reflects_invoices_processed(test_client: TestClient):
    """After processing invoices via batch, metrics counter increments."""
    # Submit a batch to increment the counter
    test_client.post(
        "/api/v1/batch",
        files=[("files", ("invoice.txt", b"Invoice from Acme Corp", "text/plain"))],
    )
    response = test_client.get("/api/v1/metrics")
    pipeline = response.json()["pipeline"]
    assert pipeline["invoices_processed_today"] >= 1


def test_metrics_contains_ai_costs(test_client: TestClient):
    """Metrics response has 'ai_costs' with utilisation data."""
    response = test_client.get("/api/v1/metrics")
    body = response.json()
    assert "ai_costs" in body
    assert "daily_cost_usd" in body["ai_costs"]
    assert "circuit_breaker_open" in body["ai_costs"]


def test_metrics_contains_integrations(test_client: TestClient):
    """Metrics response includes integration status dict."""
    response = test_client.get("/api/v1/metrics")
    body = response.json()
    assert "integrations" in body
    assert "airtable" in body["integrations"]
