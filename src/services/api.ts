import type { Metrics, Review, ReviewAccepted, ReviewRequest } from "../types";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isNonNegativeNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function isMetrics(value: unknown): value is Metrics {
  return (
    isRecord(value) &&
    isNonNegativeNumber(value.total_reviews) &&
    isNonNegativeNumber(value.average_latency_seconds) &&
    isNonNegativeNumber(value.total_tokens) &&
    isNonNegativeNumber(value.total_savings_usd)
  );
}

function isReview(value: unknown): value is Review {
  return (
    isRecord(value) &&
    typeof value.repository === "string" &&
    typeof value.pull_number === "number" &&
    Number.isSafeInteger(value.pull_number) &&
    value.pull_number > 0 &&
    (value.model_tier === "groq" ||
      value.model_tier === "gemini_flash" ||
      value.model_tier === "gemini_pro") &&
    isNonNegativeNumber(value.latency_seconds) &&
    isNonNegativeNumber(value.total_tokens) &&
    isNonNegativeNumber(value.estimated_cost_usd) &&
    isNonNegativeNumber(value.estimated_savings_usd) &&
    typeof value.status === "string" &&
    typeof value.created_at === "string"
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        Accept: "application/json",
        ...(init?.body ? { "Content-Type": "application/json" } : {}),
        ...init?.headers,
      },
    });
  } catch {
    throw new ApiError(
      "Could not reach the API. Check that the FastAPI service is running at http://localhost:8000.",
    );
  }

  if (!response.ok) {
    const detail = await response
      .json()
      .then((body: { detail?: unknown }) =>
        typeof body.detail === "string" ? body.detail : undefined,
      )
      .catch(() => undefined);

    throw new ApiError(
      detail ?? `The API request failed with status ${response.status}.`,
      response.status,
    );
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export function getHealth(): Promise<{ status: string }> {
  return request<unknown>("/health").then((value) => {
    if (isRecord(value) && typeof value.status === "string") {
      return { status: value.status };
    }
    throw new ApiError("The health endpoint returned an unexpected response.");
  });
}

export async function getMetrics(): Promise<Metrics> {
  const value = await request<unknown>("/api/v1/metrics");
  if (isMetrics(value)) return value;
  throw new ApiError("The metrics endpoint returned an unexpected response.");
}

export async function getReviews(): Promise<Review[]> {
  const value = await request<unknown>("/api/v1/reviews");
  if (Array.isArray(value) && value.every(isReview)) return value;
  throw new ApiError("The review history endpoint returned an unexpected response.");
}

export async function triggerReview(
  payload: ReviewRequest,
): Promise<ReviewAccepted> {
  const value = await request<unknown>("/api/v1/reviews", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  if (
    isRecord(value) &&
    value.status === "queued" &&
    typeof value.task_id === "string" &&
    typeof value.repository === "string" &&
    typeof value.pull_number === "number"
  ) {
    return {
      status: "queued",
      task_id: value.task_id,
      repository: value.repository,
      pull_number: value.pull_number,
    };
  }
  throw new ApiError("The review endpoint returned an unexpected response.");
}
