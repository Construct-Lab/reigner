"""``faithfulness`` eval check — numeric claims must be cited (SPEC §15.1).

The trust property: every number the agent asserts in its final answer should
trace to a registered citation. This check extracts the numeric claims from the
answer text, extracts the numbers carried by the run's citations, and fails if
any answer number has no citation backing it. Acceptance: it flags every
hallucinated number (SPEC §22 Week-6 criterion 3).

Deterministic — no model call. Number extraction handles ``$``, ``%``, thousands
separators, and scale words (``billion`` / ``million`` / ``k`` / ``bn`` …), so
``"$67.0 billion"`` and a citation value of ``67000000000`` compare equal.
Matching is scale-tolerant in both directions (a citation that stores ``31.4``
billions matches an answer that says ``31.4 billion``) and uses a relative
epsilon for float comparison.

Two documented heuristics keep the check usable without an LLM judge:

- Extraction is token-based: only whole numeric tokens count, so digits fused
  into an identifier ("IR-E-U-0497") or word are never read as claims.
- Bare four-digit integers in 1900–2099 with no scale/decimal are treated as
  calendar **years**, not citable metrics, and skipped. Fiscal-/academic-year
  ranges ("2022-23", "2022/2023", "2022–23") are stripped first so the trailing
  token isn't read as a number.
- A number coincidentally equal to an unrelated citation value passes; this is
  numeric, not semantic, faithfulness. An LLM-judged variant can be added
  alongside via the same ``@check`` seam.

Verdicts:

- ``na``   — the answer contains no numeric claims (nothing to verify).
- ``pass`` — every numeric claim maps to a citation.
- ``fail`` — at least one number is uncited; the detail names the first one.
"""

from __future__ import annotations

import re

from reigner.eval.cases import EvalCase
from reigner.eval.checks import CaseRun, CheckResult, check

# A numeric *token*: optional currency, sign, thousands separators, decimal,
# optional scale word, optional percent. Matched against a whole whitespace-
# delimited token via fullmatch so a number fused into an identifier or word
# ("IR-E-U-0497", "Top10", "v2") is never mistaken for a claim — the recurring
# false-positive of a character-scanning regex.
_NUM_RE = re.compile(
    r"[$₹€£]?"
    r"(?P<num>-?\d{1,3}(?:,\d{3})+(?:\.\d+)?|-?\d+(?:\.\d+)?)"
    r"(?P<scale>trillion|billion|million|thousand|bn|mn|[kmbt])?"
    r"%?",
    re.IGNORECASE,
)

# Punctuation/markup that can wrap a number in prose ("(325)", "449,",
# "$31.4B.", "**449**", "`325`"). Stripped from token edges before matching;
# internal commas stay (thousands separators). Includes markdown emphasis/code
# since models routinely bold the figure they're asserting.
_EDGE_PUNCT = "()[]{}\"'.,;:!?–—-*_`#~"

_SCALE: dict[str, float] = {
    "": 1.0,
    "k": 1e3,
    "thousand": 1e3,
    "m": 1e6,
    "mn": 1e6,
    "million": 1e6,
    "b": 1e9,
    "bn": 1e9,
    "billion": 1e9,
    "t": 1e12,
    "trillion": 1e12,
}

# Scale factors tolerated when matching an answer number against a cited number,
# so "31.4 billion" in prose matches a citation that stores the value as 31.4.
_FACTORS = (1.0, 1e3, 1e6, 1e9, 1e12)

# Fiscal-/academic-year ranges ("2022-23", "2022/2023", "2022–23") are dates,
# not metrics. Stripped before extraction so the trailing token isn't read as a
# number. The separator class covers ASCII hyphen/slash plus the Unicode dashes
# (figure/en/em dash, horizontal bar) that prose models routinely emit.
_YEAR_RANGE_RE = re.compile(r"(?:19|20)\d{2}\s*[-/‒-―]\s*\d{2,4}")


def _numbers(text: str) -> list[float]:
    """Extract normalized numeric values from ``text`` (scale words applied).

    Token-based: each whitespace-delimited token is stripped of wrapping
    punctuation and accepted only if it is *entirely* numeric. This rejects
    numbers fused into identifiers or words while still reading "$31.4B",
    "12.5%", and "5,130".
    """
    text = _YEAR_RANGE_RE.sub(" ", text)
    out: list[float] = []
    for token in text.split():
        cleaned = token.strip(_EDGE_PUNCT)
        m = _NUM_RE.fullmatch(cleaned)
        if m is None:
            continue
        raw = m.group("num").replace(",", "")
        value = float(raw)
        scale = (m.group("scale") or "").lower()
        if not scale and "." not in raw and 1900 <= value <= 2099:
            continue  # calendar year, not a citable metric (documented heuristic)
        out.append(value * _SCALE.get(scale, 1.0))
    return out


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-6 * max(1.0, abs(a), abs(b))


def _is_cited(value: float, cited: list[float]) -> bool:
    """True if ``value`` matches a cited number under any tolerated scale factor."""
    return any(_close(value, c * f) or _close(value * f, c) for c in cited for f in _FACTORS)


@check("faithfulness")
def faithfulness(case: EvalCase, run: CaseRun) -> CheckResult:
    """Fail if any numeric claim in the answer is not backed by a citation."""
    claims = _numbers(run.answer_text)
    if not claims:
        return CheckResult("faithfulness", "na", "no numeric claims")

    cited = [n for citation in run.citations for n in _numbers(str(citation.value))]
    for claim in claims:
        if not _is_cited(claim, cited):
            shown = f"{claim:.0f}" if claim.is_integer() else f"{claim:g}"
            return CheckResult("faithfulness", "fail", f"claim {shown} not cited")
    return CheckResult("faithfulness", "pass")


__all__ = ["faithfulness"]
