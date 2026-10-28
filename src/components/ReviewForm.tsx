import { useState, type FormEvent } from "react";
import { ArrowUpRight, CircleCheck, GitPullRequest, LoaderCircle } from "lucide-react";
import { ApiError, triggerReview } from "../services/api";
import type { ReviewRequest } from "../types";

interface ReviewFormProps {
  onSuccess: (
    message: string,
    request?: ReviewRequest,
    taskId?: string,
  ) => void;
}

export function ReviewForm({ onSuccess }: ReviewFormProps) {
  const [repository, setRepository] = useState("");
  const [pullNumber, setPullNumber] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setLoading(true);

    try {
      const result = await triggerReview({
        repository: repository.trim(),
        pull_number: Number(pullNumber),
      });
      onSuccess(
        `Review queued for ${result.repository}#${result.pull_number}. Task ${result.task_id}.`,
        { repository: result.repository, pull_number: result.pull_number },
        result.task_id,
      );
      setError("");
    } catch (requestError) {
      setError(
        requestError instanceof ApiError
          ? requestError.message
          : "The review request could not be submitted.",
      );
    } finally {
      setLoading(false);
    }
  }

  function simulateLocally() {
    setError("");
    onSuccess(
      `Simulation only: ${repository.trim()}#${pullNumber} is ready. Nothing was sent to the backend or added to telemetry.`,
    );
  }

  const repositoryValue = repository.trim();
  const repositoryIsValid =
    /^[^/\s]+\/[^/\s]+$/.test(repositoryValue) ||
    /^https:\/\/github\.com\/[^/\s]+\/[^/\s]+(?:\/pull\/\d+)?\/?$/.test(
      repositoryValue,
    );
  const pullNumberIsValid = Number.isSafeInteger(Number(pullNumber)) && Number(pullNumber) > 0;

  return (
    <section className="panel trigger-panel" aria-labelledby="trigger-title">
      <div className="panel-heading">
        <div>
          <div className="eyebrow">ON-DEMAND</div>
          <h2 id="trigger-title">Start a review</h2>
          <p>Send a pull request to your review workflow.</p>
        </div>
        <span className="panel-heading-icon">
          <GitPullRequest size={19} />
        </span>
      </div>

      <form className="review-form" onSubmit={handleSubmit}>
        <label htmlFor="repository">Repository</label>
        <div className="input-wrap">
          <input
            id="repository"
            name="repository"
            placeholder="acme/product or GitHub URL"
            value={repository}
            onChange={(event) => setRepository(event.target.value)}
            autoComplete="off"
            required
            aria-describedby="repository-hint"
          />
        </div>
        <small id="repository-hint" className="field-hint">
          Use owner/repository or a GitHub repository URL
        </small>

        <label htmlFor="pull-number" className="pr-label">
          Pull request number
        </label>
        <div className="input-wrap number-input">
          <span className="input-prefix">#</span>
          <input
            id="pull-number"
            name="pull-number"
            type="number"
            min="1"
            step="1"
            placeholder="128"
            value={pullNumber}
            onChange={(event) => setPullNumber(event.target.value)}
            required
          />
        </div>

        {error && (
          <div className="form-message error-message" role="alert">
            {error}
          </div>
        )}

        <button
          className="primary-button"
          type="submit"
          disabled={loading || !repositoryIsValid || !pullNumberIsValid}
        >
          {loading ? (
            <>
              <LoaderCircle className="spin" size={17} />
              Sending request...
            </>
          ) : (
            <>
              Start review
              <ArrowUpRight size={17} />
            </>
          )}
        </button>
        <button
          className="simulation-button"
          type="button"
          onClick={simulateLocally}
          disabled={loading || !repositoryIsValid || !pullNumberIsValid}
        >
          Simulate locally
        </button>
      </form>

      <div className="form-footnote">
        <CircleCheck size={15} />
        <span>Reviews run asynchronously in the background.</span>
      </div>
    </section>
  );
}
