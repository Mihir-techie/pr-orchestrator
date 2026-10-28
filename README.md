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
exponential backoff. Configure the Groq API key to enable model inference.
Model choice alone cannot guarantee zero charges: provider free-tier quotas,
account settings, and pricing apply. Set provider-side quotas and billing
limits before enabling API keys.

Completed review telemetry is saved to `data/telemetry.sqlite3`. The `web` and
`worker` containers share the persistent `telemetry_data` volume. The dashboard
reads `GET /api/v1/metrics` and `GET /api/v1/reviews`; the latter accepts an
optional `limit` query parameter (1–500, default 50). Metrics include review
count, average latency, total tokens, and estimated savings. Each review
includes its model tier, latency, token count, cost, savings, and timestamp.
Telemetry is recorded after GitHub accepts the completed review comment;
existing logs are not backfilled.

Manual reviews can be queued with `POST /api/v1/reviews` using
`{"repository":"owner/repo","pull_number":123}`. The repository may also be a
GitHub HTTPS URL. The API verifies that the configured GitHub token can load
the pull request, then queues it through the existing Celery review task.

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



Replaced the retired default model with openai/gpt-oss-20b, including the active root .env, both .env.example files, and both READMEs. Groq recommends GPT-OSS models as replacements for the retired Llama models; free-tier access and limits still depend on your Groq account. Groq deprecation

Aligned model selection with the router: Groq requests now use GROQ_MODEL; Gemini tiers use their configured Google models and require GOOGLE_API_KEY. Gemini requests will no longer silently go to Groq.
Stopped retrying permanent LLM failures: missing provider keys and permanent 4xx errs such as a decommissioned model fail clearly without repeated Celery retries. Transient failures such as rate limits and server errors remain retryable.
Fixed per-tier cost calculations and added the selected model name to review telemetry and logs.
The main changes are in llm.py, config.py,
and celery_worker.py. I added tests in test_llm.py.

Verification: Docker image build succeeded and all 16 tests passed. The tests cover model selection, provider routing, costs, telemetry, retry behavior, and existing webhook/routing behavior.

Run the tests from D:\pr-orchestrator:

docker compose build
docker run --rm -v "${PWD}\pr-orchestrator\tests:/tests" pr-orchestrator-worker:latest python -m unittest discover -s /tests -v
Then recreate the services to load the updated .env and code:

docker compose up -d --build --force-recreate worker web
docker compose logs -f worker