"""CLI tests for Tract -- tests all 5 commands via Click's CliRunner.

Each test uses runner.isolated_filesystem() with file-backed databases
since CLI opens its own connection (separate from SDK setup).
"""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from tract.cli import cli
from tract.models.content import InstructionContent, DialogueContent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def runner():
    """Create a Click test runner."""
    return CliRunner()


def _setup_tract(db_path: str, *, tract_id: str = "test-tract") -> None:
    """Create a tract with sample commits using the SDK, then close it.

    Creates 3 commits: system instruction, user message, assistant reply.
    """
    from tract.tract import Tract

    t = Tract.open(path=db_path, tract_id=tract_id)
    t.commit(
        InstructionContent(text="You are a helpful assistant."),
        message="system prompt",
    )
    t.commit(
        DialogueContent(role="user", text="Hello, how are you?"),
        message="user greeting",
    )
    t.commit(
        DialogueContent(role="assistant", text="I am doing well, thank you!"),
        message="assistant reply",
    )
    t.close()


def _setup_empty_tract(db_path: str, *, tract_id: str = "test-tract") -> None:
    """Create a tract with no commits."""
    from tract.tract import Tract

    t = Tract.open(path=db_path, tract_id=tract_id)
    t.close()



# ---------------------------------------------------------------------------
# Log command tests
# ---------------------------------------------------------------------------

class TestLogCommand:
    """Tests for tract log."""

    def test_log_shows_commits(self, runner: CliRunner):
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            result = runner.invoke(cli, ["--db", "test.db", "--tract-id", "test-tract", "log"])
            assert result.exit_code == 0
            assert "append" in result.output.lower()
            assert "system prompt" in result.output

    def test_log_limit(self, runner: CliRunner):
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            result = runner.invoke(cli, ["--db", "test.db", "--tract-id", "test-tract", "log", "-n", "1"])
            assert result.exit_code == 0
            # Should only show 1 commit (the most recent)
            assert "assistant reply" in result.output
            # Should NOT show the first commit
            assert "system prompt" not in result.output

    def test_log_verbose(self, runner: CliRunner):
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            result = runner.invoke(cli, ["--db", "test.db", "--tract-id", "test-tract", "log", "-v"])
            assert result.exit_code == 0
            # Verbose mode shows full hashes and types
            assert "Operation:" in result.output
            assert "append" in result.output.lower()



# ---------------------------------------------------------------------------
# Status command tests
# ---------------------------------------------------------------------------

class TestStatusCommand:
    """Tests for tract status."""

    def test_status_shows_head(self, runner: CliRunner):
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            result = runner.invoke(cli, ["--db", "test.db", "--tract-id", "test-tract", "status"])
            assert result.exit_code == 0
            assert "main" in result.output.lower()

    def test_status_no_commits(self, runner: CliRunner):
        with runner.isolated_filesystem():
            _setup_empty_tract("test.db")
            result = runner.invoke(cli, ["--db", "test.db", "--tract-id", "test-tract", "status"])
            assert result.exit_code == 0
            assert "no commits" in result.output.lower()



# ---------------------------------------------------------------------------
# Diff command tests
# ---------------------------------------------------------------------------

class TestDiffCommand:
    """Tests for tract diff."""

    def test_diff_default(self, runner: CliRunner):
        """Diff with no args diffs HEAD against parent."""
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            result = runner.invoke(cli, ["--db", "test.db", "--tract-id", "test-tract", "diff"])
            assert result.exit_code == 0
            assert "diff" in result.output.lower()
            assert "added" in result.output.lower()

    def test_diff_stat(self, runner: CliRunner):
        """Diff with --stat flag shows summary only."""
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            result = runner.invoke(cli, ["--db", "test.db", "--tract-id", "test-tract", "diff", "--stat"])
            assert result.exit_code == 0
            assert "added" in result.output.lower()



# ---------------------------------------------------------------------------
# Reset command tests
# ---------------------------------------------------------------------------

class TestResetCommand:
    """Tests for tract reset."""

    def test_reset_soft(self, runner: CliRunner):
        from tract.tract import Tract

        with runner.isolated_filesystem():
            _setup_tract("test.db")
            t = Tract.open(path="test.db", tract_id="test-tract")
            entries = t.log(limit=10)
            first_hash = entries[-1].commit_hash
            t.close()

            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "reset", "--soft", first_hash,
            ])
            assert result.exit_code == 0
            assert first_hash[:8] in result.output
            assert "soft" in result.output.lower()

    def test_reset_hard_needs_force(self, runner: CliRunner):
        """Hard reset without --force should fail."""
        from tract.tract import Tract

        with runner.isolated_filesystem():
            _setup_tract("test.db")
            t = Tract.open(path="test.db", tract_id="test-tract")
            entries = t.log(limit=10)
            first_hash = entries[-1].commit_hash
            t.close()

            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "reset", "--hard", first_hash,
            ])
            assert result.exit_code == 1
            assert "force" in result.output.lower()

    def test_reset_hard_with_force(self, runner: CliRunner):
        from tract.tract import Tract

        with runner.isolated_filesystem():
            _setup_tract("test.db")
            t = Tract.open(path="test.db", tract_id="test-tract")
            entries = t.log(limit=10)
            first_hash = entries[-1].commit_hash
            t.close()

            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "reset", "--hard", "--force", first_hash,
            ])
            assert result.exit_code == 0
            assert first_hash[:8] in result.output
            assert "hard" in result.output.lower()



