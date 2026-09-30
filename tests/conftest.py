import os

import pytest

from seguro.config import load_config


@pytest.fixture(autouse=True)
def _no_api_keys(monkeypatch):
    """Етапи з `enabled: auto` не мають вмикатися від ключів з оточення розробника."""
    for key in list(os.environ):
        if key.startswith("SEGURO_"):
            monkeypatch.delenv(key)


@pytest.fixture
def config(tmp_path):
    cfg = load_config(None)
    cfg["cache_path"] = None
    cfg["blacklist"]["enabled"] = False
    cfg["toplists"]["enabled"] = False
    cfg["download_dir"] = str(tmp_path / "downloads")
    cfg["store"]["path"] = str(tmp_path / "seguro.sqlite")
    return cfg
