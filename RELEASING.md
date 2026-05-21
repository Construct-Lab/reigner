# Releasing a New Version

This document describes the release process for maintainers.

Reigner releases follow Conventional Commits → `git-cliff` (CHANGELOG) →
`uv version` (bump) → tag → push → GitHub Release → `uv publish` (PyPI).

> The repo is currently **private**. Tag internally to build CHANGELOG
> history, but **do not run `uv publish`** until the public-flip day
> (~`v0.5.0`).

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) installed
- [`git-cliff`](https://git-cliff.org/) installed (`brew install git-cliff`)
- [`gh`](https://cli.github.com/) (GitHub CLI) installed and authenticated
  (`gh auth login`)
- PyPI credentials configured for `uv publish` (deferred — see step 5)

All commits on `main` must follow
[Conventional Commits](https://www.conventionalcommits.org/) (`feat:`,
`fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `perf:`, `style:`, `ci:`,
`revert:`). Both the changelog grouping and the bump choice depend on the
prefix.

## Steps

### 1. Ensure the main branch is clean and tests pass

```bash
git checkout main
git pull
uv run pytest
uv run ruff check .
```

### 2. Run the release script

A helper script at `scripts/release.sh` bumps the version, regenerates
`CHANGELOG.md` via `git-cliff`, commits, and tags — all in one step:

```bash
# Patch release: 0.2.0 → 0.2.1
./scripts/release.sh patch

# Minor release: 0.2.0 → 0.3.0
./scripts/release.sh minor

# Major release: 0.2.0 → 1.0.0
./scripts/release.sh major
```

The script will:

- Validate the bump type
- Check the working tree is clean
- Run `uv version --bump <type>`
- Regenerate `CHANGELOG.md` using `git-cliff`
- Commit `pyproject.toml`, `uv.lock`, and `CHANGELOG.md` together
- Create an annotated `v<version>` git tag

The script does **not** infer the bump — you pick based on what's in the
unreleased commit list. See [Version numbering](#version-numbering) below.

### 3. Push the commit and tag

```bash
git push --follow-tags
```

### 4. Create a GitHub Release

Use `git-cliff` to extract just the latest release notes for the GitHub
Release body:

```bash
gh release create v<version> --title "v<version>" \
  --notes-file <(git cliff --latest --strip all)
```

Or open the GitHub UI: **Releases → Draft a new release → pick the tag**.

### 5. Publish to PyPI

> **Deferred until public-flip day (~`v0.5.0`).** While the repo is
> private, skip this step — internal tags and GitHub Releases are enough.

```bash
uv build
uv publish
```

To publish to TestPyPI first (configured in `pyproject.toml`):

```bash
uv publish --index testpypi
```

## Version numbering

This project follows [Semantic Versioning](https://semver.org/):

| Change type                              | Bump    | Example         |
| ---------------------------------------- | ------- | --------------- |
| Bug fixes, docs, internal refactors      | `patch` | `0.2.0 → 0.2.1` |
| New features, backward-compatible        | `minor` | `0.2.0 → 0.3.0` |
| Breaking API changes                     | `major` | `0.2.0 → 1.0.0` |

## Notes

- We stay on `0.x` through public launch; `v1.0.0` is reserved for
  post-API-stability.
- The GitHub Actions release workflow and PyPI Trusted Publishing are
  deferred — manual flow first.