# ---------------------------------------------------------------------------
# Checkout command tests
# ---------------------------------------------------------------------------

class TestCheckoutCommand:
    """Tests for tract checkout."""

    def test_checkout_commit_detaches(self, runner: CliRunner):
        from tract.tract import Tract

        with runner.isolated_filesystem():
            _setup_tract("test.db")
            t = Tract.open(path="test.db", tract_id="test-tract")
            entries = t.log(limit=10)
            first_hash = entries[-1].commit_hash
            t.close()

            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "checkout", first_hash,
            ])
            assert result.exit_code == 0
            assert "detached" in result.output.lower()

    def test_checkout_branch_attaches(self, runner: CliRunner):
        from tract.tract import Tract

        with runner.isolated_filesystem():
            _setup_tract("test.db")
            # First detach
            t = Tract.open(path="test.db", tract_id="test-tract")
            entries = t.log(limit=10)
            first_hash = entries[-1].commit_hash
            t.close()
            runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "checkout", first_hash,
            ])

            # Now checkout main branch
            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "checkout", "main",
            ])
            assert result.exit_code == 0
            assert "main" in result.output.lower()

    def test_checkout_dash(self, runner: CliRunner):
        """checkout '-' returns to previous position."""
        from tract.tract import Tract

        with runner.isolated_filesystem():
            _setup_tract("test.db")
            t = Tract.open(path="test.db", tract_id="test-tract")
            entries = t.log(limit=10)
            first_hash = entries[-1].commit_hash
            t.close()

            # Checkout commit to set PREV_HEAD
            runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "checkout", first_hash,
            ])
            # Go back
            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "checkout", "-",
            ])
            assert result.exit_code == 0



# ---------------------------------------------------------------------------
# Integration / help tests
# ---------------------------------------------------------------------------

class TestCLIIntegration:
    """General CLI integration tests."""

    def test_help(self, runner: CliRunner):
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "tract" in result.output.lower()
        assert "log" in result.output
        assert "status" in result.output
        assert "diff" in result.output
        assert "reset" in result.output
        assert "checkout" in result.output

    def test_subcommand_help(self, runner: CliRunner):
        for cmd in ["log", "status", "diff", "reset", "checkout"]:
            result = runner.invoke(cli, [cmd, "--help"])
            assert result.exit_code == 0, f"{cmd} --help failed"

    def test_no_cli_deps_for_import(self):
        """Importing tract (not tract.cli) should not require click/rich."""
        import subprocess
        import sys

        # Run in a subprocess to test import isolation
        result = subprocess.run(
            [sys.executable, "-c", "import tract; assert hasattr(tract, 'Tract')"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import failed: {result.stderr}"

    def test_auto_discover_tract(self, runner: CliRunner):
        """When --tract-id is omitted, auto-discover works for single tract."""
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            result = runner.invoke(cli, ["--db", "test.db", "log"])
            assert result.exit_code == 0
            assert "system prompt" in result.output

    def test_db_not_found(self, runner: CliRunner):
        """Graceful error when database doesn't exist."""
        with runner.isolated_filesystem():
            result = runner.invoke(cli, ["--db", "nonexistent.db", "log"])
            assert result.exit_code == 1

    def test_help_includes_new_commands(self, runner: CliRunner):
        """Help text includes branch, switch, merge commands."""
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "branch" in result.output
        assert "switch" in result.output
        assert "merge" in result.output

    def test_subcommand_help_new(self, runner: CliRunner):
        for cmd in ["branch", "switch", "merge"]:
            result = runner.invoke(cli, [cmd, "--help"])
            assert result.exit_code == 0, f"{cmd} --help failed"



# ---------------------------------------------------------------------------
# Branch command tests
# ---------------------------------------------------------------------------

class TestBranchCommand:
    """Tests for tract branch (list / create / delete)."""

    def test_branch_list(self, runner: CliRunner):
        """tract branch lists branches with * marker on current."""
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            # Create a second branch
            from tract.tract import Tract

            t = Tract.open(path="test.db", tract_id="test-tract")
            t.branch("feature", switch=False)
            t.close()

            result = runner.invoke(cli, ["--db", "test.db", "--tract-id", "test-tract", "branch"])
            assert result.exit_code == 0
            assert "main" in result.output
            assert "feature" in result.output
            assert "*" in result.output  # current branch marker

    def test_branch_create(self, runner: CliRunner):
        """tract branch create NAME creates and switches to branch."""
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "branch", "create", "feature",
            ])
            assert result.exit_code == 0
            assert "Created branch" in result.output
            assert "feature" in result.output
            assert "Switched to branch" in result.output

    def test_branch_create_no_switch(self, runner: CliRunner):
        """tract branch create --no-switch creates without switching."""
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "branch", "create", "feature", "--no-switch",
            ])
            assert result.exit_code == 0
            assert "Created branch" in result.output
            assert "Switched to branch" not in result.output

    def test_branch_delete(self, runner: CliRunner):
        """tract branch delete NAME removes branch."""
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            # Create a branch first (don't switch)
            from tract.tract import Tract

            t = Tract.open(path="test.db", tract_id="test-tract")
            t.branch("feature", switch=False)
            t.close()

            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "branch", "delete", "feature", "--force",
            ])
            assert result.exit_code == 0
            assert "Deleted branch" in result.output
            assert "feature" in result.output

    def test_branch_delete_current_errors(self, runner: CliRunner):
        """Deleting the current branch should error."""
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "branch", "delete", "main",
            ])
            assert result.exit_code == 1
            assert "error" in result.output.lower()



