# Goal M6 deployment evidence — 2026-09-08

## Production compatibility service

- Deployed the public `/api/client-capabilities` contract to `/opt/stock-monitor`.
- Rebuilt and replaced `api`, `worker`, `sec-worker` and `beat` from the shared backend context.
- The API reached Docker health `healthy`; all four services were running after replacement.
- The internal endpoint and `https://jialenb.com/api/client-capabilities` both returned contract
  version 1, minimum/recommended macOS client version 0.1.0 and the expected capability set.
- Recoverable production backup: `/opt/stock-monitor/backups/deployments/20260906-182911-goal-m6`.
  The backup includes the previous source files and rollback image tags for all four services.

## Installed macOS application

- Built the Xcode `Release` configuration for arm64 with ad-hoc signing and explicitly disabled
  Xcode's base debug-entitlement injection.
- Verified `StockMonitorAPIEnvironment=production` and
  `StockMonitorAPIBaseURL=https://jialenb.com` before installation.
- Replaced `/Applications/Stock Monitor.app` while it was not running, then verified its code
  signature, Hardened Runtime, sandbox/network-only entitlements and arm64 executable and launched
  it successfully.
- Installed executable SHA-256:
  `9ed867eefebb09d569092fcd1c85f22a654fbea1565216320a401802b6f247cf`.
- Recoverable previous app:
  `apple/DerivedData/install-backups/20260908-goal-m6/Stock Monitor.pre-goal-m6.app`.
- User data, Keychain state and server-owned investment data were not modified by replacement.

## Deferred living scope

Membership-dependent distribution and the remaining system/runtime validations are moved to
Extra Goal MX1. MX1 must be re-baselined when the user starts it; continued app work may change
its contents before then.
