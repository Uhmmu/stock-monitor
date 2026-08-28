# Binance TEST execution runbook

Goal 6 is TEST-only. The backend owns policies, expiring leases and audit rows;
the standalone `execution-agent/` process owns the Binance Futures Demo HMAC
secret and local SQLite journal. There is no live origin, environment selector,
wallet, transfer or withdrawal method in this boundary.

## One-time setup

1. In **Crypto → 测试执行**, create a TEST account, approve a complete bounded
   policy, then register one local agent. Copy the one-time machine token to a
   local `0600` file; never paste it into chat or store it on the VPS.
2. Install locally with `python -m pip install -e ./execution-agent`, then run:

   ```sh
   execution-agent init \
     --control-url https://jialenb.com \
     --agent-id <agent-name> \
     --machine-token-file <local-0600-token-file>
   ```

3. Put the Binance Futures Demo API key and HMAC secret in the generated
   `credentials.json`. The directory must be `0700` and both JSON files `0600`.
4. Run `execution-agent check`. Start the example user systemd service only
   after the checks below pass.

## Mandatory preflight and canary

- The adapter must report the compiled origin `https://demo-fapi.binance.com`.
- Signed account configuration must allow trading, reject hedge mode and
  multi-assets mode, and report withdrawal disabled when the field is present.
- The TEST account must have no unexplained position or open order. Any local ↔
  exchange mismatch activates the persistent local kill switch.
- Start with BTCUSDT, one allowlisted deployment/instrument, leverage 1, and the
  smallest exchange-valid notional. Observe signal → lease → order → fill or
  cancel → reconciliation in both the admin page and local journal.
- Restart the agent and run once again. It must query any incomplete client order
  ID before doing anything else and must not create a second logical order.
- Test timeout-after-accept, duplicate event, partial/open order cancellation,
  local kill and server kill. Each case must converge or remain blocked.

`TEST_READY` requires an enabled control plane, active account/policy/agent,
fresh heartbeat, successful reconciliation, no unknown order and no active kill
switch. `LIVE_READY` is always false.

## Deployment status (2026-08-28)

The control-plane implementation is committed, but the earlier deployment was
mistakenly sent to the retired `203.0.113.20` host. Treat that host as invalid;
the current production host is `203.0.113.10` and remains at migration `0078`
until a deliberate Goal 6 deployment is performed. No TEST account or local
agent has been registered. Provision a fresh Binance Futures Demo HMAC key in
the local executor, then deploy and run the mandatory preflight/canary above;
never copy a secret to the VPS, repository, browser or chat.

## Recovery and rollback

Stop the local service first. Query/cancel incomplete TEST orders, reconcile,
then clear the local kill file only after the mismatch is explained. Server-side
kill and agent revoke remain available immediately. To roll back the release,
keep the local service stopped, disable `EXECUTION_CONTROL_ENABLED`, restore the
deployment backup/images, and downgrade `0079_execution_test` only if its audit
rows are no longer required.
