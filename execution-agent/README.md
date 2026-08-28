# Local TEST execution agent

This package is a deliberately narrow Binance USD-M Futures **TEST** executor. Its exchange origin is compiled as `https://demo-fapi.binance.com`; runtime configuration cannot select another origin or an environment. It has no wallet, transfer, withdrawal, batch-order, WebSocket, live, or browser order path.

The VPS control-plane wire contract is `execution-agent.v1`:

- `GET /api/execution-agent/v1/lease?wire_version=execution-agent.v1`
- `POST /api/execution-agent/v1/events`

Machine requests carry `X-Execution-Agent-Id`, the raw high-entropy `X-Execution-Agent-Token`, timestamp, nonce, and HMAC-SHA256 signature. The canonical signed text has six newline-separated fields: `METHOD`, path, normalized sorted query, SHA-256 body hash, timestamp (Unix seconds), and nonce. Tokens are sent only over HTTPS and are never logged.

The lease is assumed to contain `wire_version`, `lease_id`, `signal_id`, `account_id`, `environment: "test"`, `venue: "binance_usdm"`, `symbol`, `target_exposure`, `issued_at`, `expires_at`, `policy_hash`, and `policy`. Policy hashing is SHA-256 of canonical sorted JSON for the limits object (not its envelope). A policy must include capital allocation, allowlist, order/gross/net/leverage/loss/drawdown/open-order limits, cooldown, and stale-data limits; missing values fail closed.

## Local setup

```sh
cd execution-agent
python -m pip install -e '.[test]'
python -m execution_agent init --control-url https://your-control-host --agent-id local-test-1
```

Put the machine token and Binance TEST key/secret in the generated `credentials.json` (mode `0600`), or use the documented local environment names `EXECUTION_AGENT_TOKEN`, `BINANCE_TEST_API_KEY`, and `BINANCE_TEST_API_SECRET`. The parent directory must be mode `0700`; startup refuses weak permissions. `check` makes no network request. `run --once` performs one lease poll; `run` loops. A persistent `KILL_SWITCH` file stops new execution.

```sh
python -m execution_agent check
python -m execution_agent run --once
```

The adapter journals an order before submission. Timeout or ambiguous 503 becomes `UNKNOWN`, queries by client order ID, and never blind-resubmits. SQLite fills rebuild local positions; any unresolved order or reconciliation mismatch activates the kill switch.

Run tests without network access:

```sh
pytest
```