# ---------------------------------------------------------------------------
# Switch command tests
# ---------------------------------------------------------------------------

class TestSwitchCommand:
    """Tests for tract switch."""

    def test_switch_to_branch(self, runner: CliRunner):
        """tract switch NAME switches to existing branch."""
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            # Create a branch first
            from tract.tract import Tract

            t = Tract.open(path="test.db", tract_id="test-tract")
            t.branch("feature", switch=False)
            t.close()

            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "switch", "feature",
            ])
            assert result.exit_code == 0
            assert "Switched to branch" in result.output
            assert "feature" in result.output

    def test_switch_nonexistent(self, runner: CliRunner):
        """tract switch to nonexistent branch shows error with available branches."""
        with runner.isolated_filesystem():
            _setup_tract("test.db")
            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "switch", "nope",
            ])
            assert result.exit_code == 1
            assert "not found" in result.output.lower() or "error" in result.output.lower()



# ---------------------------------------------------------------------------
# Merge command tests
# ---------------------------------------------------------------------------

class TestMergeCommand:
    """Tests for tract merge."""

    def test_merge_fast_forward(self, runner: CliRunner):
        """Merging a branch with linear history produces fast-forward."""
        with runner.isolated_filesystem():
            from tract.tract import Tract

            # Setup: commit on main, create feature, commit on feature, switch back
            t = Tract.open(path="test.db", tract_id="test-tract")
            t.commit(
                InstructionContent(text="Base system prompt"),
                message="base",
            )
            t.branch("feature")
            t.commit(
                DialogueContent(role="user", text="Feature work"),
                message="feature commit",
            )
            t.switch("main")
            t.close()

            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "merge", "feature",
            ])
            assert result.exit_code == 0
            assert "Fast-forward" in result.output or "fast-forward" in result.output.lower()

    def test_merge_clean(self, runner: CliRunner):
        """Merging diverged branches with no conflicts produces a clean merge."""
        with runner.isolated_filesystem():
            from tract.tract import Tract

            # Setup: diverge branches
            t = Tract.open(path="test.db", tract_id="test-tract")
            t.commit(
                InstructionContent(text="Base system prompt"),
                message="base",
            )
            t.branch("feature")
            t.commit(
                DialogueContent(role="user", text="Feature work"),
                message="feature commit",
            )
            t.switch("main")
            t.commit(
                DialogueContent(role="assistant", text="Main work"),
                message="main commit",
            )
            t.close()

            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "merge", "feature",
            ])
            assert result.exit_code == 0
            assert "Merged" in result.output or "merged" in result.output.lower()

    def test_merge_already_up_to_date(self, runner: CliRunner):
        """Merging a branch that is already an ancestor shows 'up to date'."""
        with runner.isolated_filesystem():
            from tract.tract import Tract

            t = Tract.open(path="test.db", tract_id="test-tract")
            t.commit(
                InstructionContent(text="Base system prompt"),
                message="base",
            )
            # Create branch at same point, then add commit only on main
            t.branch("feature", switch=False)
            t.commit(
                DialogueContent(role="user", text="Extra main commit"),
                message="main extra",
            )
            t.close()

            result = runner.invoke(cli, [
                "--db", "test.db", "--tract-id", "test-tract",
                "merge", "feature",
            ])
            assert result.exit_code == 0
            assert "up to date" in result.output.lower()
