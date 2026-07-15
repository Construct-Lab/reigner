"""Deep analytical method for rule-of-law questions, loaded on demand.

Block 1 (IGNOU BLE-001) builds the rule of law on Dicey's three-element thesis,
then applies it to India and closes with concerns. That analytical scaffold is
long and only some questions need it — an "analyse" or "explain in depth" or
"compare the elements" question, not a plain "define the rule of law". So it
lives in a skill the model pulls in when the question calls for it, keeping
every simpler question cheap.
"""

from __future__ import annotations

from reigner.skills import Skill


class RuleOfLawAnalysis(Skill):
    """On-demand method for analysing rule-of-law questions via Dicey's thesis."""

    name = "rule_of_law_analysis"
    description = (
        "Structured method for analysing or comparing the elements of the rule of law "
        "(Dicey's thesis and its application in India)."
    )

    instructions = """
    Use this method when the question asks you to analyse, explain in depth, or
    compare aspects of the rule of law — not for a one-line definition, which
    you answer directly.

    1. Anchor on Dicey's three elements, and keep them distinct. Retrieve and
       treat each separately rather than blurring them:
       - Absence of arbitrary power (Section 1.3.1) — government action must
         pass the test of legality; no one is above the law.
       - Equality before the law (Section 1.3.2) — the same law applies to all,
         irrespective of status.
       - Supremacy of law (Section 1.3.3) — law, not the discretion of
         individuals, governs.
       Cite the specific sub-section for each element you rely on.

    2. Then move to the Indian application (Section 1.4). Distinguish two
       threads the block keeps separate:
       - Rule of law and the Constitution of India (1.4.1).
       - Rule of law and administrative law in India (1.4.2).
       Do not collapse the constitutional and administrative-law discussions
       into one; cite whichever the passage actually supports.

    3. If the question invites it, bring in the wider meaning (Section 1.5) and
       the concerns (Section 1.6) — where the block notes the limits of a purely
       formal rule of law. Flag these as the block's own critique, cited, not as
       your outside commentary.

    4. For a comparison question ("compare absence of arbitrary power with
       supremacy of law"), retrieve and cite both sides, then state the contrast
       in one sentence grounded in the cited passages.

    5. Close by naming what the source establishes and what it does not. If the
       block discusses an element in the abstract but not its Indian
       application, say so rather than inferring the gap.
    """
