"""Define common test utilities."""

import os

import pytest
from aresponses import ResponsesMockServer  # type: ignore

TEST_EMAIL = "user@email.com"
TEST_PASSWORD = "password"


@pytest.fixture(autouse=True)
async def aresponses(loop):
    """replace aresponses"""
    async with ResponsesMockServer(loop=loop) as server:
        yield server


def load_fixture(filename):
    """Load a fixture."""
    path = os.path.join(os.path.dirname(__file__), "fixtures", filename)
    with open(path, encoding="utf-8") as fptr:
        return fptr.read()
