"""fs_write — whole-file overwrite/create under the FsTools sandbox.

Only emitted from :meth:`FsTools.tools` when ``write_enabled=True``.
There is no edit-style ``old_string``/``new_string`` mode in v0 — the
"raw filesystem" framing argues against it. Recipes that need partial
edits compose ``fs_read`` + ``fs_write``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from reigner.tools.base import tool

if TYPE_CHECKING:
    from reigner.tools.fs.store import FsTools


def build_fs_write(fs: FsTools) -> Callable[..., Awaitable[dict[str, Any]]]:
    """Build a @tool closure over ``fs``."""

    @tool(readonly=False)
    async def fs_write(path: str, content: str) -> dict[str, Any]:
        """Write ``content`` to ``path``, creating parent directories.

        Overwrites any existing file at ``path``. The suffix must be in
        ``fs.text_extensions`` — binary writes are not supported.

        Returns:
            ``{path, bytes_written, created}``. ``created`` is True when
            the file did not previously exist.
        """
        if not isinstance(content, str):
            raise TypeError(f"content must be a string, got {type(content).__name__}")
        root_name, target = fs.resolve(path)
        if not fs.is_text_extension(target):
            raise ValueError(
                f"{path!r} is not a writable text file "
                f"(suffix {target.suffix!r} not in fs.text_extensions)"
            )
        if target.exists() and not target.is_file():
            raise IsADirectoryError(f"{path!r} exists and is not a regular file")
        created = not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return {
            "path": fs.display(root_name, target),
            "bytes_written": len(content.encode("utf-8")),
            "created": created,
        }

    return fs_write


__all__ = ["build_fs_write"]
