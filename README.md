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
GOOGLE_API_KEY=...
GROQ_MODEL=llama-3.1-8b-instant
GEMINI_FLASH_MODEL=gemini-2.5-flash
GEMINI_PRO_MODEL=gemini-2.5-flash
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

Keep the repository in a local folder outside OneDrive (for example,
`C:\dev\pr-orchestrator`). Docker Desktop BuildKit can fail to read OneDrive
Files On-Demand placeholders while sending the build context, with errors such
as `invalid file request app/__init__.py`. Moving the checkout outside the
synced folder is the most reliable fix. If you keep it in OneDrive, mark the
repository as **Always keep on this device** and let it finish syncing before
building.

The `.dockerignore` file keeps local credentials and files not needed by the
image out of the build context.

```powershell
docker compose up --build
```

The API is available at `http://localhost:8000`; `/health` checks Redis
connectivity. The worker retries transient processing failures with bounded
exponential backoff. Configure the Groq and Google API keys to enable model
routing. Both Gemini routing tiers default to the Flash model. Model choice
alone cannot guarantee zero charges: provider free-tier quotas, account
settings, and pricing apply. Set provider-side quotas and billing limits before
enabling API keys.

## Workflow

The worker fetches the PR diff, removes blank and recognizable full-line comment changes,
computes changed-line and Python AST complexity signals, and truncates oversized
prompts at `MAX_DIFF_CHARS`. Changes in `auth`, `crypto`, `payments`, or
`db/migrations` paths route to Gemini Pro; other diffs route to Groq, Gemini
Flash, or Gemini Pro by complexity. The LangGraph workflow runs code review,
security review, then reviewer assignment. Assignment prefers CODEOWNERS and
falls back to recent file commit authors, excluding the PR author. Sensitive
or complex diffs use the flagship routing tier, which is configured to use the
Flash model by default.

Review output and worker logs include model usage, estimated spend, processing
latency, and estimated savings relative to the configured Gemini Pro baseline. Pricing values in
`app/config.py` are estimates and should be kept aligned with provider pricing.
This is an LLM-assisted review, not a replacement for CI, deterministic security
scanners, or human approval.
