import { useState, useEffect } from "react";
import {
  api,
  type ForbiddenProcessRule,
  type ResourceProtectionSettings,
} from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { SeverityBadge, type AlertSeverity } from "../components/Badge";
import { SectionCard } from "../components/Card";
import { Button } from "../components/Button";
import { SkeletonTable, ErrorState, Notice } from "../components/States";
import { DAY_NAMES, formatDateTime } from "../utils/format";
import "../styles/operations.css";
import { NumberInput } from "../components/NumberInput";

interface WorkingHoursData {
  rules: {
    day_of_week: number;
    start_time: string;
    end_time: string;
    enabled: boolean;
  }[];
  current_status: { within_working_hours: boolean; checked_at: string };
}

interface ForbiddenProcessesData {
  items: ForbiddenProcessRule[];
}

export function SettingsPage() {
  // Forbidden Process state
  const [newProcessName, setNewProcessName] = useState("");
  const [newSeverity, setNewSeverity] = useState("HIGH");
  const [newDescription, setNewDescription] = useState("");
  const [newTerminateOnDetect, setNewTerminateOnDetect] = useState(true);
  const [newResourceProtectionEligible, setNewResourceProtectionEligible] =
    useState(true);
  const [ruleSearch, setRuleSearch] = useState("");
  const [ruleBusy, setRuleBusy] = useState(false);
  const [ruleError, setRuleError] = useState<string | null>(null);

  // Resource Protection state
  const [rpSettings, setRpSettings] =
    useState<ResourceProtectionSettings | null>(null);
  const [rpBusy, setRpBusy] = useState(false);
  const [rpError, setRpError] = useState<string | null>(null);
  const [rpSuccess, setRpSuccess] = useState<string | null>(null);

  const { state: whState, refetch: refetchWh } = useFetch<WorkingHoursData>(
    () => api.getWorkingHours(),
    [],
  );

  const { state: fpState, refetch: refetchFp } =
    useFetch<ForbiddenProcessesData>(() => api.getForbiddenProcesses(), []);

  const { state: rpState, refetch: refetchRp } =
    useFetch<ResourceProtectionSettings>(() => api.getResourceProtection(), []);

  const rpData = rpState.status === "success" ? rpState.data : undefined;

  useEffect(() => {
    if (rpData) {
      setRpSettings(rpData);
    }
  }, [rpData]);

  const isStale =
    whState.status === "error" ||
    fpState.status === "error" ||
    rpState.status === "error";

  const whData: WorkingHoursData | null =
    whState.status === "success"
      ? whState.data
      : whState.status === "error" && whState.staleData
        ? whState.staleData
        : null;

  const fpData: ForbiddenProcessesData | null =
    fpState.status === "success"
      ? fpState.data
      : fpState.status === "error" && fpState.staleData
        ? fpState.staleData
        : null;

  async function addRule() {
    if (!newProcessName.trim()) return;
    setRuleBusy(true);
    setRuleError(null);
    try {
      await api.createForbiddenProcess({
        process_name: newProcessName.trim(),
        severity: newSeverity,
        enabled: true,
        description: newDescription.trim() || null,
        terminate_on_detection: newTerminateOnDetect,
        resource_protection_eligible: newResourceProtectionEligible,
      });
      setNewProcessName("");
      setNewDescription("");
      setNewTerminateOnDetect(true);
      setNewResourceProtectionEligible(true);
      refetchFp();
    } catch (error) {
      setRuleError(error instanceof Error ? error.message : String(error));
    } finally {
      setRuleBusy(false);
    }
  }

  async function updateRule(
    rule: ForbiddenProcessRule,
    updates: Partial<Omit<ForbiddenProcessRule, "process_name">>,
  ) {
    setRuleBusy(true);
    setRuleError(null);
    try {
      await api.updateForbiddenProcess(rule.process_name, {
        severity: updates.severity ?? rule.severity,
        enabled: updates.enabled ?? rule.enabled,
        description:
          updates.description !== undefined
            ? updates.description
            : rule.description,
        terminate_on_detection:
          updates.terminate_on_detection ?? rule.terminate_on_detection ?? true,
        resource_protection_eligible:
          updates.resource_protection_eligible ??
          rule.resource_protection_eligible ??
          true,
      });
      refetchFp();
    } catch (error) {
      setRuleError(error instanceof Error ? error.message : String(error));
    } finally {
      setRuleBusy(false);
    }
  }

  async function deleteRule(processName: string) {
    if (
      !window.confirm(`Delete the forbidden-process rule for ${processName}?`)
    )
      return;
    setRuleBusy(true);
    setRuleError(null);
    try {
      await api.deleteForbiddenProcess(processName);
      refetchFp();
    } catch (error) {
      setRuleError(error instanceof Error ? error.message : String(error));
    } finally {
      setRuleBusy(false);
    }
  }

  async function saveResourceProtection() {
    if (!rpSettings) return;
    setRpBusy(true);
    setRpError(null);
    setRpSuccess(null);
    try {
      const updated = await api.updateResourceProtection(rpSettings);
      setRpSettings(updated);
      setRpSuccess(
        "Resource protection settings saved and broadcast to all clients.",
      );
      setTimeout(() => setRpSuccess(null), 4000);
    } catch (error) {
      setRpError(error instanceof Error ? error.message : String(error));
    } finally {
      setRpBusy(false);
    }
  }

  const filteredRules = (fpData?.items ?? []).filter((item) => {
    if (!ruleSearch.trim()) return true;
    const term = ruleSearch.toLowerCase();
    return (
      item.process_name.toLowerCase().includes(term) ||
      (item.description && item.description.toLowerCase().includes(term)) ||
      item.severity.toLowerCase().includes(term)
    );
  });

  return (
    <div>
      <div className="page-header operations-page-header">
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            gap: "var(--space-2)",
          }}
        >
          <span className="eyebrow eyebrow--accent">SYSTEM / GOVERNANCE</span>
          <h1 className="page-title">Monitoring & Protection Policies</h1>
          <p className="page-description">
            Configure centralized policies for forbidden processes, automatic
            client resource protection, and working hours.
          </p>
        </div>
        <div className="operations-page-header__actions">
          <Button
            variant="quiet"
            size="sm"
            onClick={() => {
              refetchWh();
              refetchFp();
              refetchRp();
            }}
          >
            Refresh All
          </Button>
        </div>
      </div>

      {isStale && (
        <Notice
          variant="warning"
          title="Some configuration settings could not be verified"
        >
          Showing cached policies from server.
        </Notice>
      )}

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "1fr",
          gap: "var(--space-6)",
        }}
      >
        {/* Resource Protection Policy */}
        <SectionCard title="Automatic Resource Protection">
          {rpState.status === "loading" || !rpSettings ? (
            <SkeletonTable rows={4} columns={2} />
          ) : rpState.status === "error" && !rpSettings ? (
            <ErrorState
              title="Unable to load resource protection settings"
              message={rpState.error.message}
              onRetry={refetchRp}
            />
          ) : rpSettings ? (
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr ",
                gap: "var(--space-4)",
              }}
            >
              <p className="section-description">
                Clients autonomously terminate runaway processes when CPU or
                Memory exceeds sustained thresholds.
              </p>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(auto-fit, minmax(240px, 1fr))",
                  gap: "var(--space-4)",
                }}
              >
                {/* CPU Protection Box */}
                <div className="input_container">
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "var(--space-2)",
                    }}
                  >
                    <span
                      style={{ fontWeight: 600, fontSize: "var(--font-sm)" }}
                    >
                      CPU Protection
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setRpSettings({
                          ...rpSettings,
                          cpu: {
                            ...rpSettings.cpu,
                            enabled: !rpSettings.cpu.enabled,
                          },
                        })
                      }
                      disabled={!rpSettings.enabled}
                      style={{
                        fontSize: "var(--font-xs)",
                        border: rpSettings.cpu.enabled
                          ? "1px solid transparent"
                          : "1px solid var(--border-subtle)",
                        padding: "2px 6px",
                        borderRadius: "var(--radius-sm)",
                        background: rpSettings.cpu.enabled
                          ? "var(--success-bg)"
                          : "var(--surface-card)",
                        color: rpSettings.cpu.enabled
                          ? "var(--success)"
                          : "var(--text-muted)",
                        cursor: !rpSettings.enabled ? "not-allowed" : "pointer",
                        opacity: !rpSettings.enabled ? 0.6 : 1,
                      }}
                    >
                      {rpSettings.cpu.enabled ? "Enabled" : "Disabled"}
                    </button>
                  </div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr",
                      gap: "var(--space-3)",
                    }}
                  >
                    <NumberInput
                      id="cpu-threshold"
                      label={`Threshold (${rpSettings.cpu.threshold}%)`}
                      min={10}
                      max={100}
                      step={1}
                      value={rpSettings.cpu.threshold}
                      onChange={(value) =>
                        setRpSettings({
                          ...rpSettings,
                          cpu: {
                            ...rpSettings.cpu,
                            threshold: value,
                          },
                        })
                      }
                      disabled={!rpSettings.enabled || !rpSettings.cpu.enabled}
                    />
                    <NumberInput
                      id="cpu-sustained"
                      label="Sustained (seconds)"
                      min={1}
                      max={3600}
                      step={1}
                      value={rpSettings.cpu.sustained_seconds}
                      onChange={(value) =>
                        setRpSettings({
                          ...rpSettings,
                          cpu: {
                            ...rpSettings.cpu,
                            sustained_seconds: value,
                          },
                        })
                      }
                      disabled={!rpSettings.enabled || !rpSettings.cpu.enabled}
                    />
                  </div>
                </div>

                {/* Memory Protection Box */}
                <div className="input_container">
                  <div
                    style={{
                      display: "flex",
                      justifyContent: "space-between",
                      alignItems: "center",
                      marginBottom: "var(--space-2)",
                    }}
                  >
                    <span
                      style={{ fontWeight: 600, fontSize: "var(--font-sm)" }}
                    >
                      Memory Protection
                    </span>
                    <button
                      type="button"
                      onClick={() =>
                        setRpSettings({
                          ...rpSettings,
                          memory: {
                            ...rpSettings.memory,
                            enabled: !rpSettings.memory.enabled,
                          },
                        })
                      }
                      disabled={!rpSettings.enabled}
                      style={{
                        fontSize: "var(--font-xs)",
                        border: rpSettings.memory.enabled
                          ? "1px solid transparent"
                          : "1px solid var(--border-subtle)",
                        padding: "2px 6px",
                        borderRadius: "var(--radius-sm)",
                        background: rpSettings.memory.enabled
                          ? "var(--success-bg)"
                          : "var(--surface-card)",
                        color: rpSettings.memory.enabled
                          ? "var(--success)"
                          : "var(--text-muted)",
                        cursor: !rpSettings.enabled ? "not-allowed" : "pointer",
                        opacity: !rpSettings.enabled ? 0.6 : 1,
                      }}
                    >
                      {rpSettings.memory.enabled ? "Enabled" : "Disabled"}
                    </button>
                  </div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr",
                      gap: "var(--space-3)",
                    }}
                  >
                    <NumberInput
                      id="memory-threshold"
                      label={`Threshold (${rpSettings.memory.threshold}%)`}
                      min={10}
                      max={100}
                      step={1}
                      value={rpSettings.memory.threshold}
                      onChange={(value) =>
                        setRpSettings({
                          ...rpSettings,
                          memory: {
                            ...rpSettings.memory,
                            threshold: value,
                          },
                        })
                      }
                      disabled={
                        !rpSettings.enabled || !rpSettings.memory.enabled
                      }
                    />
                    <NumberInput
                      id="memory-sustained"
                      label="Sustained (seconds)"
                      min={1}
                      max={3600}
                      step={1}
                      value={rpSettings.memory.sustained_seconds}
                      onChange={(value) =>
                        setRpSettings({
                          ...rpSettings,
                          memory: {
                            ...rpSettings.memory,
                            sustained_seconds: value,
                          },
                        })
                      }
                      disabled={
                        !rpSettings.enabled || !rpSettings.memory.enabled
                      }
                    />
                  </div>
                </div>

                {/* Safety & Limits */}
                <div className="input_container">
                  <div
                    style={{
                      fontWeight: 600,
                      fontSize: "var(--font-sm)",
                      marginBottom: "var(--space-2)",
                    }}
                  >
                    Safety & Cooldown Limits
                  </div>
                  <div
                    style={{
                      display: "grid",
                      gridTemplateColumns: "1fr",
                      gap: "var(--space-3)",
                    }}
                  >
                    <NumberInput
                      id="cooldown-seconds"
                      label="Cooldown (seconds)"
                      min={0}
                      max={86400}
                      step={1}
                      value={rpSettings.cooldown_seconds}
                      onChange={(value) =>
                        setRpSettings({
                          ...rpSettings,
                          cooldown_seconds: value,
                        })
                      }
                      disabled={!rpSettings.enabled}
                    />
                    <NumberInput
                      id="max-interventions"
                      label="Max Interventions / Hour"
                      min={1}
                      max={100}
                      step={1}
                      value={rpSettings.max_interventions_per_hour}
                      onChange={(value) =>
                        setRpSettings({
                          ...rpSettings,
                          max_interventions_per_hour: value,
                        })
                      }
                      disabled={!rpSettings.enabled}
                    />
                  </div>
                </div>
              </div>
              {rpError && (
                <Notice variant="danger" title="Save failed">
                  {rpError}
                </Notice>
              )}
              {rpSuccess && (
                <Notice variant="success" title="Settings updated">
                  {rpSuccess}
                </Notice>
              )}

              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <Button
                  variant="primary"
                  loading={rpBusy}
                  onClick={saveResourceProtection}
                >
                  Save Resource Protection
                </Button>
              </div>
            </div>
          ) : null}
        </SectionCard>

        {/* Forbidden Processes */}
        <SectionCard title="Forbidden Process Rules">
          {fpState.status === "loading" || fpState.status === "idle" ? (
            <SkeletonTable rows={4} columns={3} />
          ) : fpState.status === "error" && !fpData ? (
            <ErrorState
              title="Unable to load process rules"
              message={fpState.error.message}
              onRetry={refetchFp}
            />
          ) : fpData ? (
            <div>
              <p
                style={{
                  fontSize: "var(--font-xs)",
                  color: "var(--text-muted)",
                  marginBottom: "var(--space-4)",
                }}
              >
                Managed clients autonomously detect and enforce forbidden
                processes and high-resource offenders.
              </p>

              {/* Search input */}
              <div style={{ marginBottom: "var(--space-3)" }}>
                <input
                  className="input_field"
                  aria-label="Filter processes"
                  placeholder="Filter processes by name or description..."
                  value={ruleSearch}
                  onChange={(e) => setRuleSearch(e.target.value)}
                  style={{ width: "100%" }}
                />
              </div>

              {/* Add form */}
              <div
                style={{
                  padding: "var(--space-3)",
                  borderRadius: "var(--radius-sm)",
                  border: "1px solid var(--border-subtle)",
                  marginBottom: "var(--space-4)",
                }}
              >
                <div
                  style={{
                    fontWeight: 600,
                    fontSize: "var(--font-sm)",
                    marginBottom: "var(--space-2)",
                  }}
                >
                  + Add Forbidden Process Rule
                </div>
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1.2fr 0.8fr 1.5fr auto",
                    gap: "var(--space-2)",
                    marginBottom: "var(--space-2)",
                  }}
                >
                  <input
                    className="input_field"
                    aria-label="Process name"
                    placeholder="process.exe"
                    value={newProcessName}
                    onChange={(event) => setNewProcessName(event.target.value)}
                  />
                  <select
                    aria-label="Severity"
                    value={newSeverity}
                    onChange={(event) => setNewSeverity(event.target.value)}
                  >
                    {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((severity) => (
                      <option key={severity}>{severity}</option>
                    ))}
                  </select>
                  <input
                    className="input_field"
                    aria-label="Description"
                    placeholder="Description / Reason"
                    value={newDescription}
                    onChange={(event) => setNewDescription(event.target.value)}
                  />
                  <Button
                    size="sm"
                    variant="primary"
                    loading={ruleBusy}
                    onClick={addRule}
                  >
                    Add
                  </Button>
                </div>
                <div
                  style={{
                    display: "flex",
                    gap: "var(--space-4)",
                    marginTop: "var(--space-2)",
                  }}
                >
                  <label
                    style={{
                      fontSize: "var(--font-xs)",
                      color: "var(--text-muted)",
                      display: "flex",
                      alignItems: "center",
                      gap: "4px",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={newTerminateOnDetect}
                      onChange={(e) =>
                        setNewTerminateOnDetect(e.target.checked)
                      }
                    />
                    Terminate on detection
                  </label>
                  <label
                    style={{
                      fontSize: "var(--font-xs)",
                      color: "var(--text-muted)",
                      display: "flex",
                      alignItems: "center",
                      gap: "4px",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={newResourceProtectionEligible}
                      onChange={(e) =>
                        setNewResourceProtectionEligible(e.target.checked)
                      }
                    />
                    Resource protection kill candidate
                  </label>
                </div>
              </div>

              {ruleError && (
                <Notice variant="danger" title="Rule update failed">
                  {ruleError}
                </Notice>
              )}

              {/* Rules list */}
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "var(--space-3)",
                }}
              >
                {filteredRules.length === 0 ? (
                  <div
                    style={{
                      fontSize: "var(--font-xs)",
                      color: "var(--text-faint)",
                      padding: "var(--space-2)",
                    }}
                  >
                    {ruleSearch
                      ? "No matching forbidden processes."
                      : "No forbidden processes configured."}
                  </div>
                ) : (
                  filteredRules.map((item) => (
                    <div
                      key={item.process_name}
                      style={{
                        padding: "var(--space-3)",
                        borderRadius: "var(--radius-sm)",
                        border: "1px solid var(--border-subtle)",
                        background: "var(--surface-muted)",
                      }}
                    >
                      <div
                        style={{
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "center",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "var(--space-2)",
                          }}
                        >
                          <span
                            style={{
                              fontWeight: 600,
                              fontFamily: "var(--font-mono)",
                            }}
                          >
                            {item.process_name}
                          </span>
                          <SeverityBadge
                            severity={item.severity as AlertSeverity}
                          />
                        </div>
                        <div
                          style={{
                            display: "flex",
                            gap: "var(--space-2)",
                            alignItems: "center",
                          }}
                        >
                          <button
                            type="button"
                            disabled={ruleBusy}
                            onClick={() =>
                              updateRule(item, {
                                enabled: !item.enabled,
                              })
                            }
                            style={{
                              fontSize: "var(--font-xs)",
                              border: item.enabled
                                ? "1px solid transparent"
                                : "1px solid var(--border-subtle)",
                              padding: "2px 6px",
                              borderRadius: "var(--radius-sm)",
                              background: item.enabled
                                ? "var(--success-bg)"
                                : "var(--surface-card)",
                              color: item.enabled
                                ? "var(--success)"
                                : "var(--text-muted)",
                              cursor: ruleBusy ? "not-allowed" : "pointer",
                              opacity: ruleBusy ? 0.6 : 1,
                            }}
                          >
                            {item.enabled ? "Enabled" : "Disabled"}
                          </button>
                          <Button
                            size="sm"
                            variant="danger"
                            disabled={ruleBusy}
                            onClick={() => deleteRule(item.process_name)}
                          >
                            Delete
                          </Button>
                        </div>
                      </div>
                      <div
                        style={{
                          display: "flex",
                          gap: "var(--space-4)",
                          marginTop: "var(--space-2)",
                        }}
                      >
                        <label
                          style={{
                            fontSize: "var(--font-xs)",
                            color: "var(--text-muted)",
                            display: "flex",
                            alignItems: "center",
                            gap: "4px",
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={item.terminate_on_detection ?? true}
                            disabled={ruleBusy}
                            onChange={(e) =>
                              updateRule(item, {
                                terminate_on_detection: e.target.checked,
                              })
                            }
                          />
                          Terminate on detection
                        </label>
                        <label
                          style={{
                            fontSize: "var(--font-xs)",
                            color: "var(--text-muted)",
                            display: "flex",
                            alignItems: "center",
                            gap: "4px",
                          }}
                        >
                          <input
                            type="checkbox"
                            checked={item.resource_protection_eligible ?? true}
                            disabled={ruleBusy}
                            onChange={(e) =>
                              updateRule(item, {
                                resource_protection_eligible: e.target.checked,
                              })
                            }
                          />
                          Resource kill candidate
                        </label>
                      </div>
                      {item.description && (
                        <div
                          style={{
                            fontSize: "var(--font-xs)",
                            color: "var(--text-muted)",
                            marginTop: "var(--space-1)",
                          }}
                        >
                          {item.description}
                        </div>
                      )}
                    </div>
                  ))
                )}
              </div>
            </div>
          ) : null}
        </SectionCard>

        {/* Working Hours Policy */}
        <SectionCard title="Working Hours Policy">
          {whState.status === "loading" || whState.status === "idle" ? (
            <SkeletonTable rows={5} columns={3} />
          ) : whState.status === "error" && !whData ? (
            <ErrorState
              title="Unable to load working hours"
              message={whState.error.message}
              onRetry={refetchWh}
            />
          ) : whData ? (
            <div>
              <div
                style={{
                  padding: "var(--space-3)",
                  borderRadius: "var(--radius-sm)",
                  background: whData.current_status.within_working_hours
                    ? "var(--success-bg)"
                    : "var(--warning-bg)",
                  color: whData.current_status.within_working_hours
                    ? "var(--success)"
                    : "var(--warning)",
                  fontSize: "var(--font-xs)",
                  fontWeight: 600,
                  marginBottom: "var(--space-4)",
                }}
              >
                Current status:{" "}
                {whData.current_status.within_working_hours
                  ? "Within Working Hours"
                  : "Outside Working Hours"}{" "}
                · Verified at {formatDateTime(whData.current_status.checked_at)}
              </div>

              <table
                style={{
                  width: "100%",
                  borderCollapse: "collapse",
                  fontSize: "var(--font-sm)",
                }}
              >
                <thead>
                  <tr
                    style={{
                      borderBottom: "1px solid var(--border)",
                      textAlign: "left",
                    }}
                  >
                    <th
                      style={{
                        padding: "var(--space-2) 0",
                        color: "var(--text-muted)",
                      }}
                    >
                      Day
                    </th>
                    <th
                      style={{
                        padding: "var(--space-2) 0",
                        color: "var(--text-muted)",
                      }}
                    >
                      Schedule
                    </th>
                    <th
                      style={{
                        padding: "var(--space-2) 0",
                        color: "var(--text-muted)",
                        textAlign: "right",
                      }}
                    >
                      Status
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {whData.rules.map((r) => (
                    <tr
                      key={r.day_of_week}
                      style={{ borderBottom: "1px solid var(--border-subtle)" }}
                    >
                      <td
                        style={{ padding: "var(--space-2) 0", fontWeight: 500 }}
                      >
                        {DAY_NAMES[r.day_of_week] ?? `Day ${r.day_of_week}`}
                      </td>
                      <td
                        style={{
                          padding: "var(--space-2) 0",
                          fontFamily: "var(--font-mono)",
                          fontSize: "var(--font-xs)",
                        }}
                      >
                        {r.start_time} – {r.end_time}
                      </td>
                      <td
                        style={{
                          padding: "var(--space-2) 0",
                          textAlign: "right",
                        }}
                      >
                        <span
                          style={{
                            fontSize: "var(--font-xs)",
                            color: r.enabled
                              ? "var(--success)"
                              : "var(--text-faint)",
                          }}
                        >
                          {r.enabled ? "Active" : "Disabled"}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </SectionCard>
      </div>
    </div>
  );
}
