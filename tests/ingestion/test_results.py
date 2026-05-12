from __future__ import annotations

from reigner.ingestion import (
    ExtractionError,
    ExtractionResult,
    TransientError,
    ValidationError,
)


def test_extraction_result_defaults_empty() -> None:
    result = ExtractionResult()
    assert result.sections == {}
    assert result.json_artifacts == {}
    assert result.meta == {}


def test_transient_is_extraction_error_subclass() -> None:
    assert issubclass(TransientError, ExtractionError)


def test_validation_is_extraction_error_subclass() -> None:
    assert issubclass(ValidationError, ExtractionError)


def test_validation_error_carries_payload() -> None:
    payload = {"sections": {"a": "x"}, "json_artifacts": {}}
    err = ValidationError("missing field foo", payload=payload)
    assert err.payload == payload
    assert "missing field foo" in str(err)


def test_validation_error_payload_optional() -> None:
    err = ValidationError("bad")
    assert err.payload is None
