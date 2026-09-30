import pytest

from seguro.config import load_config


@pytest.fixture
def config():
    cfg = load_config(None)
    cfg["cache_path"] = None
    cfg["blacklist"]["enabled"] = False
    return cfg
