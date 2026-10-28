export type ModelTier = "groq" | "gemini_flash" | "gemini_pro";

export interface Review {
  repository: string;
  pull_number: number;
  model_tier: ModelTier;
  latency_seconds: number;
  total_tokens: number;
  estimated_cost_usd: number;
  estimated_savings_usd: number;
  status: string;
  created_at: string;
}

export interface Metrics {
  total_reviews: number;
  average_latency_seconds: number;
  total_tokens: number;
  total_savings_usd: number;
}

export interface ReviewRequest {
  repository: string;
  pull_number: number;
}

export interface ReviewAccepted extends ReviewRequest {
  status: "queued";
  task_id: string;
}
