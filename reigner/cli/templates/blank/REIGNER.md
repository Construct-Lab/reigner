# REIGNER.md

> This file is the single runtime source of truth for your agent's behavior.
> It is loaded once at session start. Skills (see `reigner.yaml`) layer in
> on demand; nothing else does.

## Identity

<!--
Describe what your agent is, who it's for, and what it refuses to do.
Example: "You are a research assistant over the company's compiled
financial filings. You answer with citations or you say you don't know."
-->

## Retrieval grammar

<!--
Teach the model how to use your tools. With the default artifact toolbox
this usually looks like:

  1. get_json_field for structured metrics
  2. grep_artifact to locate sections
  3. read_artifact_file to read in bounded chunks

State it explicitly. Tool docstrings are not enough.
-->

## Citation rules

<!--
Spell out what counts as a citation and when the agent must refuse to answer.
Example: "Every numeric claim must be backed by an artifact path retrieved
this session. If you cannot retrieve it, say so."
-->

## Clarification policy

<!--
When should the agent stop and ask vs. proceed with a best guess?
-->
