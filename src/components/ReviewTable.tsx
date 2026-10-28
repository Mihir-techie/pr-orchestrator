import {
  ArrowUpRight,
  Clock3,
  GitPullRequest,
  ListFilter,
  Sparkles,
} from "lucide-react";
import type { Review } from "../types";

interface ReviewTableProps {
  reviews: Review[];
  loading: boolean;
  error: string;
  onRefresh: () => void;
}

function formatModel(tier: Review["model_tier"]) {
  if (tier === "groq") return { label: "Groq", detail: "Lightweight", className: "groq" };
  if (tier === "gemini_pro") return { label: "Groq", detail: "Flagship", className: "pro" };
  return { label: "Groq", detail: "Lightweight", className: "groq" };
}

function formatLatency(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  return seconds < 60 ? `${seconds.toFixed(1)}s` : `${(seconds / 60).toFixed(1)}m`;
}

function formatCost(cost: number) {
  return Number.isFinite(cost) ? `$${cost.toFixed(4)}` : "—";
}

export function ReviewTable({ reviews, loading, error, onRefresh }: ReviewTableProps) {
  return (
    <section className="panel reviews-panel" id="reviews" aria-labelledby="reviews-title">
      <div className="reviews-heading">
        <div>
          <div className="eyebrow">ACTIVITY</div>
          <div className="title-row">
            <h2 id="reviews-title">Recent reviews</h2>
            {reviews.length > 0 && <span className="count-badge">{reviews.length}</span>}
          </div>
          <p>Your latest orchestrated pull requests.</p>
        </div>
        <button className="text-button" type="button" onClick={onRefresh} disabled={loading}>
          <ListFilter size={16} />
          Refresh
        </button>
      </div>

      <div className="review-table-wrap">
        <table className="review-table">
          <thead>
            <tr>
              <th>Pull request</th>
              <th>Model tier</th>
              <th><span className="th-icon"><Clock3 size={13} />Latency</span></th>
              <th>Tokens</th>
              <th>Est. cost</th>
              <th>Saved</th>
              <th>Completed</th>
              <th>Status</th>
              <th aria-label="Details" />
            </tr>
          </thead>
          <tbody>
            {reviews.map((review) => {
              const model = formatModel(review.model_tier);
              return (
                <tr key={`${review.repository}-${review.pull_number}`}>
                  <td>
                    <div className="pr-cell">
                      <span className="pr-icon"><GitPullRequest size={16} /></span>
                      <span>
                        <strong>{review.repository}</strong>
                        <small>PR #{review.pull_number}</small>
                      </span>
                    </div>
                  </td>
                  <td>
                    <span className={`model-badge ${model.className}`}>
                      <span className="model-dot" />
                      <span>{model.label}<small>{model.detail}</small></span>
                    </span>
                  </td>
                  <td className="table-number">{formatLatency(review.latency_seconds)}</td>
                  <td className="table-number">{new Intl.NumberFormat("en-US").format(review.total_tokens)}</td>
                  <td className="table-number">{formatCost(review.estimated_cost_usd)}</td>
                  <td className="table-number">{formatCost(review.estimated_savings_usd)}</td>
                  <td className="table-number">{new Date(review.created_at).toLocaleString()}</td>
                  <td>
                    <span className="status-badge">
                      <span />
                      {review.status || "Completed"}
                    </span>
                  </td>
                  <td><ArrowUpRight size={16} className="row-arrow" /></td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {!loading && reviews.length === 0 && (
          <div className="empty-state">
            <span className="empty-icon"><Sparkles size={21} /></span>
            <strong>{error ? "Review history isn’t connected yet" : "No reviews yet"}</strong>
            <p>
              {error ||
                "When a review history endpoint is available, your orchestrated pull requests will show up here."}
            </p>
            {error && (
              <span className="empty-endpoint">Expected endpoint: GET /api/v1/reviews</span>
            )}
          </div>
        )}
        {loading && reviews.length === 0 && (
          <div className="empty-state loading-state">
            <span className="loader-ring" />
            <strong>Checking for recent reviews</strong>
          </div>
        )}
      </div>
      <div className="table-footer">
        <span>Showing {reviews.length} review{reviews.length === 1 ? "" : "s"}</span>
        <span className="table-footer-live"><span />Live data when connected</span>
      </div>
    </section>
  );
}
