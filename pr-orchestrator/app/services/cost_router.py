import ast
import re
from dataclasses import dataclass
from typing import Literal

from unidiff import PatchSet

from app.config import Settings

ModelTier = Literal["groq", "gemini_flash", "gemini_pro"]

_SECURITY_PATH_PARTS = {"auth", "authentication", "crypto", "cryptography", "payments"}
_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


@dataclass(frozen=True)
class DiffAnalysis:
    pruned_diff: str
    changed_files: tuple[str, ...]
    changed_lines: int
    complexity_score: int
    sensitive: bool
    truncated: bool


def _is_sensitive_path(path: str) -> bool:
    normalized = path.replace("\\", "/").lower()
    parts = normalized.split("/")
    stems = {part.rsplit(".", 1)[0] for part in parts}
    return bool((set(parts) | stems) & _SECURITY_PATH_PARTS) or any(
        parent == "db" and child == "migrations"
        for parent, child in zip(parts, parts[1:])
    )


def _is_comment(line: str, extension: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return True
    if extension in {".py", ".rb", ".sh", ".yaml", ".yml", ".toml"}:
        return stripped.startswith("#")
    if extension == ".sql":
        return stripped.startswith(("--", "/*"))
    if extension in {".html", ".xml"}:
        return stripped.startswith("<!--")
    return stripped.startswith(("//", "/*"))


def analyze_diff(diff: str, settings: Settings) -> DiffAnalysis:
    patch = PatchSet(diff.splitlines(keepends=True))
    pruned: list[str] = []
    changed_files: list[str] = []
    changed_lines = 0
    ast_complexity = 0

    for file_patch in patch:
        path = file_patch.path or file_patch.source_file
        if path:
            changed_files.append(path)
            pruned.append(f"File: {path}")
        extension = "." + path.rsplit(".", 1)[-1].lower() if path and "." in path else ""
        added_python: list[str] = []

        for hunk in file_patch:
            for line in hunk:
                if not (line.is_added or line.is_removed):
                    continue
                content = line.value.rstrip("\r\n")
                if _is_comment(content, extension):
                    continue
                changed_lines += 1
                pruned.append(("+" if line.is_added else "-") + content.strip())
                if line.is_added and extension == ".py":
                    added_python.append(content)

        if added_python:
            try:
                ast_complexity += sum(1 for _ in ast.walk(ast.parse("\n".join(added_python))))
            except SyntaxError:
                ast_complexity += len(added_python)

    sensitive = any(_is_sensitive_path(path) for path in changed_files)
    complexity_score = changed_lines + (ast_complexity // 2) + (len(changed_files) * 3)
    pruned_diff = "\n".join(pruned)
    truncated = len(pruned_diff) > settings.max_diff_chars
    if truncated:
        pruned_diff = pruned_diff[: settings.max_diff_chars] + "\n[diff truncated]"

    return DiffAnalysis(
        pruned_diff=pruned_diff,
        changed_files=tuple(changed_files),
        changed_lines=changed_lines,
        complexity_score=complexity_score,
        sensitive=sensitive,
        truncated=truncated,
    )


def select_model_tier(analysis: DiffAnalysis) -> ModelTier:
    if analysis.sensitive or analysis.complexity_score >= 150:
        return "gemini_pro"
    if analysis.complexity_score >= 40:
        return "gemini_flash"
    return "groq"


def estimate_tokens(text: str) -> int:
    return max(1, len(_TOKEN_PATTERN.findall(text)))
