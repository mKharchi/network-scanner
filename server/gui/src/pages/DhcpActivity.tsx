import { useState } from "react";
import { api } from "../api/client";
import { useFetch } from "../hooks/useFetch";
import { Button } from "../components/Button";
import { DataTable, type Column } from "../components/DataTable";
import {
  SkeletonTable,
  ErrorState,
  EmptyState,
  Notice,
} from "../components/States";
import { formatDateTime, normalizeMac } from "../utils/format";

interface DhcpObservationItem {
  received_at: string;
  reporting_client_mac: string;
  neighbours: unknown[];
  dhcp: {
    message_type: number;
    vendor_class: string | null;
    client_id: string | null;
  };
}

const DHCP_MESSAGE_NAMES: Record<number, string> = {
  1: "DISCOVER",
  2: "OFFER",
  3: "REQUEST",
  4: "DECLINE",
  5: "ACK",
  6: "NAK",
  7: "RELEASE",
  8: "INFORM",
};

export function DhcpActivityPage() {
  const todayStr = new Date().toISOString().split("T")[0];
  const [date, setDate] = useState(todayStr);
  const [reporterMac, setReporterMac] = useState("");

  const { state, refetch } = useFetch(
    () =>
      api.getDhcp({
        date: date || undefined,
        reporter_mac: reporterMac || undefined,
      }),
    [date, reporterMac],
    ['app:dhcp_update', 'dhcp_update'],
  );

  const items: DhcpObservationItem[] =
    state.status === 'success'
      ? state.data.items
      : state.status === 'error' && state.staleData
        ? state.staleData.items
        : [];

  const columns: Column<DhcpObservationItem>[] = [
    {
      key: "received_at",
      label: "Received At",
      render: (item) => (
        <span style={{ fontWeight: 500 }}>
          {formatDateTime(item.received_at)}
        </span>
      ),
    },
    {
      key: "dhcp_message_type",
      label: "DHCP Type",
      render: (item) => {
        const typeName =
          DHCP_MESSAGE_NAMES[item.dhcp.message_type] ||
          `Type ${item.dhcp.message_type}`;
        return (
          <span
            style={{
              display: "inline-block",
              padding: "2px 8px",
              borderRadius: "var(--radius-sm)",
              background: "var(--surface-muted)",
              fontSize: "var(--font-xs)",
              fontWeight: 600,
              fontFamily: "var(--font-mono)",
            }}
          >
            {typeName}
          </span>
        );
      },
    },
    {
      key: "reporting_client_mac",
      label: "Reporter MAC",
      mono: true,
      render: (item) => normalizeMac(item.reporting_client_mac),
    },
    {
      key: "vendor_class",
      label: "Vendor Class",
      render: (item) => item.dhcp.vendor_class ?? null,
    },
    {
      key: "client_id",
      label: "Client ID",
      mono: true,
      render: (item) => item.dhcp.client_id ?? null,
    },
  ];

  return (
    <div>
      <div className="page-header">
        <div>
          <h1 className="page-title">DHCP Activity</h1>
          <p className="page-description">
            Passive DHCP traffic observed by active monitoring agents.
          </p>
        </div>
        <Button variant="quiet" size="sm" onClick={refetch}>
          Refresh
        </Button>
      </div>

      {state.status === "error" && (
        <Notice variant="warning" title="DHCP audit records unavailable">
          {state.error.message}
        </Notice>
      )}

      {/* Date & Reporter Filter */}
      <div
        style={{
          display: "flex",
          gap: "var(--space-3)",
          marginBottom: "var(--space-5)",
          alignItems: "center",
          flexWrap: "wrap",
        }}
      >
        <label
          style={{ fontSize: "var(--font-sm)", color: "var(--text-muted)" }}
        >
          Date:
          <input
            type="date"
            value={date}
            onChange={(e) => setDate(e.target.value)}
            style={{
              marginLeft: "var(--space-2)",
              padding: "0 var(--space-2)",
              height: 36,
              border: "1px solid var(--border)",
              borderRadius: "var(--radius)",
              fontFamily: "var(--font-sans)",
              background: "var(--surface)",
              color: "var(--text)",
            }}
          />
        </label>
        <input
          type="search"
          placeholder="Filter by reporter MAC…"
          value={reporterMac}
          onChange={(e) => setReporterMac(e.target.value)}
          style={{
            padding: "0 var(--space-3)",
            height: 36,
            border: "1px solid var(--border)",
            borderRadius: "var(--radius)",
            fontFamily: "var(--font-sans)",
            fontSize: "var(--font-sm)",
            background: "var(--surface)",
            color: "var(--text)",
            minWidth: 220,
          }}
        />
      </div>

      {state.status === "idle" || state.status === "loading" ? (
        <SkeletonTable rows={6} columns={5} />
      ) : state.status === "error" && !state.staleData ? (
        <ErrorState
          title="Unable to load DHCP observations"
          message={state.error.message}
          onRetry={refetch}
        />
      ) : items.length === 0 ? (
        <EmptyState
          icon="📡"
          title="No DHCP observations for this date"
          body="No broadcast DHCP packets were captured by any monitoring agents on the chosen date."
        />
      ) : (
        <DataTable
          columns={columns}
          data={items}
          rowKey={(item, idx) =>
            `${item.received_at}-${item.reporting_client_mac}-${idx}`
          }
          aria-label="DHCP activity observations"
        />
      )}
    </div>
  );
}
