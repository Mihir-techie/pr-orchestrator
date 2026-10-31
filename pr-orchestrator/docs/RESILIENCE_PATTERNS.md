# MergeFlow Resilience Patterns

This document describes the rate-control and payload-boundary patterns in the
MergeFlow backend. The implementation uses Redis for coordination between API
processes and Celery workers, so limits are shared rather than local to one
process.

## 1. Outbound LLM token budget

### Why

An agent workflow can make multiple model calls for a single pull request, and
multiple Celery workers can process reviews concurrently. A per-process counter
cannot protect a provider-wide limit in that environment. Coordinating estimated
input usage in Redis spreads calls over time and reduces avoidable provider
throttling. Waiting asynchronously also keeps a worker from synchronously
blocking its event loop while it waits for budget.

The configured budget is an application control, not a statement of any
provider's current limit. The default is `LLM_TOKENS_PER_MINUTE=30000`. Set it
below the applicable provider/model/account limit, accounting for output tokens,
other applications using the same credentials, and provider-specific quota
rules. For example, if the effective Groq quota for the deployed model is 8,000
tokens per minute, configure a lower value than 8,000; do not rely on the
default.

### How the implementation works

`app/services/rate_limiter.py` implements a Redis-backed **token bucket**, not
a strict fixed or rolling-window counter:

1. `acquire_tokens(provider, requested_tokens, tokens_per_minute)` validates
   the request and identifies the provider bucket. Prompts larger than the
   bucket capacity fail explicitly because they can never acquire enough tokens.
2. One Lua script executes atomically in Redis. It obtains Redis server time,
   loads the bucket's remaining `tokens` and `updated_at` values, then refills
   the bucket continuously at `capacity / 60 seconds`, up to the configured
   capacity.
3. If enough tokens are present, the script deducts the estimate and returns
   success. Otherwise, it returns the time needed to refill the shortfall.
4. The Python coroutine awaits `asyncio.sleep()` for that interval and retries
   the atomic reservation. Redis keys expire after two refill windows without
   activity.

Redis server time avoids relying on worker clock synchronization. The Lua
operation ensures simultaneous workers cannot reserve the same tokens. This
continuous-refill bucket allows a burst up to one minute's capacity and then
smooths further consumption; it is not equivalent to a hard rolling-window
ceiling.

```python
await acquire_tokens(
    "groq",
    estimate_tokens(f"{system_prompt}\n{user_prompt}"),
    settings.llm_tokens_per_minute,
)
```

`app/services/llm.py` performs this reservation immediately before the model
call. `estimate_tokens` currently uses a regex-based word/punctuation estimate
from `app/services/cost_router.py`; the service does not use `tiktoken`. The
reservation covers estimated prompt/input tokens, not generated output. It is
conservative to use a budget below the provider's limit, since output usage and
other callers are outside this estimate. A reservation is not refunded if a
provider call subsequently fails.

The current `_get_chat_model` constructs `ChatGroq` for all routing tiers:
`groq`, `gemini_flash`, and `gemini_pro` select different configured Groq model
names. Consequently, the current `"groq"` bucket protects these actual calls.
Although Google credentials and Gemini model settings exist in configuration,
this code path does not currently invoke Gemini.

### Operations and failure behavior

Redis is a required dependency for reservations. Redis errors are not silently
ignored: the invocation fails and the Celery task's existing bounded retry
policy can retry transient errors. This favors not exceeding a shared provider
budget over operating without rate protection. Monitoring should include Redis
availability, reservation delay, LLM failure/retry counts, and provider quota
responses. The current implementation does not emit a dedicated reservation
wait metric.

Configure the value through `.env`:

```dotenv
LLM_TOKENS_PER_MINUTE=7000
```

Choose a value based on the actual provider plan, model, and shared credential
usage. The example is illustrative, not a recommended universal quota.

## 2. Context-window and diff guardrails

### Why

Very large pull-request diffs can exceed model context limits, inflate latency
and cost, or cause otherwise useful reviews to fail before the model can
respond. A deterministic size bound limits the amount of changed code included
in each review prompt, while preserving indicators that a review was partial.

