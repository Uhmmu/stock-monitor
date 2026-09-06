# macOS release checklist

## Automated candidate gate

- Run `./scripts/verify-goal-m6.sh` on Apple Silicon with stable Xcode 26.6.
- Run `./scripts/build-release-candidate.sh` and retain its SHA-256 checksum.
- Run `./scripts/verify-app-security.sh` against the candidate and `./scripts/rehearse-local-rollback.sh`.
- Confirm the parity matrix has no unexplained route or state gaps.
- Confirm the compatibility endpoint and macOS contract tests pass together.

## Manual quality gate

- Verify light/dark appearance, VoiceOver, Full Keyboard Access, Increase Contrast, Reduce Motion,
  Reduce Transparency, display zoom and long Chinese/English content at minimum and maximum windows.
- Profile SwiftUI updates, animation hitches, memory, network, energy, hangs and leaks with Instruments.
- Soak test market SSE, long AI streams, sleep/wake, network changes, server restart and multiple windows.
- Verify login, logout, role changes, stale/offline states, destructive confirmations and private-state clearing.
- Run Web and Mac golden flows against the same non-production test account and attach results to the
  parity matrix evidence log.

## Distribution gate requiring paid membership

- Install a Developer ID Application certificate without exporting it into the repository.
- Store notarization credentials in a local Keychain profile and set only its profile name in the shell.
- Run `./scripts/notarize.sh`; verify codesign, notarization, stapling and Gatekeeper assessment.
- Install, first-login, upgrade and uninstall on a clean Apple Silicon Mac.
- Preserve the previous notarized artifact and rehearse rollback before staged rollout.

Channel rules and the data-safe rollback boundary are documented in `RELEASE_CHANNELS.md`.

Never check in a Team ID, certificate, notary credential, account identifier, token or secret.
