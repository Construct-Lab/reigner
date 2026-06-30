"""FsTools — root-bound sandbox handle for raw filesystem tools.

The store is the trust boundary: every path the agent supplies passes
through :meth:`FsTools.resolve`, which rejects absolute paths, ``..``
traversal, and symlinks that resolve outside the root. The same store
also owns the per-tool bounds, the ignore predicate, and the text-file
extension allowlist so each tool module stays small.

``fs_write`` is the only mutating tool. It is **only emitted** from
:meth:`FsTools.tools` when ``write_enabled=True`` — there is no runtime
"permission denied" branch. Omission, not refusal, is the gate.
"""

from __future__ import annotations

from pathlib import Path

from reigner.tools.base import RunnableToolAdapter, to_runnable

DEFAULT_TEXT_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".c",
        ".cfg",
        ".cpp",
        ".css",
        ".csv",
        ".env",
        ".go",
        ".h",
        ".hpp",
        ".html",
        ".ini",
        ".java",
        ".js",
        ".json",
        ".jsonl",
        ".jsx",
        ".kt",
        ".lua",
        ".md",
        ".php",
        ".pl",
        ".py",
        ".rb",
        ".rs",
        ".scss",
        ".sh",
        ".sql",
        ".svelte",
        ".swift",
        ".toml",
        ".ts",
        ".tsv",
        ".tsx",
        ".txt",
        ".vue",
        ".xml",
        ".yaml",
        ".yml",
        ".zsh",
    }
)

DEFAULT_IGNORED_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)


class FsTools:
    """Root-bound sandbox for raw filesystem tools.

    Args:
        root: Directory the agent is allowed to see. All tool paths are
            interpreted relative to this root and validated against it.
        write_enabled: When True, ``tools()`` also emits ``fs_write``.
            Defaults to False so the read-only case is the obvious default.
        max_read_chars: Per-call character cap for ``fs_read``.
        max_grep_matches: Total match cap for ``fs_grep``.
        max_ls_entries: Entry cap for ``fs_ls``.
        max_glob_results: Result cap for ``fs_glob``.
        text_extensions: Suffix allowlist (lowercase, with leading dot)
            for ``fs_read`` and the default ``fs_grep`` filter.
        ignored_dirs: Directory basenames skipped during recursive walks.
    """

    def __init__(
        self,
        root: str | Path,
        *,
        write_enabled: bool = False,
        max_read_chars: int = 8000,
        max_grep_matches: int = 20,
        max_ls_entries: int = 200,
        max_glob_results: int = 200,
        text_extensions: frozenset[str] | set[str] | None = None,
        ignored_dirs: frozenset[str] | set[str] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.write_enabled = write_enabled
        self.max_read_chars = max_read_chars
        self.max_grep_matches = max_grep_matches
        self.max_ls_entries = max_ls_entries
        self.max_glob_results = max_glob_results
        self.text_extensions = (
            frozenset(text_extensions) if text_extensions else DEFAULT_TEXT_EXTENSIONS
        )
        self.ignored_dirs = frozenset(ignored_dirs) if ignored_dirs else DEFAULT_IGNORED_DIRS

    # ---- Trust boundary ----------------------------------------------------

    def resolve(self, rel: str) -> Path:
        """Resolve a root-relative path, rejecting traversal escapes.

        ``rel`` must be a non-empty relative POSIX-style path. The resolved
        path is rejected if it doesn't stay under ``self.root`` — this
        catches both ``..`` traversal and symlinks pointing outside the
        root (``Path.resolve()`` follows symlinks before the check).
        """
        if not isinstance(rel, str) or not rel:
            raise ValueError("path must be a non-empty string")
        if rel.startswith(("/", "\\")):
            raise ValueError(f"path must be relative, got {rel!r}")
        candidate = (self.root / rel).resolve()
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise ValueError(f"path {rel!r} escapes fs root") from exc
        return candidate

    # ---- Ignore predicate --------------------------------------------------

    def is_ignored(self, path: Path, *, include_hidden: bool = False) -> bool:
        """True if ``path`` (under root) should be skipped during walks.

        Skips any segment in :attr:`ignored_dirs`. When ``include_hidden``
        is False (the default), also skips any segment starting with ``.``
        except the literal current-directory ``.`` placeholder that can
        appear when the path equals root.
        """
        try:
            rel_parts = path.relative_to(self.root).parts
        except ValueError:
            return True
        for part in rel_parts:
            if part in self.ignored_dirs:
                return True
            if not include_hidden and part.startswith(".") and part not in (".", ".."):
                return True
        return False

    def is_text_extension(self, path: Path) -> bool:
        """True if ``path``'s suffix is in :attr:`text_extensions`."""
        return path.suffix.lower() in self.text_extensions

    # ---- Tool assembly -----------------------------------------------------

    def tools(self) -> list[RunnableToolAdapter]:
        """Build the FS tools as RunnableTool wrappers.

        Returns four tools by default (``fs_read``, ``fs_grep``,
        ``fs_glob``, ``fs_ls``); ``fs_write`` is appended only when
        :attr:`write_enabled` is True.
        """
        from reigner.tools.fs.glob import build_fs_glob
        from reigner.tools.fs.grep import build_fs_grep
        from reigner.tools.fs.ls import build_fs_ls
        from reigner.tools.fs.read import build_fs_read

        funcs = [
            build_fs_read(self),
            build_fs_grep(self),
            build_fs_glob(self),
            build_fs_ls(self),
        ]
        if self.write_enabled:
            from reigner.tools.fs.write import build_fs_write

            funcs.append(build_fs_write(self))
        return [to_runnable(f) for f in funcs]


__all__ = ["DEFAULT_IGNORED_DIRS", "DEFAULT_TEXT_EXTENSIONS", "FsTools"]
