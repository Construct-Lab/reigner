import reigner


def test_version() -> None:
    assert isinstance(reigner.__version__, str)
    assert reigner.__version__ != ""


def test_cli_importable() -> None:
    from reigner.cli.__main__ import main

    assert callable(main)
