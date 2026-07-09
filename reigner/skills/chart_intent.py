"""``chart_intent`` — emit a chart_intent block before a final answer when useful."""

from __future__ import annotations

from reigner.skills.base import Skill


class ChartIntent(Skill):
    """Discipline: declare chartable data as structured intent, not prose."""

    name = "chart_intent"
    description = "Emit a <chart_intent> block before the final answer when data is chartable."

    instructions = """
    When the answer contains a series that a reader would benefit from seeing as
    a chart — a trend over time, a breakdown across categories, a comparison —
    emit a `<chart_intent>` block immediately before your final answer text.

    The block declares intent for a downstream renderer; you do not draw the
    chart. Include:

    - `type`: one of line, bar, area, or pie.
    - `title`: a short caption.
    - `series`: the labelled data points, each traceable to a value you already
      retrieved (and cited, if numeric).

    Only emit one when the data genuinely warrants it. A single number or two
    unrelated values is not a chart — answer those in prose.
    """
