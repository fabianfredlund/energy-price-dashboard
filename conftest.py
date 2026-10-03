import pytest


@pytest.fixture
def cache_root(tmp_path):
    return tmp_path
