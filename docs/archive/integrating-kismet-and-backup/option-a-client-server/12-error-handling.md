# Error Handling

| Condition                        | Layer that detects it               | Contract                                                 | UI meaning                                         |
| -------------------------------- | ----------------------------------- | -------------------------------------------------------- | -------------------------------------------------- |
| Client not connected             | server registry/helper              | `CLIENT_OFFLINE`, retryable                              | refresh failed                                     |
| Client disconnects while waiting | existing response queue sentinel    | transport error, retryable                               | refresh failed                                     |
| Timeout                          | `execute_client_command` wrapper    | `CLIENT_TIMEOUT`, retryable                              | refresh failed                                     |
| Kismet database absent           | client listener/query               | `KISMET_UNAVAILABLE`, retryable                          | refresh failed                                     |
| Database file disappears         | client SQLite/discovery             | `KISMET_UNAVAILABLE`, retryable                          | refresh failed                                     |
| SQLite query/open failure        | client query                        | `KISMET_QUERY_FAILED`, retryable depends on cause        | refresh failed                                     |
| Invalid MAC/time/limit           | server and client validation        | `INVALID_REQUEST` or `INVALID_TIME_RANGE`, not retryable | request error                                      |
| No matching rows                 | client query                        | `status: ok`, empty observations and zero summary        | no observations                                    |
| Oversized result                 | client/server limit validation      | `RESULT_TOO_LARGE` or bounded `truncated: true`          | refresh failed or partial result, per final policy |
| Malformed response               | server validator                    | `MALFORMED_RESPONSE`, non-retryable until client fixed   | refresh failed                                     |
| Client identity mismatch         | server socket association/validator | `IDENTITY_MISMATCH`, security event                      | refresh failed                                     |
| Unknown command/version          | client dispatcher                   | existing structured error                                | refresh failed                                     |

## Rules

- Never catch an exception and return an empty observation list.
- Never fall back to another connected client.
- Never use server-local files for a remote target unless explicit fallback is enabled and response metadata identifies it.
- Log request ID, canonical client ID, device MAC, normalized bounds, error code, and duration. Avoid logging full packet payloads.
- Close SQLite connections and release server/client locks in `finally` paths.
- Treat malformed or mismatched responses as protocol failures, not data.
- Preserve the original query window in error logs so boundary bugs can be diagnosed.

## Retry policy

The first implementation should not automatically retry a query because repeated SQLite requests can amplify load and may return a different `now` window for presets. The server may expose retryable metadata for the UI/manual retry. If automatic retry is later needed, reuse an existing bounded retry convention and reuse the same normalized start/end and request identity rules.

## Observability

Add structured logs around dispatch and completion:

```text
client_id, device_mac, request_id, start, end, limit, include_noise,
status, observation_count, truncated, elapsed_ms, error_code
```

Do not add a continuous event stream merely for logging. Existing server/client logs are sufficient for the first implementation.
