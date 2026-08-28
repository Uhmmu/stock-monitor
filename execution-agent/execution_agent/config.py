from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from .constants import BINANCE_TEST_ORIGIN, CONTROL_PREFIX, ENVIRONMENT, VENUE, WIRE_VERSION
from .errors import ConfigurationError
from .security import ensure_secure_directory, ensure_secure_file, validate_control_url, validate_high_entropy_token


def default_directory() -> Path:
    return Path.home() / ".local" / "share" / "stock-monitor" / "execution-agent"


@dataclass(frozen=True)
class AgentConfig:
    """Local configuration; TEST is a compile-time invariant, not a selector."""

    data_dir: Path
    control_url: str
    agent_id: str
    agent_token: str = field(repr=False)
    binance_api_key: str = field(default="", repr=False)
    binance_api_secret: str = field(default="", repr=False)
    poll_interval_seconds: float = 30.0
    control_timeout_seconds: float = 10.0
    exchange_timeout_seconds: float = 10.0
    recv_window_ms: int = 5_000
    wire_version: str = WIRE_VERSION

    @property
    def environment(self) -> str:
        return ENVIRONMENT

    @property
    def venue(self) -> str:
        return VENUE

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.json"

    @property
    def credentials_path(self) -> Path:
        return self.data_dir / "credentials.json"

    @property
    def journal_path(self) -> Path:
        return self.data_dir / "journal.sqlite3"

    @property
    def lock_path(self) -> Path:
        return self.data_dir / "agent.lock"

    @property
    def kill_switch_path(self) -> Path:
        return self.data_dir / "KILL_SWITCH"

    def validate(self, *, require_credentials: bool = True, allow_test_control: bool = False) -> "AgentConfig":
        ensure_secure_directory(self.data_dir, create=False)
        try:
            validate_control_url(self.control_url, allow_test_server=allow_test_control)
        except Exception as exc:
            raise ConfigurationError(str(exc)) from exc
        if not self.agent_id or len(self.agent_id) > 128 or any(char.isspace() for char in self.agent_id):
            raise ConfigurationError("agent_id is missing or malformed")
        if self.wire_version != WIRE_VERSION:
            raise ConfigurationError("unsupported execution-agent wire version")
        if not 0 < self.recv_window_ms <= 5_000:
            raise ConfigurationError("recv_window_ms must be between 1 and 5000")
        if self.poll_interval_seconds <= 0 or self.control_timeout_seconds <= 0 or self.exchange_timeout_seconds <= 0:
            raise ConfigurationError("timeouts and poll interval must be positive")
        if require_credentials:
            try:
                validate_high_entropy_token(self.agent_token)
            except Exception as exc:
                raise ConfigurationError(str(exc)) from exc
            if not self.binance_api_key or not self.binance_api_secret:
                raise ConfigurationError("local Binance TEST credentials are required")
        return self

    def public_dict(self) -> dict[str, object]:
        return {
            "control_url": self.control_url,
            "agent_id": self.agent_id,
            "environment": ENVIRONMENT,
            "venue": VENUE,
            "wire_version": self.wire_version,
            "binance_origin": BINANCE_TEST_ORIGIN,
            "poll_interval_seconds": self.poll_interval_seconds,
        }

    @classmethod
    def from_env(
        cls,
        *,
        data_dir: Path | None = None,
        environ: Mapping[str, str] | None = None,
        require_credentials: bool = True,
        allow_test_control: bool = False,
    ) -> "AgentConfig":
        env = dict(os.environ if environ is None else environ)
        root = Path(data_dir or env.get("EXECUTION_AGENT_DIR") or default_directory()).expanduser()
        ensure_secure_directory(root, create=False)
        config_data = _read_json(root / "config.json") if (root / "config.json").exists() else {}
        credential_data = _read_json(root / "credentials.json") if (root / "credentials.json").exists() else {}
        def value(name: str, file_key: str, default: str = "") -> str:
            return str(env.get(name, config_data.get(file_key, credential_data.get(file_key, default))) or "")

        config = cls(
            data_dir=root,
            control_url=value("EXECUTION_AGENT_CONTROL_URL", "control_url"),
            agent_id=value("EXECUTION_AGENT_ID", "agent_id"),
            agent_token=value("EXECUTION_AGENT_TOKEN", "agent_token"),
            binance_api_key=value("BINANCE_TEST_API_KEY", "binance_api_key"),
            binance_api_secret=value("BINANCE_TEST_API_SECRET", "binance_api_secret"),
            poll_interval_seconds=float(value("EXECUTION_AGENT_POLL_SECONDS", "poll_interval_seconds", "30")),
            control_timeout_seconds=float(value("EXECUTION_AGENT_CONTROL_TIMEOUT", "control_timeout_seconds", "10")),
            exchange_timeout_seconds=float(value("EXECUTION_AGENT_EXCHANGE_TIMEOUT", "exchange_timeout_seconds", "10")),
            recv_window_ms=int(value("EXECUTION_AGENT_RECV_WINDOW_MS", "recv_window_ms", "5000")),
            wire_version=value("EXECUTION_AGENT_WIRE_VERSION", "wire_version", WIRE_VERSION),
        )
        if not config.control_url:
            raise ConfigurationError("EXECUTION_AGENT_CONTROL_URL is required")
        config.validate(require_credentials=require_credentials, allow_test_control=allow_test_control)
        return config


def _read_json(path: Path) -> dict[str, object]:
    ensure_secure_file(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ConfigurationError(f"invalid local config file: {path}") from exc
    if not isinstance(value, dict):
        raise ConfigurationError(f"local config file must contain an object: {path}")
    return value


def _write_json(path: Path, value: dict[str, object], *, force: bool = False) -> None:
    ensure_secure_directory(path.parent)
    if path.exists() and not force:
        raise ConfigurationError(f"refusing to overwrite existing file: {path}")
    if path.exists():
        ensure_secure_file(path)
        path.unlink()
    ensure_secure_file(
        path,
        create=True,
        content=(json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def initialize_directory(
    directory: Path,
    *,
    control_url: str,
    agent_id: str,
    agent_token: str = "",
    force: bool = False,
) -> AgentConfig:
    root = ensure_secure_directory(Path(directory).expanduser(), create=True)
    # Init permits a blank token/credential template; runtime validation does not.
    validate_control_url(control_url, allow_test_server=True)
    _write_json(
        root / "config.json",
        {
            "control_url": control_url,
            "agent_id": agent_id,
            "environment": ENVIRONMENT,
            "venue": VENUE,
            "wire_version": WIRE_VERSION,
            "poll_interval_seconds": 30,
            "control_timeout_seconds": 10,
            "exchange_timeout_seconds": 10,
            "recv_window_ms": 5000,
            "binance_origin": BINANCE_TEST_ORIGIN,
            "api_prefix": CONTROL_PREFIX,
        },
        force=force,
    )
    _write_json(
        root / "credentials.json",
        {
            "agent_token": agent_token,
            "binance_api_key": "",
            "binance_api_secret": "",
        },
        force=force,
    )
    return AgentConfig(
        data_dir=root,
        control_url=control_url,
        agent_id=agent_id,
        agent_token=agent_token,
        binance_api_key="",
        binance_api_secret="",
    )
