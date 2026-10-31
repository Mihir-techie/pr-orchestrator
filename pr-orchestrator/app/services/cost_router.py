import ast
import re
from dataclasses import dataclass
from typing import Literal

from unidiff import PatchSet

from app.config import MAX_DIFF_CHARS, Settings

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
    sections: list[tuple[str, str, bool]] = []
    changed_files: list[str] = []
    changed_lines = 0
    ast_complexity = 0

    for file_patch in patch:
        path = file_patch.path or file_patch.source_file
        pruned: list[str] = []
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
        if pruned:
            sections.append((path or "", "\n".join(pruned), _is_sensitive_path(path or "")))

    sensitive = any(_is_sensitive_path(path) for path in changed_files)
    complexity_score = changed_lines + (ast_complexity // 2) + (len(changed_files) * 3)
    max_chars = min(settings.max_diff_chars, MAX_DIFF_CHARS)
    pruned_diff = "\n".join(section for _, section, _ in sections)
    truncated = len(pruned_diff) > max_chars
    if truncated:
        truncation_marker = "\n[diff truncated]"[:max_chars]
        content_budget = max(0, max_chars - len(truncation_marker))
        prioritized_sections = sorted(sections, key=lambda section: not section[2])
        selected: list[str] = []
        used_chars = 0
        for _, section, _ in prioritized_sections:
            separator = 1 if selected else 0
            available = content_budget - used_chars - separator
            if available <= 0:
                break
            if len(section) > available:
                partial = section[:available]
                last_newline = partial.rfind("\n")
                if last_newline > 0:
                    partial = partial[:last_newline]
                if partial:
                    selected.append(partial)
                break
            selected.append(section)
            used_chars += separator + len(section)
        pruned_diff = "\n".join(selected) + truncation_marker

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
