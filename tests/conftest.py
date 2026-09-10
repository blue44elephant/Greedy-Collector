"""pytest configuration for Greedy Collector tests."""

import pytest
import asyncio


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


def pytest_configure(config):
    """Configure pytest for async support."""
    # Allow asyncio mode to auto
    if not hasattr(config.option, 'asyncio_mode'):
        config.option.asyncio_mode = 'auto'
