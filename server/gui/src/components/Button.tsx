import '../styles/button.css';

type ButtonVariant = 'primary' | 'secondary' | 'quiet' | 'danger';
type ButtonSize    = 'sm' | 'md' | 'lg';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  iconOnly?: boolean;
  loading?: boolean;
}

export function Button({
  variant = 'secondary',
  size = 'md',
  iconOnly = false,
  loading = false,
  disabled,
  children,
  className = '',
  ...rest
}: ButtonProps) {
  const cls = [
    'btn',
    `btn--${variant}`,
    size !== 'md' ? `btn--${size}` : '',
    iconOnly ? 'btn--icon' : '',
    className,
  ].filter(Boolean).join(' ');

  return (
    <button
      className={cls}
      disabled={disabled || loading}
      aria-disabled={disabled || loading}
      {...rest}
    >
      {loading ? <LoadingSpinner size="sm" /> : children}
    </button>
  );
}

// Inline tiny spinner used by Button and other components
export function LoadingSpinner({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
  const px = size === 'sm' ? 14 : size === 'lg' ? 24 : 18;
  return (
    <svg
      width={px}
      height={px}
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      style={{ flexShrink: 0 }}
    >
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        .spinner-ring { animation: spin 0.8s linear infinite; transform-origin: center; }
      `}</style>
      <circle
        className="spinner-ring"
        cx="12" cy="12" r="9"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
        strokeDasharray="40 20"
      />
    </svg>
  );
}
