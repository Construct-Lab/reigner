"""The ``document_qa`` recipe — the v0 hero scaffold.

A recipe is *data, not code*: this package is a bundle of curated files
(``REIGNER.md``, ``reigner.yaml``, ``schema.yaml``, ``extractor_stub.py``)
that ``reigner init --recipe document_qa`` copies into a user's project. After
init the recipe is no longer referenced — the project runs through the ordinary
``Harness.from_config`` path over the copied files (SPEC section 9).

There is deliberately no ``build()`` and no exported ``SCHEMA``: the recipe adds
no runtime surface. The bundled ``schema.yaml`` is authored to match
``ArtifactSchema.document_qa_default()`` and guarded by a test against drift.
"""
