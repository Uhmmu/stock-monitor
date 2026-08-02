from __future__ import annotations

import argparse
import json

from app.database import SessionLocal
from .repository import import_existing_report
from .reconciliation import reconcile_positions


def main() -> None:
    parser = argparse.ArgumentParser(description="Import an already-downloaded IBKR Flex XML report")
    parser.add_argument("--source", required=True)
    parser.add_argument("--user-id", required=True, type=int)
    parser.add_argument("--apply", action="store_true", help="Commit the import; default is dry-run")
    parser.add_argument("--reconcile", action="store_true", help="Reconcile the default portfolio after import")
    args = parser.parse_args()
    with SessionLocal() as db:
        result = import_existing_report(db, user_id=args.user_id, path=args.source, dry_run=not args.apply)
        if args.reconcile and result.get("sync_run_id"):
            result["reconciliation"] = reconcile_positions(
                db, user_id=args.user_id, sync_run_id=result["sync_run_id"], dry_run=not args.apply,
            )
    # Account identifiers are masked by the repository and raw records are never printed.
    print(json.dumps(result, ensure_ascii=False, default=str, indent=2))


if __name__ == "__main__":
    main()
