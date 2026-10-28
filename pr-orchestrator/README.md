# PR Orchestrator

Asynchronous GitHub pull-request review service using FastAPI, Celery/Redis,
LangGraph, Groq, and Google Gemini.

## Configure

Copy `.env.example` to the ignored `.env` file and add credentials before
starting the service. `REDIS_URL` is required and must be a valid cloud Redis
URL; there is no local Redis fallback:

```dotenv
REDIS_URL=rediss://default:<rotated-password>@<redis-host>:<port>
GITHUB_TOKEN=...
GITHUB_WEBHOOK_SECRET=...
GROQ_API_KEY=...
GROQ_MODEL=openai/gpt-oss-20b
GROQ_FLAGSHIP_MODEL=openai/gpt-oss-120b
```

`REDIS_URL` is used for the Celery broker, Celery result backend, webhook
deduplication, Redis helpers, and both Compose containers. Compose does not
start a local Redis service. Do not commit `.env`; `.env.example` contains safe
placeholders. Rotate any credential shared outside your secret manager before
configuring it.

Create a GitHub webhook targeting
`https://<your-host>/api/v1/webhooks/github`, choose JSON payloads, configure the
same webhook secret, and subscribe to **Pull requests**. GitHub App or token
permissions must include pull-request read/write, issue comments write, contents
read, and permission to request reviewers. The endpoint validates GitHub's
`X-Hub-Signature-256`, accepts `opened` and `synchronize` actions, deduplicates
delivery IDs in Redis, and responds with HTTP 202 after enqueueing the task.

## Run with Docker Compose

```powershell
docker compose up --build
```

The API is available at `http://localhost:8000`; `/health` checks Redis
connectivity. The worker retries transient processing failures with bounded
exponential backoff. Configure the Groq API key to enable model inference.
Model choice alone cannot guarantee zero charges: provider free-tier quotas,
account settings, and pricing apply. Set provider-side quotas and billing
limits before enabling API keys.

Completed review telemetry is saved to `data/telemetry.sqlite3`. Docker Compose
shares this directory between the API and worker through the persistent
`telemetry_data` volume. The read-only dashboard endpoints are
`GET /api/v1/metrics` and `GET /api/v1/reviews` (optionally `?limit=50`, maximum
500). Metrics include review count, average latency, total tokens, and estimated
savings; review history includes model tier, latency, tokens, cost, savings,
and completion timestamp. Telemetry is recorded after GitHub successfully
accepts the completed review comment. Existing logs are not backfilled.
Manual reviews can be queued with `POST /api/v1/reviews`, using an
`owner/repo` name or GitHub HTTPS URL and a pull-request number. The endpoint
loads actual PR metadata and queues the existing Celery review task.

The lightweight and flagship Groq models are configured with `GROQ_MODEL`
(default: `openai/gpt-oss-20b`) and `GROQ_FLAGSHIP_MODEL` (default:
`openai/gpt-oss-120b`). Both routing tiers use Groq. After changing model
configuration, recreate both services so they load the current `.env` values:
`docker compose up -d --build --force-recreate worker web`. Do not purge Redis
to apply key changes; the worker uses bounded Celery retries, and purging can
discard queued webhook and manual-review jobs.

The dashboard's `POST /api/v1/reviews` endpoint queues manual requests through
the same worker task as GitHub webhooks. Provider SDK retries are disabled so
transient errors use the worker's bounded retry policy; explicit exhausted
daily-quota errors are not retried. Check worker status and logs with
`docker compose ps worker` and `docker compose logs --tail=100 worker`.

## Workflow

The worker fetches the PR diff, removes blank and recognizable full-line comment changes,
computes changed-line and Python AST complexity signals, and truncates oversized
prompts at `MAX_DIFF_CHARS`. Changes in `auth`, `crypto`, `payments`, or
`db/migrations` paths route to the flagship tier; other diffs select a tier by
complexity. The LangGraph workflow runs code review, security review, then
reviewer assignment. Assignment prefers CODEOWNERS and falls back to recent
file commit authors, excluding the PR author.

Review output and worker logs include model usage, estimated spend, processing
latency, and estimated savings relative to the configured Gemini Pro baseline. Pricing values in
`app/config.py` are estimates and should be kept aligned with provider pricing.
This is an LLM-assisted review, not a replacement for CI, deterministic security
scanners, or human approval.
