"""GitReader deep module — all git subprocess calls isolated here."""

import subprocess
from pathlib import Path

from docspatch.errors import GitError
from docspatch.types.git import CommitInfo


class GitReader:
    """All git operations go through this class. No shell=True anywhere."""

    def __init__(self, cwd: Path | None = None) -> None:
        self._cwd = cwd or Path.cwd()

    def find_repo_root(self) -> Path:
        """Return the absolute path of the git repo root."""
        result = self._run(["git", "rev-parse", "--show-toplevel"])
        return Path(result.strip())

    def list_tracked_files(self, suffix: str = ".py") -> list[Path]:
        """Return tracked files with the given suffix relative to repo root."""
        try:
            root = self.find_repo_root()
        except GitError:
            return []
        result = self._run(["git", "-C", str(root), "ls-files"])
        paths = []
        for line in result.splitlines():
            p = root / line
            if p.suffix == suffix:
                paths.append(p)
        return paths

    def get_activity_signals(self, since_ref: str = "HEAD~1") -> list[CommitInfo]:
        """Return commits since since_ref. Raises GitError on bad ref."""
        root = self.find_repo_root()
        # Validate ref exists first
        self._run(["git", "-C", str(root), "rev-parse", "--verify", since_ref])
        result = self._run(
            [
                "git",
                "-C",
                str(root),
                "log",
                f"{since_ref}..HEAD",
                "--pretty=format:%H\t%s\t%an\t%aI",
                "--name-only",
            ]
        )
        return _parse_log(result)

    def get_remote_url(self) -> str | None:
        """Return the origin remote URL, or None if no remote configured."""
        root = self.find_repo_root()
        try:
            return self._run(["git", "-C", str(root), "remote", "get-url", "origin"]).strip()
        except GitError:
            return None

    def _run(self, cmd: list[str]) -> str:
        """Run a git command. Raises GitError on non-zero exit."""
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=self._cwd)
        if result.returncode != 0:
            raise GitError(
                f"git command failed: {' '.join(cmd)}",
                hint=result.stderr.strip(),
            )
        return result.stdout


def _parse_log(raw: str) -> list[CommitInfo]:
    if not raw.strip():
        return []
    commits = []
    current: dict = {}
    files: list[str] = []

    for line in raw.splitlines():
        if "\t" in line and not current:
            parts = line.split("\t", 3)
            current = {"sha": parts[0], "message": parts[1], "author": parts[2], "ts": parts[3]}
            files = []
        elif line.strip() and current:
            files.append(line.strip())
        elif not line.strip() and current:
            commits.append(
                CommitInfo(
                    sha=current["sha"],
                    message=current["message"],
                    author=current["author"],
                    timestamp=current["ts"],
                    files_changed=files,
                )
            )
            current = {}
            files = []

    if current:
        commits.append(
            CommitInfo(
                sha=current["sha"],
                message=current["message"],
                author=current["author"],
                timestamp=current["ts"],
                files_changed=files,
            )
        )
    return commits
