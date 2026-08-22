import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom';
import { ApiStateProvider } from './hooks/useApiState';
import { ToastProvider } from './hooks/useToast';
import { useRealTimeEvents } from './hooks/useRealTimeEvents';
import { AppShell } from './components/AppShell';

import { DashboardPage } from './pages/Dashboard';
import { ClientsPage } from './pages/Clients';
import { ClientDetailPage } from './pages/ClientDetail';
import { LatestScanPage } from './pages/LatestScan';
import { ScanHistoryPage } from './pages/ScanHistory';
import { DeviceDetailPage } from './pages/DeviceDetail';
import { DhcpActivityPage } from './pages/DhcpActivity';
import { AlertsPage } from './pages/Alerts';
import { ActivityLogsPage } from './pages/ActivityLogs';
import { SettingsPage } from './pages/Settings';

function AppContent() {
  const { unreadAlerts } = useRealTimeEvents();

  return (
    <AppShell newAlertCount={unreadAlerts}>
      <Routes>
        <Route path="/" element={<DashboardPage />} />

        {/* Clients */}
        <Route path="/clients" element={<ClientsPage />} />
        <Route path="/clients/:clientId" element={<ClientDetailPage />} />

        {/* Network */}
        <Route path="/network" element={<Navigate to="/network/latest" replace />} />
        <Route path="/network/latest" element={<LatestScanPage />} />
        <Route path="/network/history" element={<ScanHistoryPage />} />
        <Route path="/network/devices/:mac" element={<DeviceDetailPage />} />
        <Route path="/network/dhcp" element={<DhcpActivityPage />} />

        {/* Alerts */}
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/alerts/:alertId" element={<AlertsPage />} />

        {/* Activity Logs */}
        <Route path="/activity" element={<ActivityLogsPage />} />
        <Route path="/activity/:logId" element={<ActivityLogsPage />} />

        {/* Settings */}
        <Route path="/settings" element={<SettingsPage />} />

        {/* Fallback */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AppShell>
  );
}

export default function App() {
  return (
    <ApiStateProvider>
      <BrowserRouter>
        <ToastProvider>
          <AppContent />
        </ToastProvider>
      </BrowserRouter>
    </ApiStateProvider>
  );
}
