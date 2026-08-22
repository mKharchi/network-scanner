/**
 * Shared formatting utilities used across pages.
 */

/** Format an ISO-8601 timestamp to a human-readable local date+time. */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Intl.DateTimeFormat(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

/** Format an ISO-8601 timestamp as a relative "X ago" string. */
export function formatRelative(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const seconds = Math.floor(diff / 1000);
    if (seconds < 60)      return `${seconds}s ago`;
    if (seconds < 3600)    return `${Math.floor(seconds / 60)}m ago`;
    if (seconds < 86400)   return `${Math.floor(seconds / 3600)}h ago`;
    if (seconds < 604800)  return `${Math.floor(seconds / 86400)}d ago`;
    return formatDateTime(iso);
  } catch {
    return iso ?? '—';
  }
}

/** Format a date-only string (YYYY-MM-DD). */
export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—';
  try {
    return new Intl.DateTimeFormat(undefined, { dateStyle: 'medium' }).format(new Date(iso + 'T00:00:00'));
  } catch {
    return iso;
  }
}

/** Truncate a hostname to N characters. */
export function truncate(s: string | null | undefined, max = 30): string {
  if (!s) return '—';
  return s.length > max ? s.slice(0, max) + '…' : s;
}

/** Format a MAC address to canonical uppercase colon-separated form. */
export function normalizeMac(mac: string | null | undefined): string {
  if (!mac) return '—';
  return mac.toUpperCase().replace(/-/g, ':');
}

/** Day-of-week name from Python's weekday (0 = Monday). */
export const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
