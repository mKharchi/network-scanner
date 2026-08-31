Milestone D — Implementation & Verification Report: Bulk / Multi-Client Targeting

Status: Completed and Verified.
Goal: Extend the proven single-client `DEPLOY_PACKAGE` flow to multiple clients at once with throttled concurrency, independent per-target tracking, and aggregate progress surfacing.
──────

## 1. Summary of Changes & File Citations

### D.1 — Concurrent Fan-Out with Throttle Cap

• Multi-target dispatch finding (Milestone A): `execute_action()` looped targets sequentially. For `DEPLOY_PACKAGE` only, this is replaced with a `ThreadPoolExecutor` capped at `DEPLOY_PACKAGE_MAX_CONCURRENT = 5` (`action_service.py:17-20`, `action_service.py:302-339`).
• All other action types (`GET_PROCESSES`, `SHUTDOWN`, `PING`, etc.) retain the original sequential dispatch loop unchanged (`action_service.py:341-399`).
• Final action status rolls up per-target results: all succeed → `SUCCESS`; all fail → `FAILED`; mixed → `PARTIAL_SUCCESS` (`action_service.py:401-406`).

### D.2 — Per-Target Independent Tracking

• `create_action()` already accepts a list of `client_id` strings and inserts one `action_targets` row per target (`action_service.py:107-114`).
• Each concurrent `deploy_package_to_client()` call marks its target `RUNNING` independently (`action_service.py:207-225`) and `handle_package_result()` persists per-client `SUCCESS`/`FAILED` to `action_targets` (`server_lib.py:836-851`).
• `PACKAGE_RESULT` waiters are keyed by `(action_id, mac)` so concurrent transfers for the same action do not steal each other's result notifications (`server_lib.py:800-815`, `action_service.py:228-277`).

### D.3 — Aggregate Progress Surfacing

• Added `summarize_action_progress()` and `summarize_action_progress_from_statuses()` in `action_framework.py:59-81`. Returns `{total, completed, succeeded, failed, in_progress, pending}`.
• `get_action()` now includes a `progress` field derived from per-target statuses (`action_service.py:446-447`).
• Each `PACKAGE_RESULT` SSE `action_update` broadcast includes a live `progress` rollup queried from `action_targets` (`server_lib.py:861-900`).

### D.4 — Bug Fixes Required for Multi-Client Correctness

• **Server waiter collision:** `_PACKAGE_RESULT_NOTIFIERS` previously keyed only by `action_id`, causing concurrent multi-client deploys to overwrite each other's wait queues. Fixed by keying on `(action_id, mac)`.
• **Client session collision in tests:** `ACTIVE_PACKAGE_SESSIONS` and package directory globals were process-wide, breaking e2e tests that simulate multiple clients in one process. Fixed with thread-local package state (`client_lib.py:1038-1125`) and `configure_package_paths()` / `reset_all_package_states()` test helpers.

──────

## 2. Parameter Specifications

| Parameter | Value | Details |
|-----------|-------|---------|
| Max concurrent transfers | 5 | `DEPLOY_PACKAGE_MAX_CONCURRENT` — prevents saturating TCP server threads |
| Target list | `client_id[]` | Group/zone resolution remains aspirational (per Milestone A) |
| Progress rollup | `get_action().progress` | Also pushed via SSE `action_update` on each `PACKAGE_RESULT` |
| Waiter key | `(action_id, mac)` | One in-memory queue per action/client-connection pair |

──────

## 3. Verification Results

| Test Scenario | Location | Result |
|---------------|----------|--------|
| Concurrent fan-out (5 targets) | `test_package_deployment.py:173-206` | Passed: wall-clock time confirms parallel execution, not sequential |
| One client fails, others succeed | `test_package_deployment.py:210-234` | Passed: `PARTIAL_SUCCESS`; per-target statuses independent |
| Throttle cap (10 targets, max 5 concurrent) | `test_package_deployment.py:238-273` | Passed: high-water mark ≤ 5 |
| Same-action waiter isolation | `test_package_deployment.py:318-404` | Passed: two concurrent deploys with shared `action_id` route results correctly |
| Progress rollup helper | `test_package_deployment.py:306-316` | Passed: counts match expected breakdown |
| Non-deploy actions unchanged | `test_package_deployment.py:275-299` | Passed: `GET_PROCESSES` still sequential |
| E2E: 3 clients independent tracking | `test_package_deployment_e2e.py:368-503` | Passed: all 3 extract to their own `updates/current/` |
| E2E: 1 client drops, others succeed | `test_package_deployment_e2e.py:517-546` | Passed: `PARTIAL_SUCCESS` |
| E2E: unrelated client responsive during bulk deploy | `test_package_deployment_e2e.py:632-689` | Passed: `PING` on control client returns in < 1.5s while 3-client deploy runs |
| Client unit tests (extraction safety) | `client/tests/test_package_deployment.py` | Passed: 6/6 |

──────

Stop Condition Met: In accordance with `docs/package-send/plan.md`, Milestone D results are verified. **Feature Phase 1 (package transfer + safe extraction + multi-client fan-out) is complete** and ready for real-world testing before Feature Phase 2 (client self-update) is scoped.
