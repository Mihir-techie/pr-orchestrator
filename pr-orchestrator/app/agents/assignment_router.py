from app.agents.state import ReviewState
from app.services.assignment import parse_codeowners
from app.services.github_client import GitHubClient


async def assignment_router(state: ReviewState) -> dict[str, list[str]]:
    github = GitHubClient()
    try:
        codeowners = await github.get_codeowners(state["repository"], state["base_ref"])
        candidates = parse_codeowners(codeowners, state.get("changed_files", []))
        pull_author = state.get("pull_author", "").lower()
        candidates = [login for login in candidates if login.lower() != pull_author]
        if not candidates:
            candidates = await github.get_recent_file_authors(
                state["repository"],
                state.get("changed_files", []),
                state["base_ref"],
            )
        candidates = [
            login
            for login in candidates
            if login.lower() != pull_author
        ][:5]
        return {"reviewer_candidates": candidates}
    finally:
        await github.close()
