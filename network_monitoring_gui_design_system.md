# Network Monitoring GUI — Design System

## Purpose

This design system is for a desktop-first operational monitoring interface.
Its priorities are clarity, readable dense data, visible freshness, and a
consistent treatment of risk. It deliberately avoids decorative gradients,
large illustration areas, and non-essential animation.

This is a specification, not a frontend implementation. No frontend
technology exists in the repository yet, so the eventual application should
express these as CSS variables/tokens and reusable components.

## Foundations

### Typography

Use a system sans-serif stack so the local operator UI stays fast and native:

```css
font-family: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
```

| Token | Value | Use |
| --- | --- | --- |
| `font-xs` | 0.75rem / 1rem | timestamps, labels, table metadata |
| `font-sm` | 0.875rem / 1.25rem | body copy, table values, buttons |
| `font-base` | 1rem / 1.5rem | long-form content |
| `font-lg` | 1.125rem / 1.5rem | card titles, section headings |
| `font-xl` | 1.5rem / 2rem | page titles |
| `font-2xl` | 2rem / 2.5rem | dashboard key metric only |

Use tabular numerals for IP addresses, counts, IDs, and timestamps. Use a
monospace face only for MAC addresses, IP addresses, paths, and event payload
snippets.

### Spacing and layout

Use a four-pixel base unit.

| Token | Value |
| --- | --- |
| `space-1` | 0.25rem |
| `space-2` | 0.5rem |
| `space-3` | 0.75rem |
| `space-4` | 1rem |
| `space-5` | 1.25rem |
| `space-6` | 1.5rem |
| `space-8` | 2rem |

Desktop content is centered in a fluid container with a 90rem maximum width.
Use 24px page padding on desktop, 16px on tablet, and 12px on narrow screens.
Cards use 16px internal padding and 12–16px gaps. Never use spacing alone to
indicate severity; severity must also have text and an icon.

### Colour tokens

The default is a light, neutral theme with high-contrast text. These semantic
names, not raw colours, should be used in component code.

| Token | Hex | Use |
| --- | --- | --- |
| `canvas` | `#F8FAFC` | application background |
| `surface` | `#FFFFFF` | cards, dialogs, sidebar |
| `surface-muted` | `#F1F5F9` | table headers, inactive controls |
| `border` | `#CBD5E1` | component boundaries |
| `text` | `#0F172A` | primary text |
| `text-muted` | `#475569` | metadata and helper text |
| `primary` | `#1D4ED8` | primary actions, selected navigation |
| `primary-hover` | `#1E40AF` | primary action hover |
| `focus` | `#2563EB` | 2px keyboard focus ring |
| `success` | `#15803D` | online, resolved, successful action |
| `warning` | `#B45309` | warning, stale data |
| `danger` | `#B91C1C` | high-risk / critical attention |
| `info` | `#0369A1` | neutral operational information |

Use tinted semantic backgrounds (`success` at low opacity, etc.) behind
badges and banners while retaining the semantic foreground colour. Text and
icons must satisfy normal-text contrast against their actual background.

## Reusable components

### Navigation

The sidebar is the primary desktop navigation and contains only:

```text
Dashboard
Clients
Network
  Latest Scan
  Scan History
  DHCP Activity
Alerts
Activity Logs
Settings
```

An active item uses a left accent, a `surface-muted` background, and `text`
colour. It must not rely only on blue text. On narrow screens, replace the
sidebar with a menu button and keep the current route in the header.

### Header

The header contains the page title, optional contextual controls, and a
global server-data state:

* `Connected` — last refresh succeeded.
* `Refreshing` — request in progress; retain usable old data.
* `Stale` — previous data is visible but a refresh failed; show its timestamp.
* `Unavailable` — no data can be displayed; show a retry action.

The state is informational, not an assertion that an individual monitoring
client is online.

### Buttons

Buttons have a minimum 36px height, 8px corner radius, visible focus ring,
and disabled state with unchanged label.

