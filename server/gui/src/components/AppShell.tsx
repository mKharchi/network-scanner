import { useState } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";
import "../styles/shell.css";
import { useApiState } from "../hooks/useApiState";
import { TbActivity, TbCloudNetwork, TbDevices, TbMapPin, TbRadar, TbShieldAlert, TbAdjustmentsHorizontal } from "react-icons/tb";
import { FiCpu, FiExternalLink, FiGlobe, FiMenu, FiX } from "react-icons/fi";
import { HiOutlineSquare3Stack3D } from "react-icons/hi2";

// ── Connection State Indicator ───────────────────────────────────
export type ApiState = "connected" | "refreshing" | "stale" | "unavailable";

const STATE_LABEL: Record<ApiState, string> = {
  connected: "LIVE",
  refreshing: "SYNCING",
  stale: "STALE",
  unavailable: "OFFLINE",
};

function LiveStatusPill() {
  const { state } = useApiState();
  return (
    <div
      className={`header-status-pill header-status-pill--${state}`}
      title={`Server State: ${STATE_LABEL[state]}`}
    >
      <span className="status-dot" />
      <span>{STATE_LABEL[state]}</span>
    </div>
  );
}

// ── Navigation Link Definitions ──────────────────────────────────
interface NavEntry {
  label: string;
  to: string;
  icon: React.ReactNode;
  badge?: number;
  exact?: boolean;
}

interface NavGroup {
  name: string;
  items: NavEntry[];
}

