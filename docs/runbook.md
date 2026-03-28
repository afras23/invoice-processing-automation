# Runbook

Operational procedures for the AI Invoice Processing Pipeline.

---

## Health Checks

### Liveness
```bash
curl http://localhost:8000/api/v1/health
# {"status":"healthy","timestamp":"...","version":"1.0.0"}
```
Returns 200 if the process is alive. Used by Docker HEALTHCHECK.

### Readiness
```bash
curl http://localhost:8000/api/v1/health/ready
# {"status":"ready","checks":{"ai_provider":"ok","database":"ok"}}
```
Returns 200 if both AI provider and database are reachable. Returns 503 if either is down.

Use the readiness endpoint for load balancer health checks. Use liveness for process restart decisions.

### Metrics
```bash
curl http://localhost:8000/api/v1/metrics
```
Returns daily AI cost, call count, budget utilisation, and circuit breaker state.

---

## Common Failures

### 1. `{"status":"error","error":{"error_code":"COST_LIMIT_EXCEEDED"}}`

**Cause:** Daily AI spend has reached `MAX_DAILY_COST_USD`.

**Resolution:**
1. Check current spend: `GET /api/v1/metrics` → `daily_cost_usd`
2. If legitimate: increase `MAX_DAILY_COST_USD` in `.env` and restart the app
3. If unexpected: check for runaway batch jobs or abuse of the API
4. Cost resets at UTC midnight automatically

### 2. `{"error_code":"CIRCUIT_BREAKER_OPEN"}`

**Cause:** The AI client has seen `CIRCUIT_BREAKER_THRESHOLD` consecutive failures and has opened the circuit breaker to prevent cascade failures.

**Resolution:**
1. Check `GET /api/v1/metrics` → `circuit_breaker_open: true`
2. Check Anthropic status page for outages
3. The circuit breaker resets automatically after `CIRCUIT_BREAKER_RESET_SECONDS` (default: 60s)
4. To force-reset: restart the application (`docker-compose restart app`)

### 3. `{"status":"ready","checks":{"database":"error: ..."}}`

**Cause:** The app cannot reach PostgreSQL.

**Resolution:**
1. Check DB container: `docker-compose ps db`
2. If stopped: `docker-compose start db`
3. If unhealthy: check logs: `docker-compose logs db`
4. Verify `DATABASE_URL` in `.env` matches the DB service config
5. Without a database, invoice processing still works (no persistence); only metrics aggregation and audit log persistence are affected

### 4. `422 Unprocessable Entity` on file upload

**Cause:** Incorrect `Content-Type` or form field name.

**Resolution:**
```bash
# Correct form:
curl -X POST http://localhost:8000/api/v1/process \
  -F "file=@invoice.pdf"

# Batch:
curl -X POST http://localhost:8000/api/v1/batch \
  -F "files=@invoice1.pdf" \
  -F "files=@invoice2.pdf"
```

### 5. Invoice stuck in review queue

**Cause:** Confidence score below threshold (default 0.7).

**Resolution:**
```bash
# List queue
curl http://localhost:8000/api/v1/review

# Approve
curl -X POST http://localhost:8000/api/v1/review/{item_id}/action \
  -H "Content-Type: application/json" \
  -d '{"action":"approve","actor":"ops@company.com"}'

# Reject
curl -X POST http://localhost:8000/api/v1/review/{item_id}/action \
  -H "Content-Type: application/json" \
  -d '{"action":"reject","actor":"ops@company.com","notes":"Duplicate submission"}'
```

### 6. High error rate on a specific invoice format

**Cause:** Prompt not generalising to a new invoice layout.

**Resolution:**
1. Add the failing invoice to `eval/test_set.jsonl` as a new test case
2. Run `make evaluate` to measure field accuracy
3. Adjust the prompt in `app/services/ai/prompts/` — do not edit prompts directly in service code
4. Re-run evaluation; compare results before/after

---

## Deployment Procedures

### Standard deploy
```bash
git pull origin main
docker-compose up --build -d
# Watch for healthy state:
docker-compose ps
```

### Database migration
```bash
# Run inside the app container:
docker-compose exec app alembic upgrade head
# Or locally with DATABASE_URL set:
make migrate
```

### Rollback
```bash
# Previous image tag:
docker-compose down
docker tag invoice-processing-automation_app:previous invoice-processing-automation_app:latest
docker-compose up -d

# DB rollback (one step):
docker-compose exec app alembic downgrade -1
```

### View logs
```bash
# All services
docker-compose logs -f

# App only, last 100 lines
docker-compose logs --tail=100 app

# Filter by correlation_id (structured JSON logs)
docker-compose logs app | python -c "
import sys, json
for line in sys.stdin:
    try:
        rec = json.loads(line)
        if rec.get('correlation_id') == 'YOUR_ID':
            print(line.strip())
    except Exception:
        pass
"
```

---

## Configuration Reference

All config is via environment variables. See [.env.example](../.env.example) for full documentation.

| Variable | Default | When to change |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | On key rotation |
| `MAX_DAILY_COST_USD` | `10.0` | When processing volume increases |
| `CONFIDENCE_REVIEW_THRESHOLD` | `0.7` | To tune automation rate vs. review load |
| `CIRCUIT_BREAKER_THRESHOLD` | `5` | If transient failures are causing false opens |
| `AI_MODEL` | `claude-3-5-sonnet-20241022` | On model upgrades |

---

## Monitoring Checklist (Daily)

- [ ] `GET /api/v1/metrics` — `daily_cost_usd` trending within expected range?
- [ ] `GET /api/v1/review` — queue not growing unboundedly?
- [ ] `GET /api/v1/health/ready` — all checks green?
- [ ] Log stream — any `ERROR` level entries?
