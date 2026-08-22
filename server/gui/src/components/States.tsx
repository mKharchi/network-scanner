
import '../styles/states.css';
import { Button } from './Button';

// ── Skeleton ─────────────────────────────────────────────────────
type SkeletonVariant =
  | 'text' | 'text-sm' | 'text-lg' | 'title' | 'badge' | 'icon' | 'row';

interface SkeletonProps {
  variant?: SkeletonVariant;
  width?: string;
  height?: string;
  className?: string;
  style?: React.CSSProperties;
}

export function Skeleton({
  variant = 'text',
  width,
  height,
  className = '',
  style,
}: SkeletonProps) {
  return (
    <span
      className={`skeleton skeleton--${variant} ${className}`}
      aria-hidden="true"
      style={{ width, height, ...style }}
    />
  );
}

interface SkeletonRowsProps {
  rows?: number;
  columns?: number;
}

export function SkeletonTable({ rows = 5, columns = 4 }: SkeletonRowsProps) {
  return (
    <div className="data-table-wrap">
      <table className="data-table" aria-hidden="true">
        <thead>
          <tr>
            {Array.from({ length: columns }).map((_, i) => (
              <th key={i}>
                <Skeleton variant="text-sm" width="5rem" />
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rows }).map((_, r) => (
            <tr key={r}>
              {Array.from({ length: columns }).map((_, c) => (
                <td key={c}>
                  <Skeleton
                    variant="text"
                    width={c === 0 ? '8rem' : c === columns - 1 ? '4rem' : '6rem'}
                  />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ── Empty state ───────────────────────────────────────────────────
interface EmptyStateProps {
  icon?: string;
  title: string;
  body?: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon = '📭', title, body, action }: EmptyStateProps) {
  return (
    <div className="empty-state" role="status">
      <div className="empty-state__icon" aria-hidden="true">{icon}</div>
      <p className="empty-state__title">{title}</p>
      {body && <p className="empty-state__body">{body}</p>}
      {action}
    </div>
  );
}

// ── Error state ───────────────────────────────────────────────────
interface ErrorStateProps {
  title?: string;
  message?: string;
  onRetry?: () => void;
}

export function ErrorState({
  title = 'Unable to load data',
  message,
  onRetry,
}: ErrorStateProps) {
  return (
    <div className="error-state" role="alert">
      <div className="error-state__icon" aria-hidden="true">⚠️</div>
      <p className="error-state__title">{title}</p>
      {message && <p className="error-state__body">{message}</p>}
      {onRetry && (
        <Button variant="secondary" onClick={onRetry}>
          Retry
        </Button>
      )}
    </div>
  );
}

// ── Inline notice ─────────────────────────────────────────────────
type NoticeVariant = 'info' | 'warning' | 'danger' | 'success';

interface NoticeProps {
  variant: NoticeVariant;
  title?: string;
  children: React.ReactNode;
  action?: React.ReactNode;
}

const NOTICE_ICONS: Record<NoticeVariant, string> = {
  info:    'ℹ️',
  warning: '⚠️',
  danger:  '🔴',
  success: '✅',
};

export function Notice({ variant, title, children, action }: NoticeProps) {
  return (
    <div className={`notice notice--${variant}`} role="status">
      <span className="notice__icon" aria-hidden="true">{NOTICE_ICONS[variant]}</span>
      <div className="notice__body">
        {title && <div className="notice__title">{title}</div>}
        <div className="notice__text">{children}</div>
      </div>
      {action}
    </div>
  );
}
