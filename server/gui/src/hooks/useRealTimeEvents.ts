/**
 * Global Real-Time SSE Stream Hook.
 * Connects to /api/v1/events, dispatches toasts, and updates UI state dynamically.
 */

import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useToast, type ToastSeverity } from './useToast';

const API_ORIGIN =
  import.meta.env.VITE_API_URL ||
  (typeof window !== 'undefined' && window.location.port === '8080'
    ? window.location.origin
    : 'http://127.0.0.1:8080');

export function useRealTimeEvents() {
  const { addToast } = useToast();
  const navigate = useNavigate();
  const [unreadAlerts, setUnreadAlerts] = useState(0);
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    const sseUrl = `${API_ORIGIN.replace(/\/+$/, '')}/api/v1/events`;
    console.log(`[SSE] Connecting to live event stream at ${sseUrl}...`);

    let es: EventSource | null = null;
    let reconnectTimeout: ReturnType<typeof setTimeout>;

    function connect() {
      try {
        es = new EventSource(sseUrl);
        esRef.current = es;

        es.onopen = () => {
          console.log('[SSE] Connected to backend live stream.');
        };

        // 1. Alert Event
        es.addEventListener('alert', (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data);
            console.log('[SSE Event: alert]', data);

            setUnreadAlerts((c) => c + 1);

            const severity: ToastSeverity =
              data.severity === 'CRITICAL' ||
              data.severity === 'HIGH' ||
              data.severity === 'MEDIUM' ||
              data.severity === 'LOW'
                ? data.severity
                : 'HIGH';

            addToast({
              title: data.title || 'New Alert Received',
              message: data.description || `Severity: ${data.severity}`,
              severity,
              action: data.id
                ? {
                    label: 'View Alert →',
                    onClick: () => navigate(`/alerts/${data.id}`),
                  }
                : undefined,
            });

            // Dispatch global event for active pages to reactively refetch
            window.dispatchEvent(new CustomEvent('app:alert', { detail: data }));
          } catch (err) {
            console.error('Error handling SSE alert event:', err);
          }
        });

        // 2. Client Status Event (Online/Offline)
        es.addEventListener('client_status', (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data);
            console.log('[SSE Event: client_status]', data);

            const isOnline = data.state === 'ONLINE';
            addToast({
              title: isOnline ? 'Client Connected' : 'Client Disconnected',
              message: `${data.hostname || data.mac_address || 'Agent'} is now ${data.state}`,
              severity: isOnline ? 'SUCCESS' : 'LOW',
              duration: 4000,
            });

            window.dispatchEvent(new CustomEvent('app:client_status', { detail: data }));
          } catch (err) {
            console.error('Error handling SSE client_status event:', err);
          }
        });

        // 3. Network Scan Update
        es.addEventListener('network_update', (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data);
            console.log('[SSE Event: network_update]', data);

            addToast({
              title: 'Network Scan Completed',
              message: `Scan finished with ${data.devices_found ?? 0} device(s) observed.`,
              severity: 'INFO',
              duration: 5000,
            });

            window.dispatchEvent(new CustomEvent('app:network_update', { detail: data }));
          } catch (err) {
            console.error('Error handling SSE network_update event:', err);
          }
        });

        // 4. Client location assignment update
        es.addEventListener('client_location_updated', (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data);
            console.log('[SSE Event: client_location_updated]', data);
            window.dispatchEvent(new CustomEvent('app:client_location_updated', { detail: data }));
          } catch (err) {
            console.error('Error handling SSE client_location_updated event:', err);
          }
        });

        // 5. DHCP Update
        es.addEventListener('dhcp_update', (e: MessageEvent) => {
          try {
            const data = JSON.parse(e.data);
            window.dispatchEvent(new CustomEvent('app:dhcp_update', { detail: data }));
          } catch (err) {
            console.error('Error handling SSE dhcp_update event:', err);
          }
        });

        es.onerror = () => {
          console.warn('[SSE] Connection lost. Reconnecting in 5s...');
          es?.close();
          reconnectTimeout = setTimeout(connect, 5000);
        };
      } catch (err) {
        console.error('[SSE] Failed to initialize EventSource:', err);
      }
    }

    connect();

    return () => {
      clearTimeout(reconnectTimeout);
      es?.close();
      esRef.current = null;
    };
  }, [addToast, navigate]);

  return { unreadAlerts };
}
