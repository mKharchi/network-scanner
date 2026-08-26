import { useState } from "react";
import { NavLink } from "react-router-dom";
import "../styles/shell.css";
import { useApiState } from "../hooks/useApiState";
import { TbCloudNetwork, TbMapPin } from "react-icons/tb";
import { RiScanLine } from "react-icons/ri";
import { MdHistory } from "react-icons/md";
import { FiServer } from "react-icons/fi";
import { HiOutlineSquare3Stack3D } from "react-icons/hi2";

// ── Icons ────────────────────────────────────────────────────────
function IconDashboard() {
  return (
    <svg
      className="nav-item__icon"
      viewBox="0 0 20 20"
      fill="currentColor"
      aria-hidden="true"
    >
      <rect x="2" y="2" width="7" height="7" rx="1.5" />
      <rect x="11" y="2" width="7" height="7" rx="1.5" />
      <rect x="2" y="11" width="7" height="7" rx="1.5" />
      <rect x="11" y="11" width="7" height="7" rx="1.5" />
    </svg>
  );
}

function IconClients() {
  return (
    <svg
      className="nav-item__icon"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
    >
      <circle cx="7" cy="7" r="3" />
      <path d="M1 17c0-3.314 2.686-5 6-5s6 1.686 6 5" strokeLinecap="round" />
      <path
        d="M13 4a3 3 0 1 1 0 6M19 17c0-3.314-2.686-5-6-5"
        strokeLinecap="round"
      />
    </svg>
  );
}

const IconHistory = () => (
  <div className="nav-item__icon" aria-hidden="true">
    <MdHistory size={15} />
  </div>
);

const IconAllDevices = () => (
  <div className="nav-item__icon" aria-hidden="true">
    <FiServer size={15} />
  </div>
);

function IconScan() {
  return (
    <div className="nav-item__icon" aria-hidden="true">
      <RiScanLine size={15} />
    </div>
  );
}

function IconNetwork() {
  return (
    <svg
      className="nav-item__icon"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
    >
      <circle cx="10" cy="10" r="2.5" />
      <circle cx="3" cy="10" r="1.5" />
      <circle cx="17" cy="10" r="1.5" />
      <circle cx="10" cy="3" r="1.5" />
      <circle cx="10" cy="17" r="1.5" />
      <line x1="5" y1="10" x2="7.5" y2="10" />
      <line x1="12.5" y1="10" x2="15.5" y2="10" />
      <line x1="10" y1="5" x2="10" y2="7.5" />
      <line x1="10" y1="12.5" x2="10" y2="15.5" />
    </svg>
  );
}

function IconAlerts() {
  return (
    <svg
      className="nav-item__icon"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
    >
      <path d="M10 2L2 16h16L10 2z" strokeLinejoin="round" />
      <line x1="10" y1="9" x2="10" y2="12" strokeLinecap="round" />
      <circle cx="10" cy="14.5" r="0.8" fill="currentColor" stroke="none" />
    </svg>
  );
}

