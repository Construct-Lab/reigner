# Handoff — docs site + lean README for OSS release

**Crux:** Scaffolded a public MkDocs Material docs site, rewrote README as a lean landing page, and scrubbed internal/planning content from SPEC/PRINCIPLES ahead of PyPI/OSS release. Slices 1–3 committed and pushed; Slice 4 (Pages deploy) is gated and NOT started.

## Update (2026-07-16) — finalized logo assets

Swapped the placeholder logos for the finalized brand set (crown mark + `reigner` lockup).

- **Canonical exports live in repo-root `assets/`:** `reigner-logo-{dark,light}.svg` (lockup), `reigner-icon-{dark,light}.svg` (crown only), `favicon.svg`. Pure vector, gold crown on the `-dark` variants / ink crown on `-light`, no external font dependency.
- **README** `<picture>` now points at repo-root `assets/reigner-logo-{dark,light}.svg` (width 360), matching the finalized snippet. (PyPI still needs the absolute-raw-URL swap at publish — see below.)
- **Docs site** needs its own copy under `docs_dir`, so the full set is duplicated into `docs/assets/`. Stale `docs/assets/logo-{dark,light}.svg` + `logo.svg` deleted. **Two-folder layout is intentional** (`assets/` = README/PyPI, `docs/assets/` = MkDocs) — MkDocs won't bundle files outside `docs_dir`. Do not delete `assets/`; it backs the README.
- **`mkdocs.yml`:** header `logo: assets/reigner-icon-dark.svg` (gold crown reads well on the teal primary bar); `favicon: assets/favicon.svg`.
- `uv run mkdocs build --strict` passes; all five SVGs render into `site/assets/`.
- **Known caveat:** favicon SVG is non-square (`viewBox 0 0 200 150`), so it letterboxes slightly in the browser tab. Left as the exported asset per user; square-crop later if desired.

- **Branch:** `ananthanandanan/docs-scaffold-mkdocs-material-site-github-pages` (pushed to origin)
- **Working dir:** `/Users/ananthan2k/orca/workspaces/reigner/docs-scaffold-mkdocs-material-site-github-pages`
- **Date:** 2026-07-15
- **Tracking issue:** #76 (docs scaffold)

## Agenda

Prep Reigner for open-source: (1) rewrite README to a professional PyPI landing page, (2) stand up a free hosted docs site (MkDocs Material → GitHub Pages), (3) clean internal artifacts (TASKS.md, internal "ApolloScope" name, LLM-slop tone, stale model ids) from docs that will be published. Deploy is deliberately last and gated.

## Files written / edited (committed)

| File | Change |
|---|---|
| `README.md` | Rewritten: tagline, badges, docs link, "one core, three surfaces" framing, features, 4-cmd quickstart, extras table. Observability tutorial removed (moved to site). |
| `mkdocs.yml` | New. Material theme, search, mkdocstrings, include-markdown, `exclude_docs` (`*.html`, `plan/`, `review/`, `teach/`), GitHub-compatible toc slugify (`pymdownx.slugs.slugify` via `!!python/object/apply`), nav. |
| `docs/index.md` | New. Overview: "one core, three surfaces"; MCP-planned note. |
| `docs/reference.md` | New. mkdocstrings API page (`::: reigner`, `.tools`, `.sessions`, `.plugins`, `.artifacts`). |
| `docs/guide/observability.md` | New. OTel walkthrough lifted from old README. |
| `docs/guide/usage.md` | Renamed from `docs/USAGE.md` (git rename). Rewrote meta-narration intro; `gpt-4o`→`gpt-5.5`; "see README" refs → `observability.md` links; AGPL note self-contained. |
| `docs/design/spec.md`, `docs/design/principles.md` | New. include-markdown stubs pulling root `SPEC.md`/`PRINCIPLES.md`. |
| `SPEC.md` | Scrubbed ApolloScope/NIRF; removed Appendix B; removed §22 open-questions; reframed §20 build-order (no weeks) and §21 → "What v0 delivers"; license Apache→MIT; added design-doc status note; `gpt-4o`→`gpt-5.5`. |
| `PRINCIPLES.md` | Reframed §2 "Build fresh, don't port" (dropped ApolloScope); softened §8 predecessor ref; `.md`-filename cross-refs → prose ("the spec"); "default ROLE" → "default `REIGNER.md`". |
| `CLAUDE.md` | Dropped TASKS.md pointer + `T-01`; corrected stale "not yet implemented" status. |
| `TASKS.md` | Deleted (work tracked in GitHub Issues). |
| `pyproject.toml` | Added `docs` dependency-group: mkdocs, mkdocs-material, mkdocstrings[python], mkdocs-include-markdown-plugin, mike. |
| `.gitignore` | Added `/site/`. |

**Uncommitted (intentionally):** `docs/plan/docs-site.html` (visualise-plan output — repo convention: never commit). Updated this session to reflect unversioned-deploy decision.

