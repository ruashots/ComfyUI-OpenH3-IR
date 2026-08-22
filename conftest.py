"""Not a test fixture. The one sentence somebody gets when they run pytest the wrong way.

This file is loaded ONLY when pytest's rootdir is the repository root, which is the invocation that
cannot work: the root holds the pack's `__init__.py`, pytest imports it as a bare `__init__` with no
parent package because `ComfyUI-OpenH3-IR` is not a Python identifier, and its first relative import
raises. Every test in the suite then errors in setup with a traceback about the wrong file.

`tests/pytest.ini` makes `tests/` the rootdir for the correct invocation, and pytest stops looking
for conftest files above its rootdir -- so a correct run never loads this file at all.
"""
import pytest


def pytest_configure(config):
    raise pytest.UsageError(
        "run the suite as `pytest tests` from the repository root, or as `pytest` from inside the "
        "tests folder. This repository's root is the ComfyUI node pack itself, so it holds an "
        "__init__.py that pytest cannot import from here. tests/pytest.ini has the measurement.")
