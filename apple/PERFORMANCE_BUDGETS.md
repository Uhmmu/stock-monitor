# macOS performance and stability budgets

These budgets are release gates for Apple Silicon production candidates. A measured exception must
be documented with the affected workflow, device/OS, trace and explicit acceptance; absence of a
measurement is not a pass.

| Area | Budget |
|---|---|
| Cold launch to login/restored-shell visibility | 2 seconds at p95 |
| Main-thread hang | No event at or above 250 ms in a representative workflow |
| Animation hitch | No repeatable user-visible hitch; zero hitches in the release smoke trace |
| Idle login memory after stabilization | Below 150 MB resident |
| Long-session memory growth | Below 10% after a 60-minute representative loop |
| Resource parse work | Below 16 ms p95 for routine payloads; large chart transforms stay off MainActor |
| Background network | No unbounded retry or inactive-screen polling; terminal jobs stop polling |
| Energy | No sustained unexpected CPU wakeups while market and job streams are inactive |
| Crash/hang severity | Zero open P0/P1 defects at promotion |

The short local trace is a smoke check only. Final promotion still requires the golden-flow and
soak scenarios in `RELEASE_CHECKLIST.md`, including market-open streaming and long AI responses.
