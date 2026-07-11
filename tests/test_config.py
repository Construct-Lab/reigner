"""Tests for reigner/config.py (T-17 / issue #17)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from reigner.config import (
    ReignerConfig,
    SettingsConfig,
)
from reigner.types import ConfigError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINIMAL_YAML = """\
name: demo
model:
  provider: openai
  name: gpt-4o
"""


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "reigner.yaml"
    p.write_text(body)
    return p


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_load_minimal(tmp_path: Path) -> None:
    cfg = ReignerConfig.load(_write(tmp_path, MINIMAL_YAML))
    assert cfg.name == "demo"
    assert cfg.model.provider == "openai"
    assert cfg.model.name == "gpt-4o"
    # Defaults filled in.
    assert cfg.settings.max_iterations == 25
    assert cfg.role.file == "REIGNER.md"
    assert cfg.oracle is None


def test_load_records_config_path(tmp_path: Path) -> None:
    p = _write(tmp_path, MINIMAL_YAML)
    cfg = ReignerConfig.load(p)
    assert cfg.config_path == p.resolve()


def test_resolve_relative_path(tmp_path: Path) -> None:
    p = _write(tmp_path, MINIMAL_YAML)
    cfg = ReignerConfig.load(p)
    resolved = cfg.resolve("library/raw")
    assert resolved == (tmp_path / "library" / "raw").resolve()


def test_resolve_absolute_path_passthrough(tmp_path: Path) -> None:
    cfg = ReignerConfig.load(_write(tmp_path, MINIMAL_YAML))
    abs_path = tmp_path / "absolute"
    assert cfg.resolve(abs_path) == abs_path


def test_resolve_expands_home_tilde(tmp_path: Path) -> None:
    cfg = ReignerConfig.load(_write(tmp_path, MINIMAL_YAML))
    resolved = cfg.resolve("~/repos/api")
    assert resolved == Path.home() / "repos" / "api"


# ---------------------------------------------------------------------------
# write_default round-trip
# ---------------------------------------------------------------------------


def test_write_default_round_trips(tmp_path: Path) -> None:
    out = tmp_path / "reigner.yaml"
    ReignerConfig.write_default(out, name="round_trip")
    cfg = ReignerConfig.load(out)
    assert cfg.name == "round_trip"
    assert cfg.model.provider == "openai"
    assert cfg.settings.max_iterations == 25
    assert cfg.role.file == "REIGNER.md"


# ---------------------------------------------------------------------------
# Validation: typos, unknown keys, role.cascade
# ---------------------------------------------------------------------------


def test_unknown_top_level_key_rejected(tmp_path: Path) -> None:
    body = MINIMAL_YAML + "unexpected_top: 1\n"
    with pytest.raises(ConfigError, match="unexpected_top"):
        ReignerConfig.load(_write(tmp_path, body))


def test_unknown_settings_key_rejected(tmp_path: Path) -> None:
    body = MINIMAL_YAML + "settings:\n  max_iterz: 9\n"
    with pytest.raises(ConfigError, match="max_iterz"):
        ReignerConfig.load(_write(tmp_path, body))


def test_role_cascade_rejected_with_message(tmp_path: Path) -> None:
    body = MINIMAL_YAML + "role:\n  cascade: [recipe, user]\n"
    with pytest.raises(ConfigError, match="cascade is not supported"):
        ReignerConfig.load(_write(tmp_path, body))


# ---------------------------------------------------------------------------
# Validation: SettingsConfig
# ---------------------------------------------------------------------------


def test_settings_non_monotonic_thresholds_rejected() -> None:
    with pytest.raises(ValidationError, match="increasing|monotonic|in \\(0, 1\\)"):
        SettingsConfig(compaction_thresholds=(0.9, 0.8, 0.95))


def test_settings_threshold_out_of_range_rejected() -> None:
    with pytest.raises(ValidationError, match="in \\(0, 1\\)"):
        SettingsConfig(compaction_thresholds=(0.1, 0.5, 1.5))


def test_settings_negative_iterations_rejected() -> None:
    with pytest.raises(ValidationError):
        SettingsConfig(max_iterations=0)


def test_settings_tool_result_char_limits_must_be_positive() -> None:
    with pytest.raises(ValidationError, match="must be > 0"):
        SettingsConfig(tool_result_char_limits={"read": -1})


# ---------------------------------------------------------------------------
# describe() helper
# ---------------------------------------------------------------------------


def test_settings_describe_marks_origin() -> None:
    s = SettingsConfig(max_iterations=10)
    rows = {row.name: row for row in s.describe()}
    assert rows["max_iterations"].from_file is True
    assert rows["max_iterations"].value == 10
    assert rows["nudge_interval"].from_file is False
    assert rows["nudge_interval"].value == 3


def test_settings_describe_covers_all_fields() -> None:
    rows = SettingsConfig().describe()
    assert {row.name for row in rows} == set(SettingsConfig.model_fields)


# ---------------------------------------------------------------------------
# Tools section
# ---------------------------------------------------------------------------


def test_tools_artifacts_parses(tmp_path: Path) -> None:
    body = (
        MINIMAL_YAML
        + "tools:\n  artifacts:\n    root: library/artifacts\n    schema: ./schema.yaml\n"
    )
    cfg = ReignerConfig.load(_write(tmp_path, body))
    assert cfg.tools.artifacts is not None
    assert cfg.tools.artifacts.root == "library/artifacts"
    assert cfg.tools.artifacts.schema_path == "./schema.yaml"


def test_tools_custom_passthrough(tmp_path: Path) -> None:
    body = MINIMAL_YAML + "tools:\n  custom:\n    - mypkg.tools:get_foo\n"
    cfg = ReignerConfig.load(_write(tmp_path, body))
    assert cfg.tools.custom == ["mypkg.tools:get_foo"]


def test_tools_fs_parses(tmp_path: Path) -> None:
    body = MINIMAL_YAML + "tools:\n  fs:\n    root: .\n    write_enabled: true\n"
    cfg = ReignerConfig.load(_write(tmp_path, body))
    assert cfg.tools.fs is not None
    assert cfg.tools.fs.root == "."
    assert cfg.tools.fs.write_enabled is True


def test_tools_fs_defaults_to_read_only(tmp_path: Path) -> None:
    body = MINIMAL_YAML + "tools:\n  fs:\n    root: ./sandbox\n"
    cfg = ReignerConfig.load(_write(tmp_path, body))
    assert cfg.tools.fs is not None
    assert cfg.tools.fs.write_enabled is False


def test_tools_fs_rejects_unknown_key(tmp_path: Path) -> None:
    body = MINIMAL_YAML + "tools:\n  fs:\n    root: .\n    bogus: 1\n"
    with pytest.raises(ConfigError, match="bogus"):
        ReignerConfig.load(_write(tmp_path, body))


def test_tools_fs_roots_parses(tmp_path: Path) -> None:
    body = (
        MINIMAL_YAML + "tools:\n  fs:\n    roots:\n      backend: ../api\n      frontend: ../web\n"
    )
    cfg = ReignerConfig.load(_write(tmp_path, body))
    assert cfg.tools.fs is not None
    assert cfg.tools.fs.root is None
    assert cfg.tools.fs.roots == {"backend": "../api", "frontend": "../web"}


def test_tools_fs_rejects_both_root_and_roots(tmp_path: Path) -> None:
    body = MINIMAL_YAML + "tools:\n  fs:\n    root: .\n    roots:\n      backend: ../api\n"
    with pytest.raises(ConfigError, match="exactly one of 'root' or 'roots'"):
        ReignerConfig.load(_write(tmp_path, body))


def test_tools_fs_rejects_neither_root_nor_roots(tmp_path: Path) -> None:
    body = MINIMAL_YAML + "tools:\n  fs:\n    write_enabled: true\n"
    with pytest.raises(ConfigError, match="exactly one of 'root' or 'roots'"):
        ReignerConfig.load(_write(tmp_path, body))


def test_tools_fs_rejects_empty_roots(tmp_path: Path) -> None:
    body = MINIMAL_YAML + "tools:\n  fs:\n    roots: {}\n"
    with pytest.raises(ConfigError, match="non-empty map"):
        ReignerConfig.load(_write(tmp_path, body))


def test_tools_fs_rejects_bad_root_name(tmp_path: Path) -> None:
    body = MINIMAL_YAML + "tools:\n  fs:\n    roots:\n      'back end': ../api\n"
    with pytest.raises(ConfigError, match="invalid root name"):
        ReignerConfig.load(_write(tmp_path, body))


# ---------------------------------------------------------------------------
# File errors
# ---------------------------------------------------------------------------


def test_missing_file_raises_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot read"):
        ReignerConfig.load(tmp_path / "nope.yaml")


def test_invalid_yaml_raises_config_error(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("name: demo\n  : :  malformed")
    with pytest.raises(ConfigError, match="parse YAML"):
        ReignerConfig.load(p)


def test_yaml_not_a_mapping(tmp_path: Path) -> None:
    p = tmp_path / "bad.yaml"
    p.write_text("- just\n- a\n- list\n")
    with pytest.raises(ConfigError, match="must be a mapping"):
        ReignerConfig.load(p)


# ---------------------------------------------------------------------------
# Error formatting surfaces the file path
# ---------------------------------------------------------------------------


def test_error_message_includes_file_path(tmp_path: Path) -> None:
    p = _write(tmp_path, "name: demo\nmodel: { provider: openai, name: '' }\n")
    with pytest.raises(ConfigError) as exc:
        ReignerConfig.load(p)
    assert str(p) in str(exc.value)
