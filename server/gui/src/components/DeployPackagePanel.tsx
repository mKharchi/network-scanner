import { useEffect, useMemo, useRef, useState } from "react";
import { api, type ActionDetail } from "../api/client";
import { Button } from "./Button";
import { Notice } from "./States";

const MAX_PACKAGE_BYTES = 200 * 1024 * 1024;

function deployTimeoutMs(fileSizeBytes: number): number {
  const chunkSize = 128 * 1024;
  const totalChunks = Math.max(1, Math.ceil(fileSizeBytes / chunkSize));
  // Match server watchdog: 3s per chunk, minimum 5 minutes, plus a small GUI buffer.
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
  return base || `pkg-${Date.now()}`;
}

function targetRows(action: ActionDetail | null) {
  return action?.targets ?? action?.result?.targets ?? [];
}

interface DeployPackagePanelProps {
  targets: string[];
  disabled?: boolean;
  title?: string;
  description?: string;
  onCompleted?: (action: ActionDetail) => void;
}

export function DeployPackagePanel({
  targets,
  disabled = false,
  title = "Deploy package",
  description = "Upload a .zip archive (up to 200 MB). The agent verifies the hash, extracts safely, and swaps it into updates/current/.",
  onCompleted,
}: DeployPackagePanelProps) {
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [packageId, setPackageId] = useState("");
  const [deploying, setDeploying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [action, setAction] = useState<ActionDetail | null>(null);

  const uniqueTargets = useMemo(
    () =>
      Array.from(
        new Set(targets.map((target) => target.trim()).filter(Boolean)),
      ),
    [targets],
  );

  useEffect(() => {
    const handler = (event: Event) => {
      const detail = (event as CustomEvent).detail;
      if (!action?.action_id || detail?.action_id !== action.action_id) {
        return;
      }
      void api
        .getAction(action.action_id)
        .then(setAction)
        .catch(() => undefined);
    };

    window.addEventListener("app:action_update", handler);
    return () => window.removeEventListener("app:action_update", handler);
  }, [action?.action_id]);

  const handleFileChange = (file: File | null) => {
    setSelectedFile(file);
    setError(null);
    if (file) {
      setPackageId(defaultPackageId(file));
    }
  };

  const handleDeploy = async () => {
    if (!selectedFile || uniqueTargets.length === 0) {
      return;
    }
    if (!selectedFile.name.toLowerCase().endsWith(".zip")) {
      setError("Package must be a .zip file.");
      return;
    }
    if (selectedFile.size > MAX_PACKAGE_BYTES) {
      setError(
        `Package is too large (${formatBytes(selectedFile.size)}). Limit is ${formatBytes(MAX_PACKAGE_BYTES)}.`,
      );
      return;
    }

    setDeploying(true);
    setError(null);
    setAction(null);

    try {
      const resolvedPackageId =
        packageId.trim() || defaultPackageId(selectedFile);
      const transferTimeoutMs = deployTimeoutMs(selectedFile.size);
      const uploaded = await api.uploadPackage(selectedFile, {
        packageId: resolvedPackageId,
      });
      const created = await api.deployPackage({
        targets: uniqueTargets,
        packageId: uploaded.package_id,
        timeoutSeconds: transferTimeoutMs / 1000,
      });
      setAction(created);

      const finalAction = await api.waitForAction(created.action_id, {
        onUpdate: setAction,
        timeoutMs: transferTimeoutMs,
      });
      setAction(finalAction);
      onCompleted?.(finalAction);
    } catch (err: any) {
      setError(err?.message ?? "Package deployment failed.");
    } finally {
      setDeploying(false);
    }
  };

  const progress = action?.progress;
  const rows = targetRows(action);
  const isTerminal =
    action &&
    ["SUCCESS", "FAILED", "PARTIAL_SUCCESS", "CANCELLED", "EXPIRED"].includes(
      action.status,
    );

  return (
    <div
      style={{
        display: "grid",
        gap: "var(--space-3)",
        width: "100%",
        padding: "var(--space-3)",
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
            marginBottom: "var(--space-1)",
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
          Choose at least one online client before deploying.
        </Notice>
      )}

      <label
        style={{
          width: "100%",
          display: "flex",
          flexDirection: "column",
          gap: "var(--space-1)",
          cursor: disabled || deploying ? "not-allowed" : "pointer",
        }}
      >
        <span
          style={{
            fontSize: "var(--font-xs)",
            color: "var(--text-muted)",
          }}
        >
          Package (.zip)
        </span>

        <div
          style={{
            position: "relative",
            width: "100%",
            display: "flex",
            alignItems: "center",
            gap: "var(--space-2)",
            padding: "var(--space-2) var(--space-3)",
            border: "1px solid var(--border-color)",
            borderRadius: "var(--radius-md)",
            background: "var(--bg-secondary)",
            transition: "all 0.2s ease",
            opacity: disabled || deploying ? 0.6 : 1,
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".zip,application/zip"
            disabled={disabled || deploying}
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
              borderRadius: "var(--radius-sm)",
              background: "rgba(37, 99, 235, 0.12)",
              color: "var(--accent-blue)",
            }}
          >
            {/* Upload / package icon */}
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
              <path d="M12 16V4" />
              <path d="M8 8l4-4 4 4" />
              <path d="M4 16v3a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3" />
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
                color: "var(--text-primary)",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
              }}
            >
              {selectedFile ? selectedFile.name : "Choose ZIP package"}
            </span>

            <span
              style={{
                fontSize: "var(--font-xs)",
                color: "var(--text-muted)",
              }}
            >
              {selectedFile
                ? formatBytes(selectedFile.size)
                : "Select a package to deploy"}
            </span>
          </div>

          <span
            style={{
              flexShrink: 0,
              fontSize: "var(--font-xs)",
              fontWeight: 500,
              color: "var(--accent-blue)",
            }}
          >
            {selectedFile ? "Change" : "Browse"}
          </span>
        </div>
      </label>

      <label style={{ display: "grid", gap: "var(--space-1)" }}>
        <span
          style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}
        >
          Package ID
        </span>
        <input
          type="text"
          value={packageId}
          disabled={disabled || deploying}
          onChange={(event) => setPackageId(event.target.value)}
          placeholder="e.g. agent-update-v1"
          style={{
            background: "var(--surface)",
            color: "var(--text)",
            border: "1px solid var(--border)",
            borderRadius: "var(--radius-sm)",
            padding: "8px 10px",
            fontSize: "var(--font-sm)",
          }}
        />
      </label>

      <div
        style={{
          display: "flex",
          gap: "var(--space-2)",
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <Button
          variant="primary"
          size="md"
          disabled={
            disabled || deploying || !selectedFile || uniqueTargets.length === 0
          }
          onClick={() => void handleDeploy()}
        >
          {deploying
            ? `Deploying to ${uniqueTargets.length} client${uniqueTargets.length === 1 ? "" : "s"}…`
            : `Deploy to ${uniqueTargets.length} client${uniqueTargets.length === 1 ? "" : "s"}`}
        </Button>
        {uniqueTargets.length > 1 && (
          <span
            style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}
          >
            Up to 5 transfers run concurrently on the server.
          </span>
        )}
      </div>

      {error && (
        <Notice variant="danger" title="Deployment failed">
          {error}
        </Notice>
      )}

      {action && (
        <div style={{ display: "grid", gap: "var(--space-2)" }}>
          <div style={{ fontSize: "var(--font-sm)" }}>
            <strong>Action:</strong> {action.action_id}
            <br />
            <strong>Status:</strong> {action.status}
          </div>

          {progress && (
            <div
              style={{ fontSize: "var(--font-sm)", color: "var(--text-muted)" }}
            >
              {progress.completed}/{progress.total} completed ·{" "}
              {progress.succeeded} succeeded · {progress.failed} failed ·{" "}
              {progress.in_progress} in progress · {progress.pending} pending
            </div>
          )}

          {rows.length > 0 && (
            <div className="data-table-wrap">
              <table
                className="data-table"
                aria-label="Deployment target status"
              >
                <thead>
                  <tr>
                    <th>Client</th>
                    <th>Status</th>
                    <th>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => {
                    const detail =
                      typeof row.result?.message === "string"
                        ? row.result.message
                        : typeof row.error?.message === "string"
                          ? row.error.message
                          : row.result?.error
                            ? String(row.error)
                            : "—";
                    return (
                      <tr key={row.client_id ?? `target-${index}`}>
                        <td className="cell--mono">{row.client_id ?? "—"}</td>
                        <td>{row.status ?? "—"}</td>
                        <td
                          style={{
                            fontSize: "var(--font-xs)",
                            color: "var(--text-muted)",
                          }}
                        >
                          {detail}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {isTerminal && action.status === "SUCCESS" && (
            <Notice variant="success" title="Deployment complete">
              Package extracted on all target clients.
            </Notice>
          )}
          {isTerminal && action.status === "PARTIAL_SUCCESS" && (
            <Notice variant="warning" title="Partial success">
              Some clients failed. Review per-target status above and retry
              failed clients.
            </Notice>
          )}
        </div>
      )}
    </div>
  );
}
