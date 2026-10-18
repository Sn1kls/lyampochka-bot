from collections.abc import Iterator

import pytest

from poweron.adapters.telegram.handlers import router


@pytest.fixture(autouse=True)
def detached_router() -> Iterator[None]:
    """The module-level router can join one dispatcher only; free it after each test."""
    yield
    router._parent_router = None
