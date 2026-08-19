/**
 * Toast Notification Context and Hook.
 * Allows triggering structured toast alerts anywhere in the application.
 */

import React, { createContext, useCallback, useContext, useState } from 'react';
import '../styles/toast.css';

export type ToastSeverity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO' | 'SUCCESS';

export interface ToastItem {
  id: string;
  title: string;
  message?: string;
  severity?: ToastSeverity;
  duration?: number; // Milliseconds, default 6000
  action?: {
    label: string;
    onClick: () => void;
  };
  createdAt: Date;
}

interface ToastContextValue {
  toasts: ToastItem[];
  addToast: (toast: Omit<ToastItem, 'id' | 'createdAt'>) => string;
  dismissToast: (id: string) => void;
}

const ToastContext = createContext<ToastContextValue>({
  toasts: [],
  addToast: () => '',
  dismissToast: () => {},
});
import { FiCheckCircle } from "react-icons/fi";
import { GoBell } from "react-icons/go";
import { BsInfoCircle } from 'react-icons/bs';
import { IoAlertOutline } from 'react-icons/io5';
import { RxCross1 } from 'react-icons/rx';

const SEVERITY_ICONS: Record<ToastSeverity, string> = {
  CRITICAL: <RxCross1 />as unknown as string,
  HIGH: <IoAlertOutline /> as unknown as string,
  MEDIUM: '⚡',
  LOW: (<BsInfoCircle style={{ color: 'var(--info)' }} />) as unknown as string,
  INFO: (<GoBell style={{ color: 'var(--info)' }} />) as unknown as string,
  SUCCESS: (<FiCheckCircle style={{ color: 'var(--success)' }} />) as unknown as string,
};

export function ToastProvider({ children }: { children: React.ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const dismissToast = useCallback((id: string) => {
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const addToast = useCallback(
    (toast: Omit<ToastItem, 'id' | 'createdAt'>) => {
      const id = Math.random().toString(36).substring(2, 9);
      const newItem: ToastItem = {
        ...toast,
        id,
        severity: toast.severity || 'INFO',
        duration: toast.duration ?? (toast.severity === 'CRITICAL' ? 10000 : 6000),
        createdAt: new Date(),
      };

      setToasts((prev) => [newItem, ...prev.slice(0, 5)]); // Keep max 6 toasts visible

      if (newItem.duration && newItem.duration > 0) {
        setTimeout(() => {
          dismissToast(id);
        }, newItem.duration);
      }

      return id;
    },
    [dismissToast],
  );

  return (
    <ToastContext.Provider value={{ toasts, addToast, dismissToast }}>
      {children}
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}

function ToastContainer({
  toasts,
  onDismiss,
}: {
  toasts: ToastItem[];
  onDismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;

  return (
    <div className="toast-container" role="region" aria-label="Notifications" aria-live="polite">
      {toasts.map((toast) => {
        const severityKey = (toast.severity || 'INFO').toLowerCase();
        const icon = SEVERITY_ICONS[toast.severity || 'INFO'] || (<GoBell style={{ color: 'var(--info)' }} />) as unknown as string;

        return (
          <div key={toast.id} className={`toast toast--${severityKey}`} role="status">
            <div className="toast__header">
              <span className="toast__icon" aria-hidden="true">
                {icon}
              </span>
              <span className="toast__title">{toast.title}</span>
              <span className="toast__time">Just now</span>
              <button
                className="toast__close"
                onClick={() => onDismiss(toast.id)}
                aria-label="Dismiss notification"
              >
                ×
              </button>
            </div>
            {toast.message && <div className="toast__body">{toast.message}</div>}
            {toast.action && (
              <div style={{ padding: '0 var(--space-4) var(--space-3) var(--space-4)' }}>
                <span
                  className="toast__action"
                  onClick={() => {
                    toast.action?.onClick();
                    onDismiss(toast.id);
                  }}
                  role="button"
                  tabIndex={0}
                >
                  {toast.action.label}
                </span>
              </div>
            )}
            {toast.duration && toast.duration > 0 && (
              <div
                className="toast__progress"
                style={{ animationDuration: `${toast.duration}ms` }}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
