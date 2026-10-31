import unittest

from app.config import Settings
from app.services.assignment import parse_codeowners
from app.services.cost_router import analyze_diff, select_model_tier


class CostRouterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = Settings(
            _env_file=None,
            redis_url="redis://localhost:6379/0",
        )

    def test_sensitive_paths_route_to_flagship(self) -> None:
        diff = (
            "diff --git a/src/payments/refund.py b/src/payments/refund.py\n"
            "--- a/src/payments/refund.py\n"
            "+++ b/src/payments/refund.py\n"
            "@@ -1 +1 @@\n"
            "-return False\n"
            "+return True\n"
        )
        analysis = analyze_diff(diff, self.settings)
        self.assertTrue(analysis.sensitive)
        self.assertEqual(select_model_tier(analysis), "gemini_pro")
        self.assertEqual(self.settings.gemini_pro_model, "gemini-3.8-flash")
        self.assertEqual(self.settings.gemini_flash_model, "gemini-1.5-flash")

    def test_pruning_removes_blank_and_comment_changes(self) -> None:
        diff = (
            "diff --git a/src/example.py b/src/example.py\n"
            "--- a/src/example.py\n"
            "+++ b/src/example.py\n"
            "@@ -1 +1,3 @@\n"
            "-# old comment\n"
            "+# updated comment\n"
            "+\n"
            "+return value\n"
        )
        analysis = analyze_diff(diff, self.settings)
        self.assertEqual(analysis.changed_lines, 1)
        self.assertEqual(analysis.pruned_diff, "File: src/example.py\n+return value")

    def test_truncation_prioritizes_sensitive_files_within_hard_limit(self) -> None:
        settings = self.settings.model_copy(update={"max_diff_chars": 100})
        diff = (
            "diff --git a/docs/large.txt b/docs/large.txt\n"
            "--- a/docs/large.txt\n"
            "+++ b/docs/large.txt\n"
            "@@ -0,0 +1 @@\n"
            f"+{'x' * 300}\n"
            "diff --git a/src/auth.py b/src/auth.py\n"
            "--- a/src/auth.py\n"
            "+++ b/src/auth.py\n"
            "@@ -0,0 +1 @@\n"
            "+validate_credentials()\n"
        )

        analysis = analyze_diff(diff, settings)

        self.assertTrue(analysis.truncated)
        self.assertLessEqual(len(analysis.pruned_diff), 100)
        self.assertIn("File: src/auth.py", analysis.pruned_diff)
        self.assertIn("[diff truncated]", analysis.pruned_diff)

    def test_codeowners_supports_users_and_teams(self) -> None:
        owners = parse_codeowners(
            "*.py @alice @platform/reviewers\n",
            ["src/service.py"],
        )
        self.assertEqual(owners, ["alice", "platform/reviewers"])

    def test_last_matching_codeowners_rule_wins(self) -> None:
        owners = parse_codeowners(
            "src/ @team-a\nsrc/private/ @team-b\n",
            ["src/private/credentials.py"],
        )
        self.assertEqual(owners, ["team-b"])


if __name__ == "__main__":
    unittest.main()
