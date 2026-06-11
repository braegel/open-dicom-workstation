"""Shared pytest fixtures for the Open DICOM Workstation test suite."""

import socket

import pytest
from pydicom.dataset import FileDataset
from tests.support.factory import make_ct_dataset, make_series


def free_port() -> int:
    """Return a currently-free TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture
def ct_dataset() -> FileDataset:
    return make_ct_dataset()


@pytest.fixture
def ct_series() -> list[FileDataset]:
    return make_series(3)