function IconActivity() {
  return (
    <svg
      className="nav-item__icon"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
    >
      <polyline
        points="2,10 6,5 9,13 12,8 15,11 18,10"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function IconSettings() {
  return (
    <svg
      className="nav-item__icon"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      aria-hidden="true"
    >
      <circle cx="10" cy="10" r="2.5" />
      <path
        d="M10 2v1.5M10 16.5V18M2 10h1.5M16.5 10H18M3.75 3.75l1.06 1.06M15.18 15.18l1.07 1.07M3.75 16.25l1.06-1.06M15.18 4.82l1.07-1.07"
        strokeLinecap="round"
      />
    </svg>
  );
}

function IconMenu() {
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      aria-hidden="true"
    >
      <line x1="3" y1="6" x2="17" y2="6" strokeLinecap="round" />
      <line x1="3" y1="10" x2="17" y2="10" strokeLinecap="round" />
      <line x1="3" y1="14" x2="17" y2="14" strokeLinecap="round" />
    </svg>
  );
}

// ── Connection State Indicator ───────────────────────────────────
export type ApiState = "connected" | "refreshing" | "stale" | "unavailable";

const STATE_LABEL: Record<ApiState, string> = {
  connected: "Connected",
  refreshing: "Refreshing",
  stale: "Stale data",
  unavailable: "Unavailable",
};

function ConnectionState() {
  const { state } = useApiState();
  return (
    <div
      className={`conn-state conn-state--${state}`}
      aria-label={`Server connection: ${STATE_LABEL[state]}`}
      title={STATE_LABEL[state]}
    >
      <span className="conn-state__dot" />
      <span>{STATE_LABEL[state]}</span>
    </div>
  );
}

// ── Sidebar ──────────────────────────────────────────────────────
interface SidebarProps {
  isOpen?: boolean;
  newAlertCount?: number;
  onClose?: () => void;
}
function Sidebar({ isOpen = false, newAlertCount = 0, onClose }: SidebarProps) {
  return (
    <aside
      className={`sidebar${isOpen ? " sidebar--open" : ""}`}
      aria-label="Application navigation"
    >
      {/* Header / Brand */}
      <div className="sidebar__header">
        <div className="sidebar__brand">
          <div className="sidebar__brand-icon" aria-hidden="true">
            <TbCloudNetwork />
          </div>
          <div>
            <div className="sidebar__brand-name">Monitoring Console</div>
          </div>
        </div>

        <button
          type="button"
          className="sidebar__close"
          onClick={onClose}
          aria-label="Close navigation menu"
        >
          &times;
        </button>
      </div>

      <div className="sidebar__status">
        <ConnectionState />
      </div>

      {/* Navigation */}
      <nav className="sidebar__nav" aria-label="Main navigation">
        <NavLink
          to="/"
          end
          onClick={onClose}
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
        >
          <IconDashboard />
          Dashboard
        </NavLink>

        <NavLink
          to="/clients"
          onClick={onClose}
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
        >
          <IconClients />
          Clients
        </NavLink>
        <NavLink
          to="/locations"
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
        >
          <TbMapPin />
          Locations
        </NavLink>
        <NavLink
          to="/rogue-devices"
          onClick={onClose}
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
        >
          <span className="nav-item__icon" aria-hidden="true">🛰️</span>
          Rogue Triangulation
        </NavLink>
        <NavLink
          to="/digital-twin"
          onClick={onClose}
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
        >
         <HiOutlineSquare3Stack3D />
          3D Digital Twin & AR
        </NavLink>

        <span
          className="sidebar__section-label"
          style={{
            display: "flex",
            alignItems: "center",
            gap: "var(--space-1)",
          }}
        >
          <IconNetwork />
          Network
        </span>

        <NavLink
          to="/network/devices"
          onClick={onClose}
          className={({ isActive }) =>
            `nav-item nav-item--sub${isActive ? " active" : ""}`
          }
        >
          <IconAllDevices />
          All Devices
        </NavLink>

        <NavLink
          to="/network/latest"
          onClick={onClose}
          className={({ isActive }) =>
            `nav-item nav-item--sub${isActive ? " active" : ""}`
          }
        >
          <IconScan />
          Latest Scan
        </NavLink>

        <NavLink
          to="/network/history"
          onClick={onClose}
          className={({ isActive }) =>
            `nav-item nav-item--sub${isActive ? " active" : ""}`
          }
        >
          <IconHistory />
          Scan History
        </NavLink>

        <NavLink
          to="/alerts"
          onClick={onClose}
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
        >
          <IconAlerts />
          Alerts
          {newAlertCount > 0 && (
            <span
              className="nav-item__badge"
              aria-label={`${newAlertCount} new alerts`}
            >
              {newAlertCount > 99 ? "99+" : newAlertCount}
            </span>
          )}
        </NavLink>

        <NavLink
          to="/activity"
          onClick={onClose}
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
        >
          <IconActivity />
          Activity Logs
        </NavLink>
      </nav>

      {/* Footer */}
      <div className="sidebar__footer">
        <NavLink
          to="/settings"
          onClick={onClose}
          className={({ isActive }) => `nav-item${isActive ? " active" : ""}`}
        >
          <IconSettings />
          Settings
        </NavLink>
      </div>
    </aside>
  );
}
// ── App Shell ────────────────────────────────────────────────────
interface AppShellProps {
  children: React.ReactNode;
  newAlertCount?: number;
}

export function AppShell({ children, newAlertCount = 0 }: AppShellProps) {
  const [menuOpen, setMenuOpen] = useState(false);

  return (
    <div className="app-shell">
      {menuOpen && (
        <div
          className="sidebar-overlay"
          onClick={() => setMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      <Sidebar
        isOpen={menuOpen}
        newAlertCount={newAlertCount}
        onClose={() => setMenuOpen(false)}
      />

      <header className="mobile-header">
        <button
          type="button"
          className="mobile-menu-button"
          onClick={() => setMenuOpen(true)}
          aria-label="Open navigation menu"
          aria-expanded={menuOpen}
        >
          <IconMenu />
        </button>

        <div className="mobile-header__title">Monitoring Console</div>

        <ConnectionState />
      </header>

      <main className="main-content" id="main-content" tabIndex={-1}>
        {children}
      </main>
    </div>
  );
}
