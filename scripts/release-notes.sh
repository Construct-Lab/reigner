#!/usr/bin/env bash
# Print the topmost release section of CHANGELOG.md, for use as the GitHub
# Release body.
#
#   gh release create v0.10.0 --title "v0.10.0" \
#     --notes-file <(./scripts/release-notes.sh)
#
# Reads the committed CHANGELOG rather than regenerating from commits with
# `git cliff --latest`. The two are not equivalent: the changelog is written
# before the release commit exists and may carry edits made while reviewing
# it, so a regeneration can silently disagree with the file that shipped.

set -euo pipefail

CHANGELOG=${1:-CHANGELOG.md}

if [[ ! -f "$CHANGELOG" ]]; then
    echo "Error: $CHANGELOG not found (run from the repo root)." >&2
    exit 1
fi

# Everything between the first "## [" heading and the next one, heading
# excluded — the GitHub Release already shows the version as its title.
notes=$(awk '/^## \[/{ if (n++) exit; next } n' "$CHANGELOG")

if [[ -z "${notes//[[:space:]]/}" ]]; then
    echo "Error: no release section found at the top of $CHANGELOG." >&2
    exit 1
fi

printf '%s\n' "$notes"
