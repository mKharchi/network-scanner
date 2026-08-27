import type { ClientLocation, LocationAssignment } from "../api/client";

export type AssignmentMethodMarker = "AUTO" | "MANUAL";

/** Plan: AUTO ● / MANUAL ◆ / empty ○ — do not rely on color alone. */
export const ASSIGNMENT_METHOD_GLYPH: Record<AssignmentMethodMarker | "EMPTY", string> = {
  AUTO: "●",
  MANUAL: "◆",
  EMPTY: "○",
};

export function resolveLocationAssignment(
  station?: ClientLocation | null,
  fallback?: LocationAssignment | null,
): LocationAssignment | null {
  return station?.assignment ?? fallback ?? null;
}

export function assignmentMethodOf(
  assignment: LocationAssignment | null | undefined,
): AssignmentMethodMarker | null {
  const method = assignment?.method;
  if (method === "AUTO" || method === "MANUAL") return method;
  return null;
}

export function formatAssignmentConfidence(
  confidence: number | null | undefined,
): string | null {
  if (typeof confidence !== "number" || Number.isNaN(confidence)) return null;
  return `${Math.round(confidence * 100)}%`;
}

export function stationAssignmentMeta(
  assignment: LocationAssignment | null | undefined,
): string | null {
  const method = assignmentMethodOf(assignment);
  if (!method) return null;
  const confidence = formatAssignmentConfidence(assignment?.confidence ?? null);
  if (method === "AUTO" && confidence) return `${method} ${confidence}`;
  return method;
}

export function stationAssignmentTitle(
  station: ClientLocation,
  healthLabel: string,
): string {
  const assignment = resolveLocationAssignment(station);
  const method = assignmentMethodOf(assignment);
  const parts = [station.label, healthLabel];
  if (station.hostname || station.client_id) {
    parts.push(station.hostname || station.client_id || "");
  }
  if (method) {
    parts.push(method);
    const confidence = formatAssignmentConfidence(assignment?.confidence ?? null);
    if (confidence) parts.push(`Confidence ${confidence}`);
  }
  return parts.filter(Boolean).join(" · ");
}
