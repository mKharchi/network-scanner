import { useState, useEffect } from "react";
import { api, type DayStatusResult, type DayFinishResult } from "../api/client";
import { Button } from "./Button";
import { Notice } from "./States";
import { SectionCard } from "./Card";

export function FinishDayCard() {
  const todayUtc = new Date().toISOString().slice(0, 10);
  const [selectedDate, setSelectedDate] = useState(todayUtc);
  const [status, setStatus] = useState<DayStatusResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [finishing, setFinishing] = useState(false);
  const [finishResult, setFinishResult] = useState<DayFinishResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const fetchStatus = async (date: string) => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.getDayStatus(date);
      setStatus(data);
    } catch (err: any) {
      setError(err?.message || "Failed to load day status.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchStatus(selectedDate);
  }, [selectedDate]);

  const handleFinishDay = async () => {
    setFinishing(true);
    setError(null);
    setFinishResult(null);
    try {
      const result = await api.finishDay(selectedDate);
      setFinishResult(result);
      await fetchStatus(selectedDate);
    } catch (err: any) {
      setError(err?.message || "Failed to complete day.");
    } finally {
      setFinishing(false);
    }
  };

  return (
    <SectionCard title="Day-End Finalization & Cleanup">
      <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-4)" }}>
        <p className="section-description" style={{ margin: 0 }}>
          Finalizes all closed 10-minute ML observation intervals for the date, compiles daily identity summaries into the persistent SQLite store, and <strong>permanently deletes all temporary per-window JSONL prediction files</strong>.
        </p>

        {/* Date Selector & Action Bar */}
        <div style={{ display: "flex", alignItems: "center", gap: "var(--space-3)", flexWrap: "wrap" }}>
          <label style={{ fontSize: "var(--font-sm)", fontWeight: 600, color: "var(--text-secondary)" }}>
            UTC Date:
          </label>
          <input
            type="date"
            value={selectedDate}
            onChange={(e) => setSelectedDate(e.target.value)}
            style={{
              height: "2.25rem",
              padding: "0 var(--space-3)",
              border: "1px solid var(--border)",
              borderRadius: "var(--radius-sm)",
              background: "var(--surface-2)",
              color: "var(--text-primary)",
              fontFamily: "inherit",
              fontSize: "var(--font-sm)",
            }}
          />
          <Button
            variant="secondary"
            size="sm"
            onClick={() => fetchStatus(selectedDate)}
            disabled={loading || finishing}
          >
            Refresh Status
          </Button>

          <Button
            variant="primary"
            size="sm"
            loading={finishing}
            disabled={finishing || loading}
            onClick={handleFinishDay}
          >
            {finishing ? "Finalizing Day…" : "Complete Day & Clean JSONL"}
          </Button>
        </div>

        {/* Live Status Indicators */}
        {status && (
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(auto-fit, minmax(140px, 1fr))",
              gap: "var(--space-3)",
              padding: "var(--space-3)",
              background: "var(--surface-2)",
              borderRadius: "var(--radius-sm)",
              border: "1px solid var(--border)",
            }}
          >
            <div>
              <div style={{ fontSize: "var(--font-xs)", color: "var(--text-faint)", textTransform: "uppercase" }}>
                Summary Status
              </div>
              <div style={{ fontWeight: 700, fontSize: "var(--font-sm)", color: status.summary_status === "completed" ? "var(--success)" : "var(--accent)" }}>
                {status.summary_status.toUpperCase()}
              </div>
            </div>

            <div>
              <div style={{ fontSize: "var(--font-xs)", color: "var(--text-faint)", textTransform: "uppercase" }}>
                Identities Summarized
              </div>
              <div style={{ fontWeight: 700, fontSize: "var(--font-sm)", color: "var(--text-primary)" }}>
                {status.summaries_generated}
              </div>
            </div>

            <div>
              <div style={{ fontSize: "var(--font-xs)", color: "var(--text-faint)", textTransform: "uppercase" }}>
                Intervals Processed
              </div>
              <div style={{ fontWeight: 700, fontSize: "var(--font-sm)", color: "var(--text-primary)" }}>
                {status.intervals_completed} / {status.intervals_total}
              </div>
            </div>

            <div>
              <div style={{ fontSize: "var(--font-xs)", color: "var(--text-faint)", textTransform: "uppercase" }}>
                Total Windows
              </div>
              <div style={{ fontWeight: 700, fontSize: "var(--font-sm)", color: "var(--text-primary)" }}>
                {status.total_window_count}
              </div>
            </div>

            <div>
              <div style={{ fontSize: "var(--font-xs)", color: "var(--text-faint)", textTransform: "uppercase" }}>
                JSONL Files Cleaned
              </div>
              <div style={{ fontWeight: 700, fontSize: "var(--font-sm)", color: status.per_window_files_deleted ? "var(--success)" : "var(--text-secondary)" }}>
                {status.per_window_files_deleted ? "Yes (Deleted)" : "Not Deleted Yet"}
              </div>
            </div>
          </div>
        )}

        {/* Feedback messages */}
        {error && (
          <Notice variant="danger" title="Operation Failed">
            {error}
          </Notice>
        )}

        {finishResult && (
          <Notice variant="success" title={`Day ${finishResult.date_utc} Completed Successfully`}>
            <div>
              Daily summaries committed to SQLite: <strong>{finishResult.identities_count} identities</strong> across <strong>{finishResult.total_windows} observation windows</strong>.
            </div>
            <div style={{ marginTop: "4px", fontSize: "var(--font-xs)" }}>
              All per-window <code>.jsonl</code> files for {finishResult.date_utc} were deleted.
            </div>
          </Notice>
        )}
      </div>
    </SectionCard>
  );
}
