# PR Orchestrator dashboard

## Run locally

From the repository root, install dependencies and start the Vite development server:

```powershell
npm install
npm run dev
```

Vite proxies `/api` and `/health` to `http://localhost:8000`, so the browser
doesn't need a cross-origin request during local development. Start the FastAPI
service separately.

For a deployed frontend, set `VITE_API_BASE_URL` to the API origin when building.
The API must allow that frontend origin through its CORS policy.

## API contract

The dashboard reads these endpoints:

- `GET /health` — backend availability.
- `GET /api/v1/metrics` — `{ "total_reviews": 0, "average_latency_seconds": 0, "total_tokens": 0, "total_savings_usd": 0 }`; empty history returns zero totals.
- `GET /api/v1/reviews` — a list of reviews with `repository`, `pull_number`,
  `model_tier` (`groq`, `gemini_flash`, or `gemini_pro`), `latency_seconds`,
  `total_tokens`, `estimated_cost_usd`, `estimated_savings_usd`, `status`, and
  `created_at`. Supports an optional `limit` query parameter (1–500, default 50).
- `POST /api/v1/reviews` — `{ "repository": "owner/repo", "pull_number": 123 }`.

The FastAPI backend implements `/health`, the signed
`POST /api/v1/webhooks/github` endpoint, and the read-only dashboard metrics and
review history endpoints above. `POST /api/v1/reviews` validates an owner/repo
or GitHub URL, loads the PR metadata using the configured GitHub token, and
queues the existing review task. The dashboard polls while a submitted review
is processing, then refreshes its metrics and history when telemetry is saved.
Completed reviews are persisted after GitHub accepts the review comment. The
GitHub webhook requires a valid GitHub signature and must not be called
directly from a browser.

## Structure

- `src/App.tsx` — dashboard state, health status, and metric orchestration.
- `src/components/` — sidebar, metric cards, review feed, and trigger form.
- `src/services/api.ts` — typed fetch client and API error handling.
- `src/index.css` — responsive layout and Tailwind base styles.
- `vite.config.ts` — local API proxy.
