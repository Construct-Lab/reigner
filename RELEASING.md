# Releasing

Reigner releases follow Conventional Commits → `git-cliff` (CHANGELOG) →
`uv version` (bump) → tag → push → GitHub Release → `uv publish` (PyPI).

The repo is currently **private**: tag internally to build CHANGELOG history,
but **do not run `uv publish`** until the public-flip day (~`v0.5.0`).

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/)
- [`git-cliff`](https://git-cliff.org/) — `brew install git-cliff`
- [`gh`](https://cli.github.com/), authenticated — `gh auth login`

All commits on `main` must follow [Conventional Commits](https://www.conventionalcommits.org/)
(`feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `perf:`, `style:`,
`ci:`, `revert:`). Both the changelog grouping and the bump choice depend on
the prefix.

## Cutting a release

```bash
# 0. main is clean and green
git checkout main && git pull
uv run pytest
uv run ruff check .

# 1. Bump + changelog + commit + tag (pick one)
./scripts/release.sh patch    # 0.2.0 → 0.2.1
./scripts/release.sh minor    # 0.2.0 → 0.3.0
./scripts/release.sh major    # 0.2.0 → 1.0.0

# 2. Push commit + tag
git push --follow-tags

# 3. Cut the GitHub Release with just this version's notes
gh release create v<version> --title "v<version>" \
  --notes-file <(git cliff --latest --strip all)

# 4. PyPI publish — DEFERRED until public-flip day (~v0.5.0).
# uv build && uv publish
```

Bump choice:

| Change                              | Bump    |
| ----------------------------------- | ------- |
| Bug fixes, docs, internal refactors | `patch` |
| New backward-compatible features    | `minor` |
| Breaking API changes                | `major` |

The script does **not** infer the bump — you pick based on what's in the
unreleased commit list.

## Notes

- `pyproject.toml` ships at `0.1.0` as the baseline for the bumper. It is
  never tagged. The first real tag is `v0.2.0`, cut via
  `./scripts/release.sh minor` after the release tooling lands.
- We stay on `0.x` through public launch; `v1.0.0` is reserved for
  post-API-stability.
- The GitHub Actions release workflow and PyPI Trusted Publishing are
  deferred — manual flow first.
