"""Dotted-path resolution in the plugin registry (SPEC §12).

A class resolves to a zero-arg instance; an already-built instance is used
as-is; anything else is a ``ConfigError``. The yaml stays a flat list of paths.
"""

from __future__ import annotations

import sys
import types
from collections.abc import Iterator

import pytest

from reigner.plugins.base import Plugin
from reigner.plugins.registry import load_plugins
from reigner.types import ConfigError

MODULE_NAME = "fake_plugin_mod"


@pytest.fixture
def fake_module() -> Iterator[types.ModuleType]:
    """Register a throwaway module exposing plugin classes and instances."""
    mod = types.ModuleType(MODULE_NAME)

    class MyPlugin(Plugin):
        name = "mine"

    class NotAPlugin:
        pass

    mod.MyPlugin = MyPlugin  # type: ignore[attr-defined]
    mod.configured = MyPlugin()  # type: ignore[attr-defined]
    mod.NotAPlugin = NotAPlugin  # type: ignore[attr-defined]
    mod.bare_object = object()  # type: ignore[attr-defined]
    sys.modules[MODULE_NAME] = mod
    try:
        yield mod
    finally:
        del sys.modules[MODULE_NAME]


def test_class_path_is_instantiated(fake_module: types.ModuleType) -> None:
    (plugin,) = load_plugins([f"{MODULE_NAME}:MyPlugin"])
    assert isinstance(plugin, Plugin)
    assert plugin.name == "mine"


def test_instance_path_used_as_is(fake_module: types.ModuleType) -> None:
    (plugin,) = load_plugins([f"{MODULE_NAME}:configured"])
    assert plugin is fake_module.configured


def test_dotted_attr_form_also_resolves(fake_module: types.ModuleType) -> None:
    # The `pkg.mod.Attr` form (no colon) resolves the last segment.
    (plugin,) = load_plugins([f"{MODULE_NAME}.MyPlugin"])
    assert isinstance(plugin, Plugin)


def test_non_plugin_class_raises(fake_module: types.ModuleType) -> None:
    with pytest.raises(ConfigError, match="not a Plugin subclass"):
        load_plugins([f"{MODULE_NAME}:NotAPlugin"])


def test_non_plugin_object_raises(fake_module: types.ModuleType) -> None:
    with pytest.raises(ConfigError, match="expected a Plugin subclass or instance"):
        load_plugins([f"{MODULE_NAME}:bare_object"])


def test_order_is_preserved(fake_module: types.ModuleType) -> None:
    plugins = load_plugins([f"{MODULE_NAME}:configured", f"{MODULE_NAME}:MyPlugin"])
    assert plugins[0] is fake_module.configured
    assert isinstance(plugins[1], Plugin)
    assert plugins[1] is not fake_module.configured


def test_empty_list_returns_empty() -> None:
    assert load_plugins([]) == []


def test_unimportable_path_raises() -> None:
    with pytest.raises(ConfigError):
        load_plugins(["definitely.not.a.real.module:Thing"])
