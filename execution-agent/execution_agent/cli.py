from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import ExecutionAgent
from .binance import BinanceClient
from .config import AgentConfig, initialize_directory
from .control import ControlPlaneClient
from .errors import ExecutionAgentError
from .journal import Journal
from .security import KillSwitch


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="execution-agent", description="Binance Futures Demo local TEST executor")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="create a restrictive local config template")
    init.add_argument("--directory", type=Path, default=None)
    init.add_argument("--control-url", required=True)
    init.add_argument("--agent-id", required=True)
    init.add_argument("--machine-token-file", type=Path, default=None, help="read a token from this local file and store it 0600")
    init.add_argument("--force", action="store_true")
    check = sub.add_parser("check", help="validate local config and permissions without network calls")
    check.add_argument("--directory", type=Path, default=None)
    check.add_argument("--allow-test-control", action="store_true", help=argparse.SUPPRESS)
    run = sub.add_parser("run", help="poll TEST leases and execute through Binance Futures Demo")
    run.add_argument("--directory", type=Path, default=None)
    run.add_argument("--once", action="store_true", help="poll one lease then exit")
    return parser


def _directory(value: Path | None) -> Path | None:
    return value.expanduser() if value is not None else None


def _read_machine_token(path: Path | None) -> str:
    if path is None:
        return ""
    # The source file itself is intentionally not chmodded or printed; callers
    # should provide a local 0600 secret file and remove it after init.
    return path.read_text(encoding="utf-8").strip()


def _load_runtime(directory: Path | None) -> AgentConfig:
    return AgentConfig.from_env(data_dir=_directory(directory), require_credentials=True)


def _run(args: argparse.Namespace) -> int:
    config = _load_runtime(args.directory)
    control = ControlPlaneClient(config.control_url, config.agent_id, config.agent_token, timeout=config.control_timeout_seconds)
    exchange = BinanceClient(config.binance_api_key, config.binance_api_secret, timeout=config.exchange_timeout_seconds)
    with Journal(config.journal_path) as journal:
        agent = ExecutionAgent(config, control, exchange, journal, kill_switch=KillSwitch(config.kill_switch_path))
        try:
            with agent.instance_lock():
                if args.once:
                    result = agent.run_once()
                    print(result["status"])
                else:
                    agent.run_loop()
        finally:
            exchange.close()
            control.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "init":
            token = _read_machine_token(args.machine_token_file)
            directory = args.directory or Path.home() / ".local" / "share" / "stock-monitor" / "execution-agent"
            initialize_directory(directory, control_url=args.control_url, agent_id=args.agent_id, agent_token=token, force=args.force)
            print(f"initialized {Path(directory).expanduser()}")
            return 0
        if args.command == "check":
            config = AgentConfig.from_env(data_dir=_directory(args.directory), require_credentials=True, allow_test_control=args.allow_test_control)
            print(f"ok: {config.public_dict()}")
            return 0
        return _run(args)
    except (ExecutionAgentError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
