# {project_name}

A multi-repo **code navigator**, scaffolded with
`reigner init --recipe code_navigator`.

This is a *sidecar* project: it lives in its own directory and points at one or
more repositories you want to explore. The agent reads across all of them in a
single conversation — so you can ask how a frontend call reaches its backend
route, or trace a shared name from where it's defined to where it's used,
without merging the repos into a monorepo. The target repos are never modified
(read-only by default).

## Layout

- `REIGNER.md` — instructions the agent reads at session start.
- `reigner.yaml` — model, settings, and the `tools.fs.roots` map.

## Setup

1. **Point the roots at your repos.** `reigner init` asks for these
   interactively and writes them into `reigner.yaml`; you can edit them there
   anytime. Each entry maps a *name* (arbitrary — it becomes the top-level
   directory the agent sees) to a repo path. Use any names, and add as many
   repos as you want to reason across:

   ```yaml
   tools:
     fs:
       roots:
         api: ../api
         web: ~/code/web
         shared: /abs/path/shared-lib
   ```

   A path can be relative (to this project), absolute, or start with `~/`. A
   root that doesn't resolve to a real directory fails loudly at startup.

2. **Add your API key.**

   ```bash
   cp .env.example .env   # then fill in your key
   ```

3. **Explore.**

   ```bash
   reigner chat
   ```

   Try: *"How does the web client call the login endpoint, and where is it
   handled in the api?"*

## Notes

- **Read-only by default.** To let the agent edit the target repos, set
  `write_enabled: true` in `reigner.yaml`.

See [Reigner SPEC](https://github.com/Construct-Lab/reigner) for the full contract.
