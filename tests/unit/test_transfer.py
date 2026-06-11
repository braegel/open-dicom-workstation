"""Tests for the transfer syntax catalog."""

from odw.core.transfer import DEFAULT_TRANSFER_SYNTAXES, TRANSFER_SYNTAXES


def test_catalog_is_non_empty_with_names() -> None:
    assert TRANSFER_SYNTAXES
    assert all(name for name in TRANSFER_SYNTAXES.values())


def test_defaults_are_subset_of_catalog() -> None:
    assert DEFAULT_TRANSFER_SYNTAXES
    assert set(DEFAULT_TRANSFER_SYNTAXES) <= set(TRANSFER_SYNTAXES)