export function AppShell({
  children,
  newAlertCount = 0,
}: {
  children: React.ReactNode;
  newAlertCount?: number;
}) {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const location = useLocation();
  const navigate = useNavigate();

  const navGroups: NavGroup[] = [
    {
      name: "INTELLIGENCE",
      items: [
        { label: "Overview", to: "/", icon: <TbRadar size={18} />, exact: true },
        { label: "Devices", to: "/network/devices", icon: <TbDevices size={18} /> },
        { label: "Clients", to: "/clients", icon: <FiCpu size={18} /> },
      ],
    },
    {
      name: "SPATIAL",
      items: [
        { label: "3D Network Twin", to: "/digital-twin", icon: <HiOutlineSquare3Stack3D size={18} /> },
        { label: "Locations", to: "/locations", icon: <TbMapPin size={18} /> },
      ],
    },
    {
      name: "OPERATIONS",
      items: [
        {
          label: "Security Alerts",
          to: "/alerts",
          icon: <TbShieldAlert size={18} />,
          badge: newAlertCount,
        },
        { label: "Rogue Hunter", to: "/rogue-devices", icon: <TbRadar size={18} /> },
        { label: "Activity Logs", to: "/activity", icon: <TbActivity size={18} /> },
        { label: "Settings", to: "/settings", icon: <TbAdjustmentsHorizontal size={18} /> },
      ],
    },
  ];

  return (
    <div className="netwatch-shell">
      {/* ── Top Header Bar ────────────────────────────────────────── */}
      <header className="netwatch-header">
        <div className="header-left">
          {/* Mobile menu trigger */}
          <button
            type="button"
            className="mobile-toggle-btn"
            onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
            aria-label="Toggle navigation"
          >
            {mobileMenuOpen ? <FiX size={20} /> : <FiMenu size={20} />}
          </button>

          {/* Product Brand Identity */}
          <NavLink to="/" className="brand-logo">
            <div className="brand-icon">
              <TbCloudNetwork size={22} />
            </div>
            <div className="brand-text">
              <span className="brand-title">NETWATCH</span>
              <span className="brand-sub">INTELLIGENCE</span>
            </div>
          </NavLink>

          {/* Primary Top Nav Links (Desktop) */}
          <nav className="desktop-nav" aria-label="Main Navigation">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                `top-nav-link ${isActive ? "top-nav-link--active" : ""}`
              }
            >
              <TbRadar size={16} />
              <span>Overview</span>
            </NavLink>

            <NavLink
              to="/network/devices"
              className={({ isActive }) =>
                `top-nav-link ${isActive || location.pathname.startsWith("/network") ? "top-nav-link--active" : ""}`
              }
            >
              <TbDevices size={16} />
              <span>Devices</span>
            </NavLink>

            <NavLink
              to="/digital-twin"
              className={({ isActive }) =>
                `top-nav-link top-nav-link--spatial ${isActive ? "top-nav-link--active" : ""}`
              }
            >
              <HiOutlineSquare3Stack3D size={16} />
              <span>3D Twin</span>
              <span className="spatial-badge">SPATIAL</span>
            </NavLink>

            <NavLink
              to="/clients"
              className={({ isActive }) =>
                `top-nav-link ${isActive ? "top-nav-link--active" : ""}`
              }
            >
              <FiCpu size={16} />
              <span>Clients</span>
            </NavLink>

            <NavLink
              to="/locations"
              className={({ isActive }) =>
                `top-nav-link ${isActive ? "top-nav-link--active" : ""}`
              }
            >
              <TbMapPin size={16} />
              <span>Locations</span>
            </NavLink>

            <NavLink
              to="/alerts"
              className={({ isActive }) =>
                `top-nav-link ${isActive ? "top-nav-link--active" : ""}`
              }
            >
              <TbShieldAlert size={16} />
              <span>Alerts</span>
              {newAlertCount > 0 && (
                <span className="alert-count-pill">{newAlertCount}</span>
              )}
            </NavLink>

            <NavLink
              to="/activity"
              className={({ isActive }) =>
                `top-nav-link ${isActive ? "top-nav-link--active" : ""}`
              }
            >
              <TbActivity size={16} />
              <span>Activity</span>
            </NavLink>
          </nav>
        </div>

        {/* Header Right Controls */}
        <div className="header-right">
          {/* Live system state */}
          <LiveStatusPill />

          {/* Language selector pill */}
          <div className="lang-pill" title="System Locale">
            <FiGlobe size={13} />
            <span>EN</span>
          </div>

          {/* Operator / User badge */}
          <div className="operator-badge" title="Operator: SEC-OPS ADMIN">
            <span className="operator-avatar">OP</span>
            <span className="operator-name">SEC-OPS</span>
          </div>

          {/* Primary Action Button */}
          <button
            type="button"
            className="header-cta-btn"
            onClick={() => navigate("/digital-twin")}
          >
            <span>Explore Twin</span>
            <span className="btn-arrow">→</span>
          </button>
        </div>
      </header>

      {/* ── Mobile & Drawer Navigation Overlay ─────────────────────── */}
      {mobileMenuOpen && (
        <div
          className="drawer-overlay"
          onClick={() => setMobileMenuOpen(false)}
        />
      )}

      <aside className={`drawer-sidebar ${mobileMenuOpen ? "drawer-sidebar--open" : ""}`}>
        <div className="drawer-header">
          <div className="brand-logo">
            <div className="brand-icon">
              <TbCloudNetwork size={20} />
            </div>
            <div className="brand-text">
              <span className="brand-title">NETWATCH</span>
              <span className="brand-sub">INTELLIGENCE</span>
            </div>
          </div>
          <button
            type="button"
            className="drawer-close-btn"
            onClick={() => setMobileMenuOpen(false)}
          >
            <FiX size={20} />
          </button>
        </div>

        <div className="drawer-content">
          {navGroups.map((group) => (
            <div key={group.name} className="drawer-group">
              <div className="drawer-group-title">{group.name}</div>
              <div className="drawer-items">
                {group.items.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.exact}
                    onClick={() => setMobileMenuOpen(false)}
                    className={({ isActive }) =>
                      `drawer-link ${isActive ? "drawer-link--active" : ""}`
                    }
                  >
                    <span className="drawer-link-icon">{item.icon}</span>
                    <span className="drawer-link-label">{item.label}</span>
                    {item.badge !== undefined && item.badge > 0 && (
                      <span className="alert-count-pill">{item.badge}</span>
                    )}
                  </NavLink>
                ))}
              </div>
            </div>
          ))}
        </div>

        <div className="drawer-footer">
          <button
            type="button"
            className="header-cta-btn"
            style={{ width: "100%", justifyContent: "center" }}
            onClick={() => {
              setMobileMenuOpen(false);
              navigate("/digital-twin");
            }}
          >
            <span>Explore 3D Network</span>
            <span className="btn-arrow">→</span>
          </button>
        </div>
      </aside>

      {/* ── Main Viewport Content ─────────────────────────────────── */}
      <main className="netwatch-main">
        <div className="netwatch-content-container">
          {children}
        </div>
      </main>
    </div>
  );
}