## Commits (pushed)

```
9585ad7 docs: rewrite README as a lean landing page
1069c1a docs: scaffold MkDocs Material documentation site (#76)
3d1962c docs: retire TASKS.md and scrub internal references   (HEAD; includes ROLE fix, amended)
```

## Skills used

- `/ank:visualise-plan` → `docs/plan/docs-site.html` (approved by user).
- `/ank:handoff` → this file.

## Links / references

- Issue #76 — docs scaffold (this work's tracking issue).
- Issue #126 — e2e testing of HTTP server (`serve --http`) + OTel observability. **Deploy gate.**
- PR #128 — this work (Slices 1–3). Open against `main`.
- Hosted URL (future): `https://construct-lab.github.io/reigner/`

## Key decisions

- **Publish SPEC/PRINCIPLES via include-markdown stubs**, keeping canonical files at repo root (contributors expect them there). Not symlinks (flaky across checkouts).
- **`docs/` gotcha (#76):** kept `docs_dir=docs`, used `exclude_docs` for generated HTML, moved only prose to `docs/guide/`.
- **Trim SPEC in place** (user chose over "keep internal + fresh architecture page").
- **`ROLE` left as-is elsewhere** — it's a live term of art (the *composed* prompt; real `reigner inspect role` command), distinct from `REIGNER.md`. Only the one clearly-stale "default ROLE" line was changed.
- **Model id = `gpt-5.5`** — mirrors `indialaw/reigner.yaml` (user's real project), not invented.
- **Deploy is unversioned first; `mike` deferred** until multiple releases exist. Slice 4 workflow will use `mkdocs gh-deploy --force`, and Pages Source = "Deploy from a branch" → `gh-pages`. (`mike` left in `docs` group for later.)
- **No `session diff` command exists** — verified `reigner/cli/session.py` registers only list/show/tree/fork/replay/export/import. Docs corrected to say "fork / replay" not "diff". (A diff command is v1-tagged and out of scope for this docs work.)

## Current state

- `uv run mkdocs build --strict` → **passes clean** (no warnings/errors) as of last run this session. 637 API objects render; SPEC/PRINCIPLES include correctly; generated HTML excluded.
- `uv run ruff check .` → 5 errors, **all in untracked `indialaw/`** (user's local project, unrelated to this work; not committed).
- Slices 1–3 committed + pushed. PR #128 open against `main`.
- Slice 4 (Pages deploy workflow `.github/workflows/docs.yml`) — **not created.**

## Open questions / not done

- User is doing a full docs read-through (`mkdocs serve`) — **gate 1** for deploy, in progress.
- Issue #126 must be DONE before deploy — **gate 2** — so its doc corrections land first.
- PR not opened yet.
- Terminal demo GIF for README quickstart — **deferred; plan below.**

### Deferred: demo GIF via VHS (plan, not started)

Tool: [charmbracelet/vhs](https://github.com/charmbracelet/vhs) (`brew install vhs`; pulls `ttyd` + `ffmpeg`; works on macOS/darwin). Records a `.tape` script driving a real terminal into a GIF.

Constraint: VHS runs commands for real, so the recording needs (1) an ingested project — `indialaw/` is a ready hero corpus (cited legal answer showcases "citation-faithful") — and (2) a live model + API key (spends tokens) + network. So it's a **manual local record, not CI** (secrets, cost, nondeterminism).

Plan when picked up:
1. Write `demo.tape` — prefer `reigner chat --print "<question>"` (one-shot) over interactive REPL for a deterministic take.
2. Run `vhs demo.tape` locally against `indialaw/` → `docs/assets/demo.gif` (optimize; keep well under ~1–2 MB).
3. Commit `demo.tape` (reproducible source) + the GIF; embed in README + `docs/index.md`.
- Repo owner must set **Settings → Pages → Source** (one-time UI step, only owner can do) before first deploy.
- **README logo uses relative paths** (`assets/reigner-logo-*.svg`) — fine on GitHub, but PyPI does not resolve relative image URLs. At PyPI-publish time, swap the README `<picture>` `src`/`srcset` to absolute `https://raw.githubusercontent.com/Construct-Lab/reigner/main/assets/reigner-logo-*.svg` URLs so the logo renders on the package page.

## Next steps (ordered)

1. Wait for user: finishing docs review + issue #126. Do NOT build Slice 4 (or merge PR #128) until both clear.
2. When user returns: confirm #126 is closed and its doc fixes are merged/pulled into this branch.
3. Build Slice 4: create `.github/workflows/docs.yml` running `uv sync --group docs` + `uv run mkdocs gh-deploy --force` on push to `main`, `permissions: contents: write`. See `docs/plan/docs-site.html` (Key code section) for the exact snippet.
4. Add README link/badge to the live `construct-lab.github.io/reigner` URL once Pages is confirmed serving.
5. Walk user through Settings → Pages → Source = "Deploy from a branch" → `gh-pages` (they must click; agent cannot).
