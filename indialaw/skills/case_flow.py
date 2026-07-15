"""A deep procedural walkthrough, loaded only for case-flow questions.

This is the kind of guidance that does NOT belong in the always-on ROLE: it is
long, and it only applies to a subset of questions ("how does a case move
through the courts?"). Keeping it in a skill means the model pulls it into
context on demand, so every other question pays nothing for it.
"""

from __future__ import annotations

from reigner.skills import Skill


class CaseFlowWalkthrough(Skill):
    """On-demand procedure walkthrough for how a case moves through the courts."""

    name = "case_flow_walkthrough"
    description = "Deep step-by-step method for tracing how a case moves through Indian courts."

    instructions = """
    Use this method only when the user asks how a case proceeds through the
    Indian court system (civil or criminal), or how a matter reaches appeal.

    1. Establish the branch first. Confirm whether the question is civil,
       criminal, or constitutional. If the retrieved sources treat these
       differently, keep them separate — do not blend a civil suit's stages
       with a criminal trial's.

    2. Retrieve the structural passage and the procedural passage separately.
       Court hierarchy (which court, what jurisdiction) and case movement
       (filing -> trial -> judgment -> appeal) often live in different sections
       of the CGDA Handbook. Pull both before you synthesize.

    3. Present the flow as ordered stages, each grounded in a cited passage:
       - Where the matter is first filed and why (jurisdiction).
       - What happens at the trial court stage.
       - How and to which forum an appeal lies.
       - Any final/revisional stage the sources describe.

    4. Cite every stage inline. A stage without a citation is not established —
       omit it or say the sources do not cover it. Do not infer a stage from
       general knowledge to make the sequence look complete.

    5. Close by noting the limits of the retrieved sources: if they describe the
       civil path but not the criminal one (or vice versa), say so explicitly
       rather than generalizing.
    """
