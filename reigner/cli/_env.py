"""Seed ``os.environ`` from a project-local ``.env`` before any adapter is built.

The model SDKs read API keys straight from the environment, so a key that lives
only in a project ``.env`` is invisible unless something loads it first. This
module does exactly that — and nothing more.
"""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv


def load_project_env(config_path: Path | None = None) -> bool:
    """Load ``<root>/.env`` into ``os.environ``. Real OS env always wins.

    ``root`` is ``config_path.parent`` when a config path is given, else the
    current working directory. Returns ``True`` iff a ``.env`` file was found
    and applied. Silent either way — nothing is printed.

    No walk-up: we pass an explicit path, so parent directories are never
    searched. ``override=False`` means a value already in the real environment
    is never clobbered by the ``.env``.
    """
    root = (config_path.parent if config_path else Path.cwd()).resolve()
    return load_dotenv(root / ".env", override=False)
