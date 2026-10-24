import fnmatch
import re


def parse_codeowners(codeowners: str, changed_paths: list[str]) -> list[str]:
    matched: list[str] = []
    rules: list[tuple[str, list[str]]] = []
    for raw_line in codeowners.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        parts = line.split()
        if len(parts) < 2:
            continue
        rules.append(
            (
                parts[0].lstrip("/"),
                [
                    owner[1:]
                    for owner in parts[1:]
                    if re.fullmatch(r"@[A-Za-z0-9-]+(?:/[A-Za-z0-9_.-]+)?", owner)
                ],
            )
        )

    for path in changed_paths:
        candidate = path.lstrip("/")
        path_owners: list[str] = []
        for pattern, owners in rules:
            if fnmatch.fnmatchcase(candidate, pattern) or (
                pattern.endswith("/") and candidate.startswith(pattern)
            ):
                path_owners = owners
        matched.extend(path_owners)
    return list(dict.fromkeys(matched))
