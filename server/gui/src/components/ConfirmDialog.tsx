import { useEffect, useId, useRef } from "react";
import { Button } from "./Button";
import "../styles/confirm-dialog.css";

interface ConfirmDialogProps {
  open: boolean;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  danger?: boolean;
  inputLabel?: string;
  inputValue?: string;
  inputPlaceholder?: string;
  onInputChange?: (value: string) => void;
  onConfirm: () => void;
  onCancel: () => void;
}

export function ConfirmDialog({
  open,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  danger = false,
  inputLabel,
  inputValue,
  inputPlaceholder,
  onInputChange,
  onConfirm,
  onCancel,
}: ConfirmDialogProps) {
  const confirmRef = useRef<HTMLButtonElement | null>(null);
  const titleId = useId();
  const descriptionId = useId();

  useEffect(() => {
    if (!open) return;
    const previouslyFocused = document.activeElement as HTMLElement | null;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKeyDown);
    window.setTimeout(() => confirmRef.current?.focus(), 0);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      previouslyFocused?.focus();
    };
  }, [open, onCancel]);

  if (!open) return null;

  return (
    <div className="confirm-dialog__backdrop" onMouseDown={onCancel}>
      <section
        className="confirm-dialog"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <h2 id={titleId} className="confirm-dialog__title">{title}</h2>
        <p id={descriptionId} className="confirm-dialog__description">{description}</p>
        {inputLabel && onInputChange && (
          <label style={{ display: "grid", gap: "var(--space-1)", marginTop: "var(--space-3)" }}>
            <span style={{ fontSize: "var(--font-xs)", color: "var(--text-muted)" }}>{inputLabel}</span>
            <input
              type="text"
              value={inputValue ?? ""}
              placeholder={inputPlaceholder}
              onChange={(event) => onInputChange(event.target.value)}
              autoFocus
              style={{
                width: "100%",
                boxSizing: "border-box",
                background: "var(--surface)",
                color: "var(--text)",
                border: "1px solid var(--border)",
                borderRadius: "var(--radius-sm)",
                padding: "var(--space-2)",
              }}
            />
          </label>
        )}
        <div className="confirm-dialog__actions">
          <Button variant="secondary" onClick={onCancel}>{cancelLabel}</Button>
          <button
            ref={confirmRef}
            className={`btn btn--${danger ? "danger" : "primary"}`}
            onClick={onConfirm}
          >
            {confirmLabel}
          </button>
        </div>
      </section>
    </div>
  );
}
