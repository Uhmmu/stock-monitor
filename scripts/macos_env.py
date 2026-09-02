#!/usr/bin/env python3
"""Load production-compatible .env plus safe native macOS overrides.

The launcher deliberately parses dotenv files instead of sourcing them in a
shell, so credentials containing shell metacharacters are never evaluated.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from dotenv import dotenv_values


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] == "--":
        args = args[1:]
    if not args:
        print("usage: macos_env.py -- command [args ...]", file=sys.stderr)
        return 2

    repo_root = Path(__file__).resolve().parents[1]
    local_env = Path(os.environ.get("STOCK_MONITOR_MACOS_ENV", repo_root / ".env.macos"))
    if not local_env.is_file():
        print(f"missing native environment file: {local_env}", file=sys.stderr)
        print("copy .env.macos.example to .env.macos first", file=sys.stderr)
        return 2

    environment = os.environ.copy()
    for env_file in (repo_root / ".env", local_env):
        if not env_file.is_file():
            continue
        for key, value in dotenv_values(env_file).items():
            if value is not None:
                environment[key] = value

    configured_data_root = environment.get("STOCK_MONITOR_LOCAL_DATA_DIR", ".local/data")
    data_root = Path(configured_data_root).expanduser()
    if not data_root.is_absolute():
        data_root = repo_root / data_root
    data_root = data_root.resolve()

    path_overrides = {
        "ARCHIVE_DIR": data_root / "archive",
        "EDGAR_LOCAL_DATA_DIR": data_root / "edgar",
        "FINNHUB_STORAGE_DIR": data_root / "finnhub",
        "TECHNICAL_CHART_DIR": data_root / "technical-charts",
    }
    for key, path in path_overrides.items():
        path.mkdir(parents=True, exist_ok=True)
        environment[key] = str(path)

    backend_path = str(repo_root / "backend")
    existing_pythonpath = environment.get("PYTHONPATH", "")
    environment["PYTHONPATH"] = (
        backend_path if not existing_pythonpath else f"{backend_path}{os.pathsep}{existing_pythonpath}"
    )
    environment["STOCK_MONITOR_REPO_ROOT"] = str(repo_root)

    os.execvpe(args[0], args, environment)
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
