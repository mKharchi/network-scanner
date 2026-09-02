import { useMemo, useRef, useState } from "react";
import {
  api,
  type ActionDetail,
  type BulkUpdateDetail,
} from "../api/client";
import { Badge } from "./Badge";
import { Button } from "./Button";
import { Notice } from "./States";

const MAX_PACKAGE_BYTES = 200 * 1024 * 1024;

function deployTimeoutMs(fileSizeBytes: number): number {
  const chunkSize = 128 * 1024;
  const totalChunks = Math.max(1, Math.ceil(fileSizeBytes / chunkSize));
  return Math.max(5 * 60 * 1000, totalChunks * 3 * 1000 + 60 * 1000);
}

function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes <= 0) {
    return "0 B";
  }
  const units = ["B", "KB", "MB", "GB"];
  let size = bytes;
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size >= 10 || unitIndex === 0 ? size.toFixed(0) : size.toFixed(1)} ${units[unitIndex]}`;
}

function defaultPackageId(file: File): string {
  const base = file.name.replace(/\.zip$/i, "").trim();
  return base || `client-update-${Date.now()}`;
}

interface UpdateClientPanelProps {
  targets: string[];
  disabled?: boolean;
  title?: string;
  description?: string;
  onCompleted?: (result: any) => void;
}

export function UpdateClientPanel({
  targets,
  disabled = false,
  title = "Update Client Application",
  description = "Deploy and apply a client update package (manifest.json + app/). The updater will back up current app/, install dependencies, validate startup, and automatically roll back on failure.",
  onCompleted,
}: UpdateClientPanelProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [packageId, setPackageId] = useState("");
  const [updating, setUpdating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bulkStatus, setBulkStatus] = useState<BulkUpdateDetail | null>(null);
  const [singleAction, setSingleAction] = useState<ActionDetail | null>(null);

  const uniqueTargets = useMemo(
    () =>
      Array.from(
        new Set(targets.map((target) => target.trim()).filter(Boolean)),
      ),
    [targets],
  );

  const isBulk = uniqueTargets.length > 1;

  const handleFileChange = (file: File | null) => {
    setSelectedFile(file);
    setError(null);
    if (file) {
      setPackageId(defaultPackageId(file));
    }
  };

  const handleUpdate = async () => {
    if (!selectedFile || uniqueTargets.length === 0) {
      return;
    }
    if (!selectedFile.name.toLowerCase().endsWith(".zip")) {
      setError("Package must be a .zip file containing manifest.json and app/ folder.");
      return;
    }
    if (selectedFile.size > MAX_PACKAGE_BYTES) {
      setError(
        `Package is too large (${formatBytes(selectedFile.size)}). Limit is ${formatBytes(MAX_PACKAGE_BYTES)}.`,
      );
      return;
    }

    setUpdating(true);
    setError(null);
    setBulkStatus(null);
    setSingleAction(null);

    try {
      const resolvedPackageId =
        packageId.trim() || defaultPackageId(selectedFile);
      const transferTimeoutMs = deployTimeoutMs(selectedFile.size);

      // Upload update package to server package store
      const uploaded = await api.uploadPackage(selectedFile, {
        packageId: resolvedPackageId,
      });

      if (isBulk) {
        // Multi-client bulk update via POST /api/v1/bulk-updates
        const bulkInit = await api.createBulkUpdate({
          packageId: uploaded.package_id,
          targetSelection: {
            strategy: "individual",
            client_ids: uniqueTargets,
          },
        });

        // Poll status until all clients complete or fail
        const finalStatus = await api.waitForBulkUpdate(bulkInit.bulk_update_id, {
          onUpdate: setBulkStatus,
          timeoutMs: transferTimeoutMs,
        });

        setBulkStatus(finalStatus);
        onCompleted?.(finalStatus);
      } else {
        // Single client update via UPDATE_CLIENT action
        const created = await api.updateClient({
          target: uniqueTargets[0],
          packageId: uploaded.package_id,
          timeoutSeconds: transferTimeoutMs / 1000,
        });
        setSingleAction(created);

        const finalAction = await api.waitForAction(created.action_id, {
          onUpdate: setSingleAction,
          timeoutMs: transferTimeoutMs,
        });

        setSingleAction(finalAction);
        onCompleted?.(finalAction);
      }
    } catch (err: any) {
      setError(err?.message ?? "Update operation failed.");
    } finally {
      setUpdating(false);
    }
  };

  const aggregate = bulkStatus?.aggregate_status;
  const progressPercent = aggregate && aggregate.total > 0
    ? Math.round(((aggregate.completed + aggregate.failed) / aggregate.total) * 100)
    : 0;

  return (
    <div
      style={{
        display: "grid",
        gap: "var(--space-3)",
        width: "100%",
        padding: "var(--space-4)",
        border: "1px solid var(--border)",
        borderRadius: "var(--radius)",
        background: "var(--surface)",
      }}
    >
      <div style={{ display: "grid", gap: "var(--space-1)", width: "100%" }}>
        <div
          style={{
            fontSize: "var(--font-xs)",
            color: "var(--text)",
            fontWeight: 600,
            textTransform: "uppercase",
            letterSpacing: "0.06em",
          }}
        >
          {title}
        </div>
        <p
          style={{
            margin: 0,
            fontSize: "var(--font-sm)",
            color: "var(--text-muted)",
          }}
        >
          {description}
        </p>
      </div>

      {uniqueTargets.length === 0 && (
        <Notice variant="warning" title="No targets selected">
          Choose at least one online client before updating.
        </Notice>
      )}

      {/* Package File Upload input */}
      <label
        style={{
          width: "100%",
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-1)",
          cursor: disabled || updating ? "not-allowed" : "pointer",
        }}
      >
        <span
          style={{
            fontSize: "var(--font-xs)",
            color: "var(--text-muted)",
          }}
        >
          Update Package (.zip)
        </span>

        <div
          style={{
            position: "relative",
            width: "100%",
            display: "flex",
            alignItems: "center",
            gap: "var(--space-2)",
            padding: "var(--space-2) var(--space-3)",
            border: "1px solid var(--border-color, var(--border))",
            borderRadius: "var(--radius-md, var(--radius))",
            background: "var(--bg-secondary, var(--surface-subtle))",
            transition: "all 0.2s ease",
            opacity: disabled || updating ? 0.6 : 1,
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip,application/zip"
            disabled={disabled || updating}
            onChange={(event) =>
              handleFileChange(event.target.files?.[0] ?? null)
            }
            style={{
              position: "absolute",
              width: "1px",
              height: "1px",
              opacity: 0,
              pointerEvents: "none",
            }}
          />

          <div
            style={{
              width: "34px",
              height: "34px",
              flexShrink: 0,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              borderRadius: "var(--radius-sm, 4px)",
              background: "rgba(16, 185, 129, 0.12)",
              color: "#10b981",
            }}
          >
            <svg
              width="18"
              height="18"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          </div>

          <div
            style={{
              minWidth: 0,
              flex: 1,
              display: "flex",
              flexDirection: "column",
              gap: "2px",
            }}
          >
            <span
              style={{
                fontSize: "var(--font-xs)",
                fontWeight: 500,
                color: "var(--text-primary, var(--text))",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {selectedFile ? selectedFile.name : "Choose update package (.zip)"}
            </span>

            <span
              style={{
                fontSize: "var(--font-xs)",
                color: "var(--text-muted)",
              }}
            >
              {selectedFile
                ? `${formatBytes(selectedFile.size)} · Click to change`
                : "Select client-update-<version>.zip containing manifest.json and app/"}
            </span>
          </div>
        </div>
      </label>

      {/* Package ID input */}
      <div style={{ display: "grid", gap: "var(--space-1)" }}>
        <label
          htmlFor="update-package-id"
          style={{
            fontSize: "var(--font-xs)",
            color: "var(--text-muted)",
          }}
        >
          Package Identifier
        </label>
        <input
          id="update-package-id"
          type="text"
          value={packageId}
          placeholder="e.g. app-v2.0.0"
          disabled={disabled || updating}
          onChange={(e) => setPackageId(e.target.value)}
          style={{
            padding: "var(--space-2) var(--space-3)",
            fontSize: "var(--font-sm)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            background: "var(--bg)",
            color: "var(--text)",
          }}
        />
      </div>

      {error && (
        <Notice variant="danger" title="Update failed">
          {error}
        </Notice>
      )}

      {/* Action Trigger Button */}
      <div style={{ display: "flex", justifyContent: "flex-end", gap: "var(--space-2)" }}>
        <Button
          variant="primary"
          disabled={disabled || updating || !selectedFile || uniqueTargets.length === 0}
          onClick={handleUpdate}
        >
          {updating
            ? isBulk
              ? `Updating ${uniqueTargets.length} clients…`
              : "Updating client…"
            : isBulk
              ? `Update ${uniqueTargets.length} Clients`
              : "Update Client"}
        </Button>
      </div>

      {/* Bulk Update Status View */}
      {bulkStatus && (
        <div
          style={{
            display: "grid",
            gap: "var(--space-3)",
            marginTop: "var(--space-2)",
            padding: "var(--space-3)",
            borderRadius: "var(--radius)",
            background: "var(--surface-subtle, rgba(255,255,255,0.03))",
            border: "1px solid var(--border)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontWeight: 600, fontSize: "var(--font-sm)" }}>
              Batch Progress ({bulkStatus.bulk_update_id})
            </span>
            <span style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>
              {bulkStatus.aggregate_status.completed} / {bulkStatus.aggregate_status.total} succeeded
              {bulkStatus.aggregate_status.failed > 0 && ` · ${bulkStatus.aggregate_status.failed} failed`}
            </span>
          </div>

          {/* Progress bar */}
          <div
            style={{
              width: "100%",
              height: "6px",
              borderRadius: "3px",
              background: "var(--border)",
              overflow: "hidden",
            }}
          >
            <div
              style={{
                width: `${progressPercent}%`,
                height: "100%",
                background:
                  bulkStatus.aggregate_status.failed > 0
                    ? "var(--danger, #ef4444)"
                    : "var(--success, #10b981)",
                transition: "width 0.3s ease",
              }}
            />
          </div>

          {/* Per-Client Status Table */}
          <div style={{ overflowX: "auto" }}>
            <table
              style={{
                width: "100%",
                borderCollapse: "collapse",
                fontSize: "var(--font-xs)",
              }}
            >
              <thead>
                <tr style={{ borderBottom: "1px solid var(--border)", textAlign: "left" }}>
                  <th style={{ padding: "6px 8px" }}>Client</th>
                  <th style={{ padding: "6px 8px" }}>Hostname</th>
                  <th style={{ padding: "6px 8px" }}>Status</th>
                  <th style={{ padding: "6px 8px" }}>Details</th>
                </tr>
              </thead>
              <tbody>
                {bulkStatus.per_client_status.map((item) => {
                  const status = item.status.toUpperCase();
                  const isSuccess = ["COMPLETED", "SUCCESS"].includes(status);
                  const isFailed = ["FAILED", "CANCELLED"].includes(status);
                  const isRunning = status === "RUNNING";

                  const badgeVariant = isSuccess
                    ? "success"
                    : isFailed
                      ? "danger"
                      : isRunning
                        ? "primary"
                        : "muted";

                  const details =
                    item.result?.error ||
                    item.result?.reason ||
                    item.result?.message ||
                    (isSuccess ? "Updated successfully" : "—");

                  return (
                    <tr
                      key={item.action_id}
                      style={{
                        borderBottom: "1px solid var(--border-subtle, rgba(255,255,255,0.05))",
                      }}
                    >
                      <td style={{ padding: "6px 8px", fontWeight: 500 }}>{item.client_id}</td>
                      <td style={{ padding: "6px 8px", color: "var(--text-muted)" }}>
                        {item.hostname}
                      </td>
                      <td style={{ padding: "6px 8px" }}>
                        <Badge variant={badgeVariant}>{status}</Badge>
                      </td>
                      <td
                        style={{
                          padding: "6px 8px",
                          color: isFailed ? "var(--danger, #ef4444)" : "var(--text-muted)",
                        }}
                      >
                        {String(details)}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Single Client Action Status View */}
      {singleAction && !bulkStatus && (
        <div
          style={{
            display: "grid",
            gap: "var(--space-2)",
            marginTop: "var(--space-2)",
            padding: "var(--space-3)",
            borderRadius: "var(--radius)",
            background: "var(--surface-subtle, rgba(255,255,255,0.03))",
            border: "1px solid var(--border)",
          }}
        >
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span style={{ fontWeight: 600, fontSize: "var(--font-sm)" }}>
              Update Action: {singleAction.action_id}
            </span>
            <Badge
              variant={
                singleAction.status === "SUCCESS" || singleAction.status === "COMPLETED"
                  ? "success"
                  : singleAction.status === "FAILED"
                    ? "danger"
                    : singleAction.status === "RUNNING"
                      ? "primary"
                      : "muted"
              }
            >
              {singleAction.status}
            </Badge>
          </div>

          {singleAction.status === "SUCCESS" && (
            <Notice variant="success" title="Client Updated">
              Update package deployed and verified. The client agent will report the new version on its next heartbeat.
            </Notice>
          )}

          {singleAction.status === "FAILED" && (
            <Notice variant="danger" title="Update Failed (Rolled Back)">
              The update encountered an error and the previous working version was restored.
            </Notice>
          )}
        </div>
      )}
    </div>
  );
}
