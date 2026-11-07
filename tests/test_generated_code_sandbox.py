"""Behavior tests for the public API of generated_code_sandbox."""

from __future__ import annotations

import pytest

import generated_code_sandbox


def test_normalize_trims_and_lowercases() -> None:
    assert generated_code_sandbox.normalize("  Hello World ") == "hello world"


@pytest.mark.parametrize("value", ["", "   ", "\t\n"])
def test_normalize_rejects_blank_input(value: str) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        generated_code_sandbox.normalize(value)


def test_version_is_semver() -> None:
    parts = generated_code_sandbox.__version__.split(".")
    assert len(parts) == 3
    assert all(part.isdigit() for part in parts)
