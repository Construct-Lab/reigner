"""Tests for reigner/types.py (T-17 / issue #17)."""

from __future__ import annotations

import pytest

from reigner.types import ConfigError, Profile, ProviderName, import_dotted


def test_import_dotted_colon_form() -> None:
    obj = import_dotted("reigner.types:ConfigError")
    assert obj is ConfigError


def test_import_dotted_attribute_form() -> None:
    obj = import_dotted("reigner.types.ConfigError")
    assert obj is ConfigError


def test_import_dotted_function() -> None:
    obj = import_dotted("reigner.types:import_dotted")
    assert obj is import_dotted


def test_import_dotted_missing_module() -> None:
    with pytest.raises(ConfigError, match="cannot import module"):
        import_dotted("nonexistent_pkg.nope:obj")


def test_import_dotted_missing_attribute() -> None:
    with pytest.raises(ConfigError, match="no attribute"):
        import_dotted("reigner.types:NotARealName")


def test_import_dotted_empty_string() -> None:
    with pytest.raises(ConfigError, match="non-empty"):
        import_dotted("")


def test_import_dotted_no_separator() -> None:
    with pytest.raises(ConfigError, match="form"):
        import_dotted("justonename")


def test_import_dotted_preserves_cause() -> None:
    with pytest.raises(ConfigError) as exc_info:
        import_dotted("reigner.types:NotARealName")
    assert isinstance(exc_info.value.__cause__, AttributeError)


def test_provider_name_literal_values() -> None:
    # Literal types can't be inspected at runtime cheaply; this is a smoke
    # test that the alias is at least importable and string-valued.
    assert "openai" in ProviderName.__args__  # type: ignore[attr-defined]
    assert "anthropic" in ProviderName.__args__  # type: ignore[attr-defined]
    assert "gemini" in ProviderName.__args__  # type: ignore[attr-defined]


def test_profile_literal_values() -> None:
    assert set(Profile.__args__) == {"full", "read_only", "eval"}  # type: ignore[attr-defined]