| Variant | Use |
| --- | --- |
| Primary | one main action within a context: `Retry`, `Apply filters` |
| Secondary | non-destructive supporting actions |
| Quiet | low-emphasis table or header action |
| Danger | destructive/irreversible future actions only |

Initial read-only pages must not display inactive-looking edit controls. If an
operation is not available, omit it and explain it in relevant settings copy.

### Cards and metrics

Cards have a 1px `border`, 8px radius, `surface` background, and no heavy
drop shadow. A metric card contains a concise label, one prominent value, and
one freshness/context line. Keep critical detail in tables/timelines, not
inside a grid of oversized metrics.

### Tables

Tables are the default for clients, devices, alerts, scan history, and log
metadata.

* Header row remains visible when the table body scrolls.
* Sortable headers show the active direction and have a real accessible name.
* Use 44px minimum row height; right-align counts and dates where helpful.
* Preserve primary identity columns (hostname/client ID or MAC) on smaller
  screens; move secondary data into a row detail view instead of horizontal
  overflow where possible.
* Unknown values render as an em dash with an accessible label such as
  `Hostname unavailable`; never hide the whole device.
* MAC and IP values use monospace and can be copied.

### Badges and status indicators

Badges always contain an icon or text label in addition to colour.

| Meaning | Label | Semantic token |
| --- | --- | --- |
| Live managed agent | `Online` | success |
| No live socket | `Offline` | text-muted |
| Data freshness failed | `Stale` | warning |
| Alert status | `New`, `Acknowledged`, `Resolved` | danger, warning, success |
| Alert severity | `Low`, `Medium`, `High`, `Critical` | info, warning, danger, danger |
| Device classification | `Managed`, `Unmanaged` | primary, text-muted |

`Critical` is differentiated from `High` with iconography and stronger surface
treatment, not a second arbitrary red tone. Never equate `Offline` with an
alert severity.

### Alerts and notices

Use inline notices for recoverable page problems and global banners only for
application-wide problems.

Each notice contains: concise title, plain-language explanation, optional
timestamp/context, and one relevant action. Examples:

* Warning: “Network scan is stale — last completed 2 hours ago.”
* Error: “Unable to load alerts. Retry.”
* Info: “No DHCP observations were recorded on this date.”

### Dialogs

Dialogs are reserved for confirmations and focused details. They need a
visible title, close button, Escape support, focus trapping, and focus return
to the invoking control. Do not put normal table filtering or ordinary
navigation inside dialogs.

### Loading, empty, error, and partial-data states

| State | Treatment |
| --- | --- |
| Loading with no prior data | layout-shaped skeletons, no misleading zeros |
| Refreshing with prior data | retain data and use a small progress indicator in the header/control |
| Empty | explanatory sentence plus only a relevant next step |
| Error with prior data | show stale notice and retain data/timestamp |
| Error with no data | centered compact error panel with `Retry` |
| Partial data | show the available device/client and use explicit unavailable values for enrichment fields |

Animation is limited to short opacity transitions for skeletons and control
feedback. Honour `prefers-reduced-motion`.

## Responsive and accessibility rules

* Desktop is the primary working layout: sidebar plus roomy tables at 1024px
  and above.
* Between 768px and 1023px, collapse secondary table columns and reduce page
  padding; retain the sidebar only if it does not crowd main content.
* Below 768px, use the menu-triggered navigation, stacked metric cards, and
  detail views for dense rows.
* Every control is keyboard reachable with a visible focus indicator.
* Status colour is never the sole carrier of meaning.
* Controls, badges, timestamps, and icon-only buttons have accessible names.
* Use semantic headings, table headers, and live regions only for genuinely
  changing data/error announcements.

## First implementation inventory

When the application shell is started, implement these primitives before any
page-specific component:

1. token layer (colour, typography, spacing, radius, focus)
2. `AppShell`, `Sidebar`, and `Header`
3. `Button`, `Badge`, `StatusIndicator`, and `Notice`
4. `Card`, `MetricCard`, `DataTable`, and `EmptyState`
5. `LoadingSkeleton`, `ErrorState`, and `Dialog`

Pages should compose these primitives rather than redefining colours, spacing,
or status treatment locally.
