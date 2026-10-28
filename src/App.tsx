import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  ArrowDownRight,
  Clock3,
  Coins,
  GitPullRequest,
  RefreshCw,
  Sparkles,
  Zap,
} from "lucide-react";
import { MetricCard } from "./components/MetricCard";
import { ReviewForm } from "./components/ReviewForm";
import { ReviewTable } from "./components/ReviewTable";
import { Sidebar } from "./components/Sidebar";
import { ApiError, getHealth, getMetrics, getReviews } from "./services/api";
import type { Metrics, Review, ReviewRequest } from "./types";

const EMPTY_METRICS: Metrics = {
  total_reviews: 0,
  average_latency_seconds: 0,
  total_tokens: 0,
  total_savings_usd: 0,
};

function formatNumber(value: number) {
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
}

function formatLatency(seconds: number) {
  if (!Number.isFinite(seconds) || seconds < 0) return "—";
  return seconds < 60 ? `${seconds.toFixed(1)}s` : `${(seconds / 60).toFixed(1)}m`;
}

function getErrorMessage(error: unknown) {
  return error instanceof ApiError ? error.message : "Unable to load data from the API.";
}

export default function App() {
  const [metrics, setMetrics] = useState(EMPTY_METRICS);
  const [reviews, setReviews] = useState<Review[]>([]);
  const [health, setHealth] = useState<"checking" | "online" | "offline">("checking");
  const [metricsError, setMetricsError] = useState("");
  const [reviewsError, setReviewsError] = useState("");
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);
  const [notice, setNotice] = useState("");
  const [pendingReview, setPendingReview] = useState<
    (ReviewRequest & { previousCreatedAt?: string; taskId: string }) | null
  >(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    const [healthResult, metricsResult, reviewsResult] = await Promise.allSettled([
      getHealth(),
      getMetrics(),
      getReviews(),
    ]);

    if (healthResult.status === "fulfilled") {
      setHealth(healthResult.value.status === "ok" ? "online" : "offline");
    } else {
      setHealth("offline");
    }

    if (metricsResult.status === "fulfilled") {
      setMetrics(metricsResult.value);
      setMetricsError("");
    } else {
      setMetrics(EMPTY_METRICS);
      setMetricsError(getErrorMessage(metricsResult.reason));
    }

    if (reviewsResult.status === "fulfilled") {
      setReviews(reviewsResult.value);
      setReviewsError("");
    } else {
      setReviews([]);
      setReviewsError(getErrorMessage(reviewsResult.reason));
    }

    setLastUpdated(new Date());
    setLoading(false);
  }, []);

  useEffect(() => {
    void refresh();
    const intervalId = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(intervalId);
  }, [refresh]);

  useEffect(() => {
    if (!pendingReview) return;

    let active = true;
    let polling = false;
    const pollForCompletion = async () => {
      if (polling) return;
      polling = true;
      try {
        const [metricsResult, reviewsResult] = await Promise.allSettled([
          getMetrics(),
          getReviews(),
        ]);
        if (!active) return;
        if (metricsResult.status === "fulfilled") {
          setMetrics(metricsResult.value);
          setMetricsError("");
        }
        if (reviewsResult.status === "fulfilled") {
          setReviews(reviewsResult.value);
          setReviewsError("");
          const completedReview = reviewsResult.value.find(
            (review) =>
              review.repository.toLowerCase() ===
                pendingReview.repository.toLowerCase() &&
              review.pull_number === pendingReview.pull_number &&
              review.created_at !== pendingReview.previousCreatedAt,
          );
          if (completedReview) {
            setPendingReview(null);
            setNotice(
              `Review completed for ${completedReview.repository}#${completedReview.pull_number}. Dashboard updated.`,
            );
          }
        }
      } finally {
        polling = false;
      }
    };

    void pollForCompletion();
    const intervalId = window.setInterval(() => void pollForCompletion(), 5000);
    const timeoutId = window.setTimeout(() => {
      if (!active) return;
      setPendingReview(null);
      setNotice(
        `Review task ${pendingReview.taskId} is still processing. Refresh the dashboard later to check its result.`,
      );
    }, 10 * 60 * 1000);

    return () => {
      active = false;
      window.clearInterval(intervalId);
      window.clearTimeout(timeoutId);
    };
  }, [pendingReview]);

  function handleReviewSuccess(
    message: string,
    request?: ReviewRequest,
    taskId?: string,
  ) {
    setNotice(message);
    if (!request || !taskId) {
      window.setTimeout(
        () => setNotice((current) => (current === message ? "" : current)),
        5000,
      );
      return;
    }
    const previousCreatedAt = reviews.find(
      (review) =>
        review.repository.toLowerCase() === request.repository.toLowerCase() &&
        review.pull_number === request.pull_number,
    )?.created_at;
    setPendingReview({
      ...request,
      previousCreatedAt,
      taskId,
    });
    void refresh();
    window.setTimeout(
      () => setNotice((current) => (current === message ? "" : current)),
      5000,
    );
  }

  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-content" id="overview">
        <header className="topbar">
          <div className="breadcrumbs"><span>Workspace</span><span>/</span><strong>Overview</strong></div>
          <div className="topbar-right">
            <span className="last-updated">
              <span className={`connection-dot ${health}`} />
              {health === "online" ? "API connected" : health === "offline" ? "API unavailable" : "Connecting"}
            </span>
            <button className="icon-button" type="button" onClick={() => void refresh()} disabled={loading} aria-label="Refresh dashboard">
              <RefreshCw size={17} className={loading ? "spin" : ""} />
            </button>
            <span className="topbar-divider" />
            <span className="topbar-avatar">PF</span>
          </div>
        </header>

        <div className="page-content">
          <section className="welcome-row">
            <div>
              <div className="welcome-kicker"><span /> YOUR REVIEW COMMAND CENTER</div>
              <h1>Welcome back, <span>developer.</span></h1>
              <p>Here’s what’s happening across your pull request reviews.</p>
            </div>
            <div className="date-chip"><Activity size={15} /> Live overview</div>
          </section>

          {health === "offline" && (
            <div className="connection-banner" role="status">
              <span className="banner-icon"><Zap size={17} /></span>
              <span><strong>Can’t reach your API.</strong> Make sure the backend is running at localhost:8000.</span>
              <button type="button" onClick={() => void refresh()}>Retry</button>
            </div>
          )}

          {notice && (
            <div className="connection-banner success-banner" role="status">
              <span className="banner-icon"><Sparkles size={17} /></span>
              <span>{notice}</span>
              <button type="button" onClick={() => setNotice("")} aria-label="Dismiss notice">Dismiss</button>
            </div>
          )}

          {pendingReview && (
            <div className="connection-banner success-banner" role="status">
              <span className="banner-icon"><RefreshCw size={16} className="spin" /></span>
              <span>
                Review for <strong>{pendingReview.repository}#{pendingReview.pull_number}</strong> is queued. The dashboard is checking for completion.
              </span>
            </div>
          )}

          <div className="section-heading">
            <div>
              <h2>Review performance</h2>
              <p>Insights across every AI-assisted code review.</p>
            </div>
            <span className="period-label"><span /> All time</span>
          </div>

          <section className="metrics-grid" aria-label="Review metrics">
            <MetricCard
              label="Pull requests reviewed"
              value={formatNumber(metrics.total_reviews)}
              detail={metricsError ? "Telemetry endpoint not connected" : "Total reviews processed"}
              icon={GitPullRequest}
              accent="violet"
            />
            <MetricCard
              label="Average review time"
              value={formatLatency(metrics.average_latency_seconds)}
              detail="End-to-end workflow latency"
              icon={Clock3}
              accent="blue"
            />
            <MetricCard
              label="Tokens processed"
              value={formatNumber(metrics.total_tokens)}
              detail="Input + output tokens"
              icon={Zap}
              accent="amber"
            />
            <MetricCard
              label="Estimated cost savings"
              value={`$${metrics.total_savings_usd.toFixed(2)}`}
              detail="Compared with Gemini Pro"
              icon={Coins}
              accent="green"
            />
          </section>

          {metricsError && health === "online" && (
            <div className="telemetry-note">
              <ArrowDownRight size={15} />
              Review telemetry could not be loaded. Check the backend logs; displayed metrics are fallback values, not inferred from logs.
              <span>GET /api/v1/metrics</span>
            </div>
          )}

          <div className="content-grid">
            <ReviewTable
              reviews={reviews}
              loading={loading}
              error={reviewsError}
              onRefresh={() => void refresh()}
            />
            <ReviewForm onSuccess={handleReviewSuccess} />
          </div>

          <footer className="page-footer">
            <span>Powered by your PR Orchestrator</span>
            <span>{lastUpdated ? `Last checked ${lastUpdated.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}` : "Connecting to API..."}</span>
          </footer>
        </div>
      </main>
    </div>
  );
}
