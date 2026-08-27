/**
 * Pure helper checks for AUTO/MANUAL station markers.
 * Mirrors server/gui/src/utils/stationAssignment.ts for CI without a TS runner.
 */

function assignmentMethodOf(assignment) {
  const method = assignment?.method;
  if (method === "AUTO" || method === "MANUAL") return method;
  return null;
}

function formatAssignmentConfidence(confidence) {
  if (typeof confidence !== "number" || Number.isNaN(confidence)) return null;
  return `${Math.round(confidence * 100)}%`;
}

function stationAssignmentMeta(assignment) {
  const method = assignmentMethodOf(assignment);
  if (!method) return null;
  const confidence = formatAssignmentConfidence(assignment?.confidence ?? null);
  if (method === "AUTO" && confidence) return `${method} ${confidence}`;
  return method;
}

function assertEqual(actual, expected, label) {
  if (actual !== expected) {
    throw new Error(`${label}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

assertEqual(assignmentMethodOf({ method: "AUTO" }), "AUTO", "auto method");
assertEqual(assignmentMethodOf({ method: "MANUAL" }), "MANUAL", "manual method");
assertEqual(assignmentMethodOf({ method: null }), null, "null method");
assertEqual(formatAssignmentConfidence(0.91), "91%", "confidence");
assertEqual(
  stationAssignmentMeta({ method: "AUTO", confidence: 0.91 }),
  "AUTO 91%",
  "auto meta",
);
assertEqual(
  stationAssignmentMeta({ method: "MANUAL", confidence: null }),
  "MANUAL",
  "manual meta",
);

console.log("stationAssignment helpers OK");
