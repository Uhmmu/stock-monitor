from __future__ import annotations

import json

import pytest

from execution_agent.config import AgentConfig, initialize_directory
from execution_agent.errors import ConfigurationError


def test_init_creates_restrictive_template(tmp_path) -> None:
    config = initialize_directory(tmp_path / "agent", control_url="https://control.example", agent_id="local-1")
    assert config.config_path.stat().st_mode & 0o777 == 0o600
    assert config.credentials_path.stat().st_mode & 0o777 == 0o600
    assert config.data_dir.stat().st_mode & 0o777 == 0o700
    payload = json.loads(config.credentials_path.read_text())
    assert payload["binance_api_secret"] == ""


def test_runtime_requires_credentials_and_high_entropy_token(tmp_path) -> None:
    initialize_directory(tmp_path / "agent", control_url="https://control.example", agent_id="local-1")
    with pytest.raises(ConfigurationError):
        AgentConfig.from_env(data_dir=tmp_path / "agent")
