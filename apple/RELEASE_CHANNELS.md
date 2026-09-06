# Release channels and rollback policy

## Local candidate

The ad-hoc signed DMG is for the owner's Mac only. It is labeled as a local build, carries a
SHA-256 checksum and must not be uploaded or described as a notarized release.

## Internal and beta

After Developer ID and notarization become available, promote the exact checksummed artifact first
to an internal channel and then to a small beta group. Each promotion records app/build version,
minimum server contract, checksum, notarization submission identifier and previous known-good
artifact. No database migration is performed by the Mac app.

## Production

Production promotion requires the completed release checklist, a clean-device Gatekeeper test and
a compatible deployed server. Rollback means republishing the previous notarized artifact while
keeping the server compatibility window open; the client never rewrites server-owned portfolio,
AI, IBKR, Crypto or PAPER state during install, upgrade or rollback.

Anonymous crash or performance evidence may contain app version, OS version, architecture and
technical counters only. It must not contain account identifiers, investment content, holdings,
transactions, conversations, tokens, IBKR identifiers, URLs or request/response payloads.
