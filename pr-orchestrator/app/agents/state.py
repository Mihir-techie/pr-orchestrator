from typing import Any, TypedDict

from app.services.cost_router import ModelTier


class ReviewState(TypedDict, total=False):
    repository: str
    pull_number: int
    pull_author: str
    base_ref: str
    head_sha: str
    diff: str
    pruned_diff: str
    changed_files: list[str]
    changed_lines: int
    complexity_score: int
    sensitive: bool
    diff_truncated: bool
    model_tier: ModelTier
    code_review: str
    security_review: str
    reviewer_candidates: list[str]
    telemetry: list[dict[str, Any]]
