import '../styles/card.css';

// ── MetricCard ───────────────────────────────────────────────────
interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  context?: React.ReactNode;
  valueVariant?: 'default' | 'success' | 'warning' | 'danger' | 'info';
  children?: React.ReactNode;
}

export function MetricCard({
  label,
  value,
  context,
  valueVariant = 'default',
  children,
}: MetricCardProps) {
  return (
    <div className="metric-card">
      <span className="metric-card__label">{label}</span>
      <span
        className={[
          'metric-card__value',
          valueVariant !== 'default' ? `metric-card__value--${valueVariant}` : '',
        ].filter(Boolean).join(' ')}
      >
        {value}
      </span>
      {context && <span className="metric-card__context">{context}</span>}
      {children}
    </div>
  );
}

// ── SectionCard ──────────────────────────────────────────────────
interface SectionCardProps {
  title?: string;
  headerAction?: React.ReactNode;
  children: React.ReactNode;
  flush?: boolean;
  className?: string;
}

export function SectionCard({
  title,
  headerAction,
  children,
  flush = false,
  className = '',
}: SectionCardProps) {
  return (
    <div className={`section-card ${className}`}>
      {title && (
        <div className="section-card__header">
          <h2 className="section-card__title">{title}</h2>
          {headerAction}
        </div>
      )}
      <div className={`section-card__body${flush ? ' section-card__body--flush' : ''}`}>
        {children}
      </div>
    </div>
  );
}

// ── Plain Card ───────────────────────────────────────────────────
interface CardProps {
  children: React.ReactNode;
  className?: string;
}

export function Card({ children, className = '' }: CardProps) {
  return (
    <div className={`card ${className}`}>
      {children}
    </div>
  );
}
