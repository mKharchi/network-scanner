# Existing TCP Request and Response Flow

## Reusable pattern

The closest existing pattern is `GET_TELEMETRY_FLOWS`.

1. A server service identifies a canonical client ID.
2. `server_lib.execute_client_command(client_id, command, args, timeout)` obtains that client's live registry entry.
3. It builds `{ "type": "COMMAND", "command": ..., "args": ... }`.
4. It serializes the frame through `send_message()` under the connection `send_lock`.
5. The client connection loop receives the frame through `receive_message()`.
6. `client/app/client.py` normalizes the command name and dispatches the operation.
7. The client reads local data and returns `{ "type": "RESPONSE", "command": ..., "data": ... }` on the same socket.
8. The server's single reader places the response into the client's queue.
9. `execute_client_command()` consumes queue entries until the command matches, or returns timeout/disconnect error.
10. A higher-level helper validates the result and returns it to its service.

The flow path uses `client/app/flow_query.py` through `get_requested_flows(message)` and the server helper `request_client_telemetry_flows()` as the behavioral template. Exact helper names and validation should be confirmed during implementation because this plan intentionally does not change code.

## Correlation limitation

Ordinary response matching currently uses only the command name. That is sufficient for one sequential command but is weak for concurrent requests with the same command. Kismet requests must carry a unique `request_id` in `args` and echo it in response data. The server helper must accept only the response whose command and request ID match.

A response for another request must remain queued or be routed by the existing queue policy; the implementation must not silently return it as the current query. If the current queue cannot safely retain unmatched same-command responses, add the smallest per-client correlation dispatcher needed around the existing queue rather than creating a second socket architecture.

## Identity enforcement

The server chooses the connection by canonical `client_id`, not by a client-supplied target in the response. The response reader already associates frames with the socket's registered MAC. The Kismet response should include `client_id` for validation and observability, but the server must compare it with the registry's authoritative ID and reject mismatch. The response cannot redirect itself to another client.

## Timeout and disconnect behavior

`execute_client_command()` has a default ten-second timeout and returns a structured error. Telemetry flow helpers use a fifteen-second convention. Kismet queries should use a named configurable timeout appropriate for SQLite and bounded results, initially fifteen seconds unless profiling proves otherwise. Disconnects are surfaced by the existing `DISCONNECTED` queue sentinel.

## Existing framing

Do not use newline-delimited JSON, a new socket, or a binary payload. Use the four-byte length prefix and JSON serializer already used by both `client_lib.send_message()` and server-side `send_message()`.

## Implementation anchor record

| File                                     | Class/function                    | Current behavior                                          | Planned reuse                                 |
| ---------------------------------------- | --------------------------------- | --------------------------------------------------------- | --------------------------------------------- |
| `server/server_components/server_lib.py` | `execute_client_command`          | Sends a `COMMAND`, waits on one client's response queue   | Add/consume Kismet-specific validated wrapper |
| `server/server_components/server_lib.py` | `receive_client_messages`         | Sole post-registration reader; routes `RESPONSE` to queue | Keep as the only socket reader                |
| `client/app/client.py`                   | command loop                      | Dispatches `COMMAND` and sends `RESPONSE`                 | Add one Kismet branch                         |
| `client/app/client_lib.py`               | `send_message`, `receive_message` | Length-prefixed JSON framing                              | Keep unchanged                                |
| `client/app/flow_query.py`               | `get_requested_flows`             | Local bounded query for an existing command               | Follow bounded local-query/error pattern      |
