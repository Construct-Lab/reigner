"""Domain-specific extractor stub.

Subclass `LLMExtractor` and fill in `PROMPT` + `extract()`. Reigner handles
adapters, retries, validation against your schema, and idempotency; the
prompt and any preprocessing are yours.

See SPEC.md §8.2 for the full contract.
"""

# from reigner.ingestion import LLMExtractor, ExtractionResult
#
#
# class MyExtractor(LLMExtractor):
#     # schema = ArtifactSchema.from_yaml("schema.yaml")
#     model = "openai:gpt-4o"
#     max_retries = 2
#
#     PROMPT = """
#     <your instructions to the model>
#     """
#
#     async def extract(self, raw: bytes, meta: dict) -> "ExtractionResult":
#         text = await self.preprocess_pdf(raw)
#         response = await self.call_model(
#             prompt=self.PROMPT.format(**meta),
#             input_text=text,
#             response_format="json",
#         )
#         return ExtractionResult(
#             sections={...},
#             json_artifacts={...},
#         )
