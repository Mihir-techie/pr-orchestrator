# MergeFlow Frontend–Backend Integration

This document defines how a React/Vite dashboard can integrate with the
existing FastAPI API. It describes the backend contract and representative
client behavior; **this repository currently contains no React/Vite frontend
source code**. Implement the UI examples in the frontend project rather than
treating them as already present here.

## Origins and connectivity

The backend runs at a deployment-specific origin (for example,
`http://localhost:8000`), and the proposed Vite development server runs at
`http://localhost:5173`. Configure the backend origin in the Vite app, for
example:

```dotenv
VITE_API_BASE_URL=http://localhost:8000
```

The current FastAPI application does not register CORS middleware. A browser
request from port 5173 to port 8000 is cross-origin, so local and production
deployments must either:

1. Configure a Vite development proxy and a same-origin production reverse
   proxy, or
2. Add backend CORS middleware with explicit trusted frontend origins and
   required methods/headers.

Do not use a permissive wildcard CORS policy for a production dashboard.
Requests should use JSON for the manual review API. GitHub webhook requests are
server-to-server and are not initiated by the React dashboard.

## Submission flows

### Manual review from the dashboard form

The backend endpoint is `POST /api/v1/reviews`. The request schema is:

```json
{
  "repository": "owner/repository",
  "pull_number": 123
}
```

The repository can also be supplied as an HTTPS GitHub repository URL or pull
request URL. The backend normalizes and validates the repository, retrieves PR
metadata from GitHub, and enqueues the `process_pull_request` Celery task.

Example request:

```ts
const response = await fetch(`${apiBase}/api/v1/reviews`, {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ repository, pull_number: Number(pullNumber) }),
});

const body = await response.json();
if (!response.ok) {
  throw new Error(body.detail ?? "Unable to queue the review");
}
// HTTP 202 means queued, not completed.
setTaskId(body.task_id);
```

Success response (HTTP 202):

```json
{
  "status": "queued",
  "task_id": "celery-task-id",
  "repository": "owner/repository",
  "pull_number": 123
}
```

Error responses can include validation errors (typically HTTP 422), missing
or inaccessible PR (HTTP 404), GitHub/provider connectivity/configuration
issues (HTTP 502/503), and inbound rate limiting (HTTP 429). A successful
response only confirms that the task was queued. The backend does not currently
provide an HTTP task-status route.

### GitHub webhook

GitHub calls `POST /api/v1/webhooks/github` directly when a configured PR event
occurs. GitHub sends the signed payload and delivery/event headers; FastAPI
validates the HMAC and deduplicates delivery IDs before enqueueing the same
Celery task. The React dashboard must not impersonate this endpoint: it does
not have the webhook secret and should not construct GitHub signature headers.

Webhook success returns HTTP 202 with a queued task ID, or a duplicate/ignored
status where appropriate. GitHub delivery retries and observability belong to
the webhook integration, not the dashboard's manual-submission form.

## Handling rate-limit responses in the UI

The inbound middleware limits `/api/` requests by the direct client IP (default
10 requests per 60 seconds). A rejected request returns HTTP 429:

```json
{"detail":"Too many requests; try again later"}
```

It also sets `Retry-After` to the number of seconds before the oldest request
in the active window expires. A dashboard should preserve the user's form
values, show an actionable error state/card, and avoid automatic rapid retries.
For example:

```ts
if (response.status === 429) {
  const retryAfter = Number(response.headers.get("Retry-After") ?? "60");
  setSubmissionState({
    kind: "rate-limited",
    message: body.detail ?? "Too many requests; try again later",
    retryAfterSeconds: retryAfter,
  });
  return;
}
```

The UI can render a card titled **Too many requests; try again later**, display
the server-provided retry time, and re-enable submission after the countdown.
The backend error body is a FastAPI `detail`; the header is authoritative for
the retry delay. Do not interpret HTTP 202 as completed work.

Rate-limiter Redis failures return HTTP 503 with a temporary-unavailability
message; they fail closed so the API does not bypass its configured limit. The
client can show a service-unavailable state and offer a deliberate retry.

## Dashboard telemetry data

The backend exposes completed data through:

- `GET /api/v1/reviews?limit=50` — newest completed review rows, with
  `repository`, `pull_number`, `model_tier`, `latency_seconds`, `total_tokens`,
  `estimated_cost_usd`, `estimated_savings_usd`, `created_at`, and `status`.
  The allowed `limit` range is 1–500.
- `GET /api/v1/metrics` — `total_reviews`,
  `average_latency_seconds`, `total_tokens`, and `total_savings_usd`.

Representative review row:

```json
{
  "repository": "owner/repository",
  "pull_number": 123,
  "model_tier": "groq",
  "latency_seconds": 18.42,
  "total_tokens": 4200,
  "estimated_cost_usd": 0.0007,
  "estimated_savings_usd": 0.02,
  "created_at": "2026-10-31T12:00:00+00:00",
  "status": "Completed"
}
```

The backend persists telemetry after GitHub accepts the completed review
comment. It does not expose in-progress Celery task state, and a just-queued
review may not appear in these endpoints until the worker has finished and
recorded the comment. The frontend can periodically refresh these read
endpoints, or use its established query/cache library:

```ts
async function loadReviews() {
  const [reviewsResponse, metricsResponse] = await Promise.all([
    fetch(`${apiBase}/api/v1/reviews?limit=50`),
    fetch(`${apiBase}/api/v1/metrics`),
  ]);
  if (!reviewsResponse.ok || !metricsResponse.ok) {
    throw new Error("Unable to load review telemetry");
  }
  return {
    reviews: await reviewsResponse.json(),
    metrics: await metricsResponse.json(),
  };
}
```

Use a modest refresh interval, pause polling when the tab is hidden, and handle
503 responses without discarding the last successfully loaded table. Since
there is no task-status endpoint, polling these endpoints only synchronizes
completed telemetry; it is not a precise job-progress indicator. A UI may
refresh after submission and continue periodic refreshes, but should label the
task as queued until a completed record arrives.

## Suggested dashboard state model

Keep form state separate from telemetry-query state. A practical manual-review
submission lifecycle is:

```text
idle -> submitting -> queued
                    -> validation-error
                    -> rate-limited (Retry-After countdown)
                    -> service-unavailable
```

The telemetry table can independently track `loading`, `loaded`, and
`refresh-error`, retaining the last loaded data during a temporary request
failure. The backend's SQLite telemetry is completion-oriented and does not
include task IDs, so the dashboard should not attempt to correlate a specific
task ID to a row unless that contract is extended.

## Integration checklist

- Set `VITE_API_BASE_URL` per environment; never put GitHub or LLM credentials
  in frontend environment variables.
- Configure explicit CORS origins or a same-origin proxy; the current backend
  has no CORS configuration.
- Send manual reviews to `POST /api/v1/reviews` with repository and positive
  pull number.
- Treat HTTP 202 as accepted/queued, not completed.
- Handle 429 using the `detail` response and `Retry-After` header.
- Refresh `GET /api/v1/reviews` and `GET /api/v1/metrics` for completed review
  telemetry; no task-status endpoint currently exists.
- Treat telemetry values as estimates where applicable; model pricing is
  configured in the backend.

## Related backend references

- [FastAPI entrypoint and middleware registration](../app/main.py)
- [Inbound IP rate limiter](../app/middleware/ip_rate_limiter.py)
- [Webhook endpoint](../app/api/webhooks.py)
- [Manual review and telemetry endpoints](../app/api/dashboard.py)
- [Celery processing workflow](../app/workers/celery_worker.py)
- [SQLite telemetry store](../app/services/telemetry_store.py)
