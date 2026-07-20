#!/usr/bin/env bash
# Release helper: bumps version, updates CHANGELOG, commits, and tags.
#
# Usage:
#   ./scripts/release.sh           # defaults to patch
#   ./scripts/release.sh patch
#   ./scripts/release.sh minor
#   ./scripts/release.sh major

set -euo pipefail

BUMP=${1:-patch}

if [[ ! "$BUMP" =~ ^(patch|minor|major)$ ]]; then
    echo "Error: bump type must be 'patch', 'minor', or 'major' (got '$BUMP')"
    exit 1
fi

# Ensure working tree is clean
if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "Error: working tree has uncommitted changes. Commit or stash first."
    exit 1
fi

# Ensure git-cliff is available
if ! command -v git-cliff &> /dev/null; then
    echo "Error: git-cliff not installed (brew install git-cliff)."
    exit 1
fi

uv version --bump "$BUMP"
VERSION=$(uv version --short)

# Prepend the new section. NOT `-o`, which rebuilds the whole file from
# commit subjects and silently drops any prose hand-added to past releases.
git cliff --tag "v$VERSION" --unreleased --prepend CHANGELOG.md

git add pyproject.toml uv.lock CHANGELOG.md
git commit -m "chore: release v$VERSION"
git tag -a "v$VERSION" -m "v$VERSION"

echo ""
echo "Version bumped to $VERSION and tagged v$VERSION."
echo ""
echo "Next steps:"
echo "  git push --follow-tags"
echo "  gh release create v$VERSION --title \"v$VERSION\" \\"
echo "    --notes-file <(git cliff --latest --strip all)"
echo "  uv build && uv publish"
