"""FsTools — root-bound sandbox handle for raw filesystem tools.

The store is the trust boundary: every path the agent supplies passes
through :meth:`FsTools.resolve`, which rejects absolute paths, ``..``
traversal, and symlinks that resolve outside its root. The same store
also owns the per-tool bounds, the ignore predicate, and the text-file
extension allowlist so each tool module stays small.

FsTools works in two modes:

- **Single-root** (``FsTools(root)``): the agent sees one directory. Paths
  are plain root-relative strings (``src/app.py``).
- **Multi-root** (``FsTools(roots={...})``): a name→directory map is exposed
  as one virtual tree. The first path segment selects the root
  (``backend/src/app.py``); everything after it is validated inside *that*
  root. This lets one agent converse across several repos at once without
  merging them into a monorepo.

Either way :meth:`resolve` returns ``(root_name, absolute_path)`` (the name is
``""`` in single-root mode), and :meth:`display` turns an absolute path back
into the string the agent should see — root-prefixed only when multi-root.

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

    Pass exactly one of ``root`` (single-root mode) or ``roots`` (multi-root
    mode). See the module docstring for how the two modes differ.

    Args:
        root: Single directory the agent is allowed to see. All tool paths are
            interpreted relative to this root and validated against it. Mutually
            exclusive with ``roots``.
        roots: Name→directory map exposed as one virtual tree. Each root name
            becomes a top-level directory; the first path segment selects the
            root. Mutually exclusive with ``root``.
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
        root: str | Path | None = None,
        *,
        roots: dict[str, str | Path] | None = None,
        write_enabled: bool = False,
        max_read_chars: int = 8000,
        max_grep_matches: int = 20,
        max_ls_entries: int = 200,
        max_glob_results: int = 200,
        text_extensions: frozenset[str] | set[str] | None = None,
        ignored_dirs: frozenset[str] | set[str] | None = None,
    ) -> None:
        if (root is None) == (roots is None):
            raise ValueError("FsTools requires exactly one of 'root' or 'roots'")
        if roots is not None:
            if not roots:
                raise ValueError("FsTools 'roots' must be a non-empty map")
            self.multi_root = True
            self.roots: dict[str, Path] = {name: Path(p).resolve() for name, p in roots.items()}
        else:
            assert root is not None
            self.multi_root = False
            self.roots = {"": Path(root).resolve()}
        self.write_enabled = write_enabled
        self.max_read_chars = max_read_chars
        self.max_grep_matches = max_grep_matches
        self.max_ls_entries = max_ls_entries
        self.max_glob_results = max_glob_results
        self.text_extensions = (
            frozenset(text_extensions) if text_extensions else DEFAULT_TEXT_EXTENSIONS
        )
        self.ignored_dirs = frozenset(ignored_dirs) if ignored_dirs else DEFAULT_IGNORED_DIRS

    @property
    def root(self) -> Path:
        """The sole root, in single-root mode. Raises in multi-root mode."""
        if self.multi_root:
            raise AttributeError("FsTools is in multi-root mode; use .roots / .iter_roots()")
        return self.roots[""]

    def iter_roots(self) -> list[tuple[str, Path]]:
        """(name, absolute-path) for every root, in configured order."""
        return list(self.roots.items())

    # ---- Trust boundary ----------------------------------------------------

    def resolve(self, rel: str) -> tuple[str, Path]:
        """Resolve a virtual-tree path, rejecting traversal escapes.

        ``rel`` must be a non-empty relative POSIX-style path. In single-root
        mode it is interpreted directly under the sole root. In multi-root mode
        the first segment names the root and the remainder is validated inside
        that root. Returns ``(root_name, absolute_path)`` — ``root_name`` is
        ``""`` in single-root mode.

        The resolved path is rejected if it doesn't stay under its selected
        root: this catches both ``..`` traversal and symlinks pointing outside
        the root (``Path.resolve()`` follows symlinks before the check).
        """
        if not isinstance(rel, str) or not rel:
            raise ValueError("path must be a non-empty string")
        if rel.startswith(("/", "\\")):
            raise ValueError(f"path must be relative, got {rel!r}")
        if not self.multi_root:
            return "", self._within("", rel)
        head, _, tail = rel.partition("/")
        if head not in self.roots:
            known = ", ".join(sorted(self.roots))
            raise ValueError(f"unknown root {head!r}; roots are: {known}")
        return head, self._within(head, tail or ".")

    def _within(self, root_name: str, rel: str) -> Path:
        """Resolve ``rel`` inside the named root, rejecting escapes."""
        base = self.roots[root_name]
        candidate = (base / rel).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            where = f"root {root_name!r}" if self.multi_root else "fs root"
            raise ValueError(f"path {rel!r} escapes {where}") from exc
        return candidate

    def display(self, root_name: str, path: Path) -> str:
        """Render an absolute ``path`` as the agent-facing virtual-tree string.

        Root-relative in single-root mode; root-prefixed (``name/rel``) in
        multi-root mode so cross-repo references stay unambiguous.
        """
        rel = path.relative_to(self.roots[root_name]).as_posix()
        if not self.multi_root:
            return rel
        return root_name if rel == "." else f"{root_name}/{rel}"

    # ---- Ignore predicate --------------------------------------------------

    def is_ignored(
        self, path: Path, base: Path | None = None, *, include_hidden: bool = False
    ) -> bool:
        """True if ``path`` should be skipped during walks.

        Skips any segment in :attr:`ignored_dirs`. When ``include_hidden``
        is False (the default), also skips any segment starting with ``.``
        except the ``.``/``..`` placeholders. Segments are measured relative
        to ``base`` — the owning root a caller already knows; when omitted it
        is inferred (a path outside every root is treated as ignored).
        """
        root_base = base if base is not None else self._owning_root(path)
        if root_base is None:
            return True
        try:
            rel_parts = path.relative_to(root_base).parts
        except ValueError:
            return True
        for part in rel_parts:
            if part in self.ignored_dirs:
                return True
            if not include_hidden and part.startswith(".") and part not in (".", ".."):
                return True
        return False

    def _owning_root(self, path: Path) -> Path | None:
        """Return the root directory containing ``path``, or None if outside all."""
        for base in self.roots.values():
            try:
                path.relative_to(base)
                return base
            except ValueError:
                continue
        return None

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
