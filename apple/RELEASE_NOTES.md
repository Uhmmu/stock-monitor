# Stock Monitor for macOS 0.1.0

Status: local release candidate. Not yet signed with Developer ID or notarized.

## Highlights

- Native SwiftUI monitoring, research, AI, portfolio, IBKR, Crypto and internal PAPER workspaces.
- Server-authoritative REST and SSE data paths with Keychain-backed session restoration.
- Apple Silicon arm64-only build with App Sandbox, Hardened Runtime and HTTPS production policy.
- Compatibility handshake, role-gated administration and privacy-scoped support diagnostics.

## Compatibility

- Requires macOS 26.0 or later on Apple Silicon.
- Requires a Stock Monitor server exposing API contract version 1. Older servers remain available
  during the compatibility-endpoint rollout and are identified in the app as compatibility mode.
- IBKR connectivity and credentials remain entirely on the server and continue to require its
  fail-closed SOCKS5 proxy policy.

## Known release gate

Public distribution is pending Apple Developer Program membership, Developer ID signing,
notarization, stapling and clean-device Gatekeeper verification.
