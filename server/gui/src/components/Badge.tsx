import '../styles/badge.css';

// ── Badge ────────────────────────────────────────────────────────
export type BadgeVariant =
  | 'success' | 'warning' | 'danger' | 'info' | 'muted' | 'primary' | 'critical';

interface BadgeProps {
  variant: BadgeVariant;
  children: React.ReactNode;
  dot?: boolean;
  className?: string;
}

export function Badge({ variant, children, dot = false, className = '' }: BadgeProps) {
  return (
    <span className={`badge badge--${variant} ${className}`}>
      {dot && <span className="badge__dot" aria-hidden="true" />}
      {children}
    </span>
  );
}

// ── Convenience badges ───────────────────────────────────────────

export function OnlineBadge() {
  return <Badge variant="success" dot>Online</Badge>;
}

export function OfflineBadge() {
  return <Badge variant="muted" dot>Offline</Badge>;
}

export function StaleBadge() {
  return <Badge variant="warning" dot>Stale</Badge>;
}

export type AlertSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL';
export type AlertStatus   = 'NEW' | 'ACKNOWLEDGED' | 'RESOLVED';

const SEVERITY_VARIANT: Record<AlertSeverity, BadgeVariant> = {
  LOW:      'info',
  MEDIUM:   'warning',
  HIGH:     'danger',
  CRITICAL: 'critical',
};

export function SeverityBadge({ severity }: { severity: AlertSeverity }) {
  const label = severity.charAt(0) + severity.slice(1).toLowerCase();
  return <Badge variant={SEVERITY_VARIANT[severity]}>{label}</Badge>;
}

const STATUS_VARIANT: Record<AlertStatus, BadgeVariant> = {
  NEW:          'danger',
  ACKNOWLEDGED: 'warning',
  RESOLVED:     'success',
};

export function StatusBadge({ status }: { status: AlertStatus }) {
  const label = status.charAt(0) + status.slice(1).toLowerCase();
  return <Badge variant={STATUS_VARIANT[status]}>{label}</Badge>;
}

export function ClassificationBadge({ managed }: { managed: boolean }) {
  return managed
    ? <Badge variant="primary">Managed</Badge>
    : <Badge variant="muted">Unmanaged</Badge>;
}
