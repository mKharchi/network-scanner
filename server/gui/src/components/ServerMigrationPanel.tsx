import { useState } from "react";
import { api } from "../api/client";
import type { ActionDetail } from "../api/client";
import { Button } from "./Button";
import { Notice } from "./States";
import "../styles/migration.css";


// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Keys the server allowlist permits — kept in sync with server + client */
const RECONFIGURE_ALLOWLIST = [
  "SERVER_IP",
  "SERVER_PORT",
  "NETWORK_SCAN_INTERFACE",
  "NETWORK_SCAN_SUBNET",
  "DHCP_LISTEN_INTERFACE",
  "FORBIDDEN_PROCESS_SCAN_INTERVAL_SECONDS",
  "PROCESS_SCAN_INTERVAL_SECONDS",
  "QUARANTINE_MAX_DURATION_MINUTES",
  "AUTO_ISOLATE_ON_ESCALATION",
  "SCREENSHOT_MAX_RESPONSE_BYTES",
  "NETWORK_NEIGHBOUR_HOSTNAME_LOOKUP_LIMIT",
] as const;

type AllowedKey = (typeof RECONFIGURE_ALLOWLIST)[number];

interface ConfigRow {
  key: AllowedKey | "";
  value: string;
}

type BroadcastState =
  | { phase: "idle" }
  | { phase: "sending" }
  | { phase: "success"; action: ActionDetail; targetCount: number }
  | { phase: "error"; message: string };

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function groupTargetsByStatus(action: ActionDetail) {
  const rows = action.result?.targets ?? action.targets ?? [];
  const success = rows.filter((t) => t.status === "SUCCESS" || t.status === "COMPLETED");
  const failed  = rows.filter((t) => t.status === "FAILED"  || t.status === "ERROR");
  const pending = rows.filter(
    (t) => t.status !== "SUCCESS" && t.status !== "COMPLETED" && t.status !== "FAILED" && t.status !== "ERROR"
  );
  return { success, failed, pending };
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function KeySelect({
  value,
  usedKeys,
  onChange,
}: {
  value: AllowedKey | "";
  usedKeys: Set<string>;
  onChange: (k: AllowedKey | "") => void;
}) {
  return (
    <select
      className="migration-select"
      value={value}
      onChange={(e) => onChange(e.target.value as AllowedKey | "")}
    >
      <option value="">— select a key —</option>
      {RECONFIGURE_ALLOWLIST.map((k) => (
        <option key={k} value={k} disabled={usedKeys.has(k) && k !== value}>
          {k}
        </option>
      ))}
    </select>
  );
}

function ResultTable({ action }: { action: ActionDetail }) {
  const { success, failed, pending } = groupTargetsByStatus(action);
  const all = [...success, ...failed, ...pending];
  if (all.length === 0) return null;

  return (
    <div className="migration-result-table-wrap">
      <table className="data-table migration-result-table">
        <thead>
          <tr>
            <th>Client</th>
            <th>Status</th>
            <th>Detail</th>
          </tr>
        </thead>
        <tbody>
          {all.map((t, idx) => {
            const isOk  = t.status === "SUCCESS" || t.status === "COMPLETED";
            const isBad = t.status === "FAILED"  || t.status === "ERROR";
            return (
              <tr key={t.client_id ?? idx}>
                <td className="mono">{t.client_id ?? "—"}</td>
                <td>
                  <span
                    className={
                      isOk  ? "badge badge--online"  :
                      isBad ? "badge badge--offline" :
                              "badge badge--unknown"
                    }
                  >
                    {t.status}
                  </span>
                </td>
                <td className="migration-result-detail">
                  {t.result
                    ? (t.result as any).message ??
                      (t.result as any).error ??
                      JSON.stringify(t.result)
                    : "—"}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export function ServerMigrationPanel() {
  const [rows, setRows] = useState<ConfigRow[]>([{ key: "SERVER_IP", value: "" }]);
  const [targetMode, setTargetMode] = useState<"all" | "specific">("all");
  const [specificTargets, setSpecificTargets] = useState("");
  const [broadcast, setBroadcast] = useState<BroadcastState>({ phase: "idle" });

  // Compute which keys are already chosen (for duplicate prevention)
  const usedKeys = new Set(rows.map((r) => r.key).filter(Boolean));

  function addRow() {
    if (rows.length >= RECONFIGURE_ALLOWLIST.length) return;
    setRows((prev) => [...prev, { key: "", value: "" }]);
  }

  function removeRow(idx: number) {
    setRows((prev) => prev.filter((_, i) => i !== idx));
  }

  function updateRow(idx: number, patch: Partial<ConfigRow>) {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  }

  function buildParameters(): Record<string, string> | null {
    const params: Record<string, string> = {};
    for (const row of rows) {
      if (!row.key) continue;
      if (!row.value.trim()) return null; // incomplete row
      params[row.key] = row.value.trim();
    }
    return Object.keys(params).length > 0 ? params : null;
  }

  function resolveTargets(): string[] | null {
    if (targetMode === "all") return ["all"];
    const ids = specificTargets
      .split(/[\n,]+/)
      .map((s) => s.trim())
      .filter(Boolean);
    return ids.length > 0 ? ids : null;
  }

  const canSubmit =
    broadcast.phase !== "sending" &&
    rows.some((r) => r.key && r.value.trim());

  async function handleBroadcast() {
    const parameters = buildParameters();
    if (!parameters) {
      setBroadcast({ phase: "error", message: "Fill in a value for every selected key." });
      return;
    }
    const targets = resolveTargets();
    if (!targets) {
      setBroadcast({ phase: "error", message: "Enter at least one client ID." });
      return;
    }

    setBroadcast({ phase: "sending" });
    try {
      const action = await api.reconfigureClients({ parameters, targets });
      const targetCount =
        (action.result?.targets ?? action.targets ?? []).length;
      setBroadcast({ phase: "success", action, targetCount });
    } catch (err: any) {
      const msg =
        err?.message ??
        (typeof err === "string" ? err : "Server returned an error.");
      setBroadcast({ phase: "error", message: msg });
    }
  }

  function handleReset() {
    setRows([{ key: "SERVER_IP", value: "" }]);
    setTargetMode("all");
    setSpecificTargets("");
    setBroadcast({ phase: "idle" });
  }

  return (
    <div className="migration-panel">
      {/* ── Header notice ────────────────────────────────────────────── */}
      <Notice variant="warning" title="Server Migration Action">
        This broadcasts a config patch to connected clients over their live TCP
        connection. Each client will atomically update its{" "}
        <code>config/.env</code> and restart. Use{" "}
        <strong>All clients</strong> to migrate the whole fleet at once.
      </Notice>

      {/* ── Config rows ──────────────────────────────────────────────── */}
      <div className="migration-rows">
        <div className="migration-rows-header">
          <span>Config key</span>
          <span>New value</span>
        </div>

        {rows.map((row, idx) => (
          <div key={idx} className="migration-row">
            <KeySelect
              value={row.key}
              usedKeys={usedKeys}
              onChange={(k) => updateRow(idx, { key: k })}
            />
            <input
              className="migration-input"
              type="text"
              placeholder={
                row.key === "SERVER_IP"   ? "e.g. 10.0.0.5" :
                row.key === "SERVER_PORT" ? "e.g. 5000"      :
                "new value"
              }
              value={row.value}
              onChange={(e) => updateRow(idx, { value: e.target.value })}
            />
            {rows.length > 1 && (
              <button
                className="migration-remove-btn"
                onClick={() => removeRow(idx)}
                aria-label="Remove row"
              >
                ✕
              </button>
            )}
          </div>
        ))}

        {rows.length < RECONFIGURE_ALLOWLIST.length && (
          <Button variant="quiet" size="sm" onClick={addRow}>
            + Add another key
          </Button>
        )}
      </div>

      {/* ── Target selection ─────────────────────────────────────────── */}
      <div className="migration-targets">
        <label className="migration-label">Target clients</label>
        <div className="migration-target-toggle">
          <label className="migration-radio">
            <input
              type="radio"
              name="targetMode"
              value="all"
              checked={targetMode === "all"}
              onChange={() => setTargetMode("all")}
            />
            All currently connected clients
          </label>
          <label className="migration-radio">
            <input
              type="radio"
              name="targetMode"
              value="specific"
              checked={targetMode === "specific"}
              onChange={() => setTargetMode("specific")}
            />
            Specific client IDs
          </label>
        </div>

        {targetMode === "specific" && (
          <textarea
            className="migration-textarea"
            placeholder={"client-e4fd45ba8605\nDESKTOP-E4KIQ7T\n..."}
            value={specificTargets}
            onChange={(e) => setSpecificTargets(e.target.value)}
            rows={4}
          />
        )}
      </div>

      {/* ── Status feedback ──────────────────────────────────────────── */}
      {broadcast.phase === "error" && (
        <Notice variant="danger" title="Broadcast failed">
          {broadcast.message}
        </Notice>
      )}

      {broadcast.phase === "success" && (
        <>
          <Notice variant="success" title="Broadcast dispatched">
            Action <code>{broadcast.action.action_id}</code> sent to{" "}
            {broadcast.targetCount} client
            {broadcast.targetCount !== 1 ? "s" : ""}. Clients are patching
            their config and restarting — they will reconnect within a few
            seconds.
          </Notice>
          <ResultTable action={broadcast.action} />
        </>
      )}

      {/* ── Actions ──────────────────────────────────────────────────── */}
      <div className="migration-actions">
        {broadcast.phase === "success" ? (
          <Button variant="secondary" onClick={handleReset}>
            New broadcast
          </Button>
        ) : (
          <Button
            variant="primary"
            loading={broadcast.phase === "sending"}
            disabled={!canSubmit}
            onClick={handleBroadcast}
          >
            {broadcast.phase === "sending" ? "Broadcasting…" : "Broadcast to clients"}
          </Button>
        )}
      </div>
    </div>
  );
}
