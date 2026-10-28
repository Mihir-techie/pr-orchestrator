import os
import re
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, TypedDict, cast

ModelTier = Literal["groq", "gemini_flash", "gemini_pro"]


class ReviewRecord(TypedDict):
    repository: str
    pull_number: int
    model_tier: ModelTier
    latency_seconds: float
    total_tokens: int
    estimated_cost_usd: float
    estimated_savings_usd: float
    created_at: str
    status: str


class Metrics(TypedDict):
    total_reviews: int
    average_latency_seconds: float
    total_tokens: int
    total_savings_usd: float


_REPORT_FIELDS = {
    "model_tier": re.compile(
        r"^- Model route: `(groq|gemini_flash|gemini_pro)`$", re.MULTILINE
    ),
    "total_tokens": re.compile(r"^- Tokens: (\d+)$", re.MULTILINE),
    "estimated_cost_usd": re.compile(
        r"^- Estimated LLM cost: \$([0-9]+(?:\.[0-9]+)?)$", re.MULTILINE
    ),
    "estimated_savings_usd": re.compile(
        r"^- Estimated savings vs\. Gemini Pro: \$([0-9]+(?:\.[0-9]+)?)$",
        re.MULTILINE,
    ),
    "latency_seconds": re.compile(
        r"^- Review workflow latency: ([0-9]+(?:\.[0-9]+)?)s$", re.MULTILINE
    ),
}


def _database_path(path: str | Path | None = None) -> Path:
    return Path(path or os.getenv("TELEMETRY_DB_PATH", "data/telemetry.sqlite3"))


def _connect(path: str | Path | None = None) -> sqlite3.Connection:
    database_path = _database_path(path)
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS reviews (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository TEXT NOT NULL,
            pull_number INTEGER NOT NULL CHECK (pull_number > 0),
            model_tier TEXT NOT NULL CHECK (
                model_tier IN ('groq', 'gemini_flash', 'gemini_pro')
            ),
            latency_seconds REAL NOT NULL CHECK (latency_seconds >= 0),
            total_tokens INTEGER NOT NULL CHECK (total_tokens >= 0),
            estimated_cost_usd REAL NOT NULL CHECK (estimated_cost_usd >= 0),
            estimated_savings_usd REAL NOT NULL CHECK (estimated_savings_usd >= 0),
            created_at TEXT NOT NULL,
            status TEXT NOT NULL
        )
        """
    )
    return connection


def _parse_report_field(report: str, field: str) -> str:
    match = _REPORT_FIELDS[field].search(report)
    if match is None:
        raise ValueError(f"Review report is missing telemetry field: {field}")
    return match.group(1)


def record_completed_review(
    repository: str,
    pull_number: int,
    report: str,
    *,
    db_path: str | Path | None = None,
) -> None:
    record: ReviewRecord = {
        "repository": repository,
        "pull_number": pull_number,
        "model_tier": cast(
            ModelTier, _parse_report_field(report, "model_tier")
        ),
        "latency_seconds": float(_parse_report_field(report, "latency_seconds")),
        "total_tokens": int(_parse_report_field(report, "total_tokens")),
        "estimated_cost_usd": float(
            _parse_report_field(report, "estimated_cost_usd")
        ),
        "estimated_savings_usd": float(
            _parse_report_field(report, "estimated_savings_usd")
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "Completed",
    }
    with closing(_connect(db_path)) as connection, connection:
        connection.execute(
            """
            INSERT INTO reviews (
                repository, pull_number, model_tier, latency_seconds,
                total_tokens, estimated_cost_usd, estimated_savings_usd,
                created_at, status
            ) VALUES (
                :repository, :pull_number, :model_tier, :latency_seconds,
                :total_tokens, :estimated_cost_usd, :estimated_savings_usd,
                :created_at, :status
            )
            """,
            record,
        )


def get_metrics(*, db_path: str | Path | None = None) -> Metrics:
    with closing(_connect(db_path)) as connection:
        row = connection.execute(
            """
            SELECT
                COUNT(*) AS total_reviews,
                COALESCE(AVG(latency_seconds), 0) AS average_latency_seconds,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                COALESCE(SUM(estimated_savings_usd), 0) AS total_savings_usd
            FROM reviews
            """
        ).fetchone()
    return {
        "total_reviews": row["total_reviews"],
        "average_latency_seconds": row["average_latency_seconds"],
        "total_tokens": row["total_tokens"],
        "total_savings_usd": row["total_savings_usd"],
    }


def get_recent_reviews(
    *, limit: int = 50, db_path: str | Path | None = None
) -> list[ReviewRecord]:
    with closing(_connect(db_path)) as connection:
        rows = connection.execute(
            """
            SELECT
                repository, pull_number, model_tier, latency_seconds,
                total_tokens, estimated_cost_usd, estimated_savings_usd,
                created_at, status
            FROM reviews
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {
            "repository": row["repository"],
            "pull_number": row["pull_number"],
            "model_tier": row["model_tier"],
            "latency_seconds": row["latency_seconds"],
            "total_tokens": row["total_tokens"],
            "estimated_cost_usd": row["estimated_cost_usd"],
            "estimated_savings_usd": row["estimated_savings_usd"],
            "created_at": row["created_at"],
            "status": row["status"],
        }
        for row in rows
    ]
