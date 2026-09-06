# Implementation Order

The sequence below minimizes the chance of changing transport, query semantics, and API behavior simultaneously.

1. **Prove the Kismet deployment.** Identify supported OS, installation/version, process owner, effective configuration, capture interface, permissions, API availability, storage path/schema, rotation, retention, and client/sensor ownership.
2. **Run a real controlled capture.** Confirm Kismet remains running, receives wireless frames, writes records with correct timestamps/fields, and preserves historical data. Block the plan if this fails.
3. **Freeze the verified source contract.** Record whether the query component uses local SQLite, Kismet API history, or a combination; record how multiple files and rotation are handled.
4. **Freeze the application contract.** Capture current API/UI response fixtures, existing Kismet service tests, timestamp conventions, error behavior, and client identity/connection assumptions.
5. **Define protocol constants and schemas.** Add the command name, request/response field rules, stable error codes, result maximum, and request ID policy without changing dispatch yet.
6. **Extract or share query primitives.** Adapt the client data layer to the verified Kismet source. Keep `poll_new_observations()` behavior unchanged and add focused tests.
7. **Implement and test the historical query.** Validate ranges and limits, query only the verified source, return normalized bounded results, and test exact filtering and empty/error distinction.
8. **Add the client dispatcher branch.** Route `GET_KISMET_OBSERVATIONS`, echo request/client IDs, and test malformed requests, unavailable Kismet, and response serialization.
9. **Add the server transport wrapper.** Reuse the existing registry, send lock, sole reader, queue, timeout, disconnect sentinel, and correlation validation.
10. **Route the investigation service and API.** Resolve the target client, normalize the window once, dispatch remotely, validate the response, preserve UI behavior, and keep any local fallback explicit.
11. **Run end-to-end verification.** Use real capture evidence plus two-client tests, exact time-boundary tests, and forged identity responses.
12. **Run regression and rollout checks.** Execute application suites/builds, measure payloads/latency, monitor Kismet/source errors, and retire fallback only after remote ownership is proven.

No step includes modifying `server/scripts.sql` unless a later, separately approved storage decision is made.