### How the implementation works

`app/services/cost_router.py` parses a unified diff with `unidiff`, removes blank
and recognizable full-line comment changes, and builds one pruned section per
file. It also calculates changed-line and Python AST complexity signals and
checks changed paths for security-sensitive areas.

The hard maximum is `MAX_DIFF_CHARS = 10000` in `app/config.py`. Settings may
lower this maximum through `MAX_DIFF_CHARS`; validation does not permit a value
above the hard cap. When the pruned diff exceeds the configured limit:

1. Sections from sensitive paths sort before non-sensitive sections. The
   detector recognizes path components/stems such as `auth`, `crypto`,
   `payments`, and `db/migrations`.
2. Sections are added in priority order until the available character budget
   is used. A partial section is cut at a newline where possible.
3. A `[diff truncated]` marker is included within the configured maximum.
4. The `DiffAnalysis.truncated` flag flows into the worker state and the
   completed GitHub review report, warning readers to inspect the full changes.

The limiter applies to the **pruned diff**, which is what agent prompts include.
It does not truncate the separately retained raw `diff` field in worker state.
The cap is measured in characters, not model tokens; the tokenizer estimate is
separate. Character limits provide a simple deterministic payload bound but do
not translate exactly to a provider token count.

### Trade-offs

Sensitive sections are prioritized, not guaranteed to be complete: if a
sensitive section itself is larger than the available space, that section is
also cut. Some nonsensitive changes may be omitted. The generated review
explicitly reports truncation, so it must not be interpreted as a complete
review of every changed line.

## 3. Inbound IP rate limiting

### Why

Webhook and dashboard API routes can be flooded with repeated traffic, which
consumes API, Redis, and worker capacity. A shared IP limit rejects excess
requests before endpoint processing and gives clients a retry hint.

### How the implementation works

`app/main.py` registers `IPRateLimitMiddleware` from
`app/middleware/ip_rate_limiter.py`. The middleware applies to request paths
beginning with `/api/`; `/health` is intentionally outside this limit.

The Redis Lua script implements a true sliding window using a sorted set:

1. It uses Redis server time in milliseconds and removes request timestamps at
   or before the active-window cutoff.
2. It counts the remaining sorted-set members for the IP.
3. If the count is at the configured maximum, it returns the time remaining
   until the oldest request leaves the window.
4. Otherwise, it records a unique request member with the current timestamp
   and expires the sorted-set key after the window.

The middleware hashes the direct connection's client IP before constructing the
Redis key. The defaults are 10 requests per 60 seconds, configurable through
`IP_RATE_LIMIT_REQUESTS` and `IP_RATE_LIMIT_WINDOW_SECONDS`.

When blocked, middleware returns:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 2
Content-Type: application/json

{"detail":"Too many requests; try again later"}
```

`Retry-After` is the ceiling, in seconds, of the calculated milliseconds until
the oldest request expires (minimum one second). On Redis errors, the middleware
logs the error and returns HTTP 503 rather than silently bypassing protection.

### Deployment considerations

The client address is `request.client.host`; forwarded headers are not trusted
by this middleware. Behind a reverse proxy, configure trusted-proxy handling at
the ASGI/deployment boundary and restrict direct access to the application, or
clients may be grouped under the proxy IP. Do not blindly trust arbitrary
`X-Forwarded-For` values. A per-IP rate limiter is one availability control,
not a complete DDoS mitigation; pair it with edge filtering, request-size
limits, connection controls, and provider/Redis capacity planning.

## Related implementation

- [Configuration](../app/config.py)
- [Redis client](../app/services/redis_client.py)
- [LLM rate limiter](../app/services/rate_limiter.py)
- [LLM invocation](../app/services/llm.py)
- [Diff analysis and model routing](../app/services/cost_router.py)
- [IP middleware](../app/middleware/ip_rate_limiter.py)
- [FastAPI entrypoint](../app/main.py)
