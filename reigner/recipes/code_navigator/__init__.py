"""The ``code_navigator`` recipe — a multi-repo code exploration scaffold.

A recipe is *data, not code*: this package is a bundle of curated files
(``REIGNER.md``, ``reigner.yaml``, ``README.md``, ``.gitignore``) that
``reigner init --recipe code_navigator`` copies into a user's project. After
init the recipe is no longer referenced — the project runs through the ordinary
``Harness.from_config`` path over the copied files (SPEC section 9).

Unlike ``document_qa``, this recipe has no ingestion step: there is no
``schema.yaml``, no extractor, and no search index. It wires ``tools.fs`` in
multi-root mode instead, so one agent can converse across several repositories
at once (e.g. a backend and a frontend) without merging them into a monorepo.
The scaffolded project is a *sidecar*: it points at repos it never modifies.

There is deliberately no ``build()`` and no exported symbols: the recipe adds
no runtime surface.
"""
