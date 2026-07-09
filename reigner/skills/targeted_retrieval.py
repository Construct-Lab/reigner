"""``targeted_retrieval`` — the get_json_field -> grep -> read retrieval grammar."""

from __future__ import annotations

from reigner.skills.base import Skill


class TargetedRetrieval(Skill):
    """Discipline: narrow before you read. Cheap locate, then precise fetch."""

    name = "targeted_retrieval"
    description = "Use the get_json_field then grep then read grammar to locate facts cheaply."

    instructions = """
    Retrieve in three narrowing steps rather than reading whole documents:

    1. `get_json_field` — when you know the exact field you want, pull it
       directly. This is the cheapest and most precise path; prefer it.
    2. `grep` — when you know a term but not where it lives, grep for it to get
       the handful of locations worth opening.
    3. `read` — only after 1 or 2 have pointed you at a specific place, read
       that slice to confirm and quote it.

    Do not read broadly and skim. Each read spends context budget you will want
    later. If a step returns `has_more` or `truncated`, refine the query before
    reaching for a wider read.
    """
