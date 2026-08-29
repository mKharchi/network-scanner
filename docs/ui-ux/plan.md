Absolutely. Since you want a **complete UI transformation**, I would give the coding AI a prompt that explicitly tells it **not to preserve the current visual structure** while still preserving the application's functionality, routes, APIs, and business logic.

Here is a prompt you can paste directly into your coding AI:

# Complete UI/UX Redesign — Deep Navy Network Intelligence Platform

## Objective

Completely redesign the current application's frontend UI/UX.

This is **not a minor restyling task**.

The existing application should receive a **complete visual and structural transformation** into a modern, premium network intelligence / infrastructure operations platform.

The goal is to make the application feel like a **cohesive professional product**, not a collection of independent pages and features.

The new design should communicate:

* Network intelligence
* Infrastructure visibility
* Spatial awareness
* Real-time monitoring
* Technical sophistication
* Reliability
* Security
* Professional enterprise software

The application already contains significant functionality. **Do not remove, break, or rewrite existing business logic merely to redesign the UI.**

The redesign should primarily affect:

* Layout
* Navigation
* Visual hierarchy
* Components
* Information presentation
* Interactions
* Animations
* Responsive behavior
* Page composition
* Design system

Preserve existing:

* API integrations
* Backend logic
* Data fetching
* Authentication
* Routing
* Existing feature functionality
* Device discovery
* Client management
* Location functionality
* 3D visualization
* Alerts
* Network monitoring
* Existing actions and workflows

If an existing component is structurally incompatible with the new design, rebuild its frontend implementation while preserving its underlying functionality.

---

# 1. Design Direction

The new UI should feel like a combination of:

* Enterprise network operations center
* Modern SaaS dashboard
* Infrastructure intelligence platform
* Spatial/network digital twin
* Premium technical control system

Avoid making it look like a generic admin dashboard.

The interface should have a strong visual identity.

The application should feel:

> **Dark, precise, intelligent, spatial, technical, modern, and premium.**

Do not use excessive gradients, glassmorphism, glowing neon effects, or excessive decorative elements.

The design should remain clean and functional.

---

# 2. Color System

Use the following palette as the foundation of the entire application.

### Primary Colors

```css
--deep-card-navy: #1B326B;
--dark-background-navy: #081329;
--accent-blue: #2563EB;
--white: #FFFFFF;
--muted-text: #94A3B8;
```

### Supporting Colors

```css
--badge-background: rgba(255, 255, 255, 0.12);
--badge-solid: #2C4175;
```

Create additional neutral/semantic colors only when necessary for:

* Success
* Warning
* Error
* Informational states

Do not introduce unrelated primary colors.

Blue should remain the dominant accent.

---

# 3. Typography

Use a modern geometric sans-serif.

Preferred order:

```text
Inter
Plus Jakarta Sans
SF Pro Display
```

Use the font consistently throughout the application.

### Eyebrows

Use for:

* Section labels
* Categories
* Status labels
* Context indicators

Properties:

```text
12–14px
uppercase
font-weight: 600–700
letter-spacing: 0.08em
muted blue/slate
```

Example:

```text
NETWORK INTELLIGENCE
```

### Main headings

```text
28–36px
bold
tight line-height
```

Important dashboard headings can be larger when appropriate.

### Body

```text
14–16px
regular
comfortable line-height
```

Use muted slate-blue text for secondary information.

---

# 4. Global Layout

Completely reconsider the existing application shell.

Do not simply keep the current sidebar/header structure and recolor it.

The navigation and page composition should be redesigned as a unified system.

Use:

```text
Top Header
────────────────────────────────────────────

Page Content
────────────────────────────────────────────

Cards / Visualization / Intelligence
```

The exact implementation can use a sidebar, floating navigation, top navigation, or hybrid navigation depending on what works best with the existing application.

However, navigation must remain extremely easy to understand.

The user should always know:

1. Where they are.
2. What the current system state is.
3. What the most important action is.
4. How to reach the major platform capabilities.

---

# 5. Header

Create a crisp white header.

Use:

```text
Logo / Product Identity

Navigation

                         Status
                         EN
                         User
                         Primary CTA
```

The header should feel lightweight and premium.

Use generous spacing.

Navigation links should not feel crowded.

Active navigation should use the blue accent rather than heavy boxes.

Language selector:

```text
EN
```

Use an outline pill.

Primary CTA:

```text
solid #2563EB
white text
pill shape
```

---

# 6. Page Backgrounds

Use strong contrast between sections.

Primary page areas should use:

```text
#FFFFFF
```

while major technical/intelligence sections can use:

```text
#081329
```

Dark sections should feel intentional rather than simply being dark dashboards.

Use dark full-width bands for:

* Network overview
* Spatial intelligence
* Infrastructure topology
* System intelligence
* Important monitoring areas

---

# 7. Cards

Replace generic dashboard cards with a consistent card system.

Primary cards:

```text
background: #1B326B
border-radius: 20–24px
padding: 32–48px
```

Cards should have:

* Strong typography
* Clear hierarchy
* Minimal borders
* Minimal decoration
* Generous whitespace

Do not make every piece of information a separate card.

Cards should group related information.

Avoid:

```text
card inside card inside card
```

Prefer:

```text
Section
    └── meaningful information group
```

---

# 8. Buttons

Primary buttons should be pill-shaped.

```text
border-radius: 9999px
background: #2563EB
color: white
font-weight: 600
```

Primary action buttons should preferably include an arrow:

```text
Explore Network →
View Devices →
Open Twin →
Investigate →
```

Secondary actions can use:

```text
outline
subtle navy
transparent
```

Do not use excessive button variants.

---

# 9. Tags and Metadata

Use compact pills.

Examples:

```text
● ONLINE
⌖ FLOOR 2
◷ 2 MIN AGO
12 DEVICES
WINDOWS
HIGH RISK
```

Use:

```text
background: rgba(255,255,255,0.12)
```

or:

```text
#2C4175
```

with muted light text.

Pills should communicate information, not decorate the UI.

---

# 10. Dashboard Redesign

The dashboard should become the **command center of the entire platform**.

Do not make it a simple collection of statistics.

The dashboard should immediately answer:

```text
What is happening?

What changed?

Where is it happening?

What requires attention?

What should I investigate?
```

Suggested structure:

```text
┌──────────────────────────────────────────────────────┐
│ NETWORK INTELLIGENCE                                 │
│ See what's happening across your infrastructure.     │
│                                                      │
│ [Explore Network →]                                  │
└──────────────────────────────────────────────────────┘


┌──────────────────────────────────────────────────────┐
│                                                      │
│                 NETWORK OVERVIEW                     │
│                                                      │
│       127 Devices        18 Clients                  │
│       4 Alerts           3 Locations                 │
│                                                      │
└──────────────────────────────────────────────────────┘


┌──────────────────────────┐  ┌────────────────────────┐
│ NETWORK ACTIVITY         │  │ ATTENTION REQUIRED      │
│                          │  │                        │
│ activity visualization  │  │ suspicious devices     │
│                          │  │ client problems        │
└──────────────────────────┘  └────────────────────────┘


┌──────────────────────────────────────────────────────┐
│ SPATIAL NETWORK INTELLIGENCE                         │
│                                                      │
│              3D NETWORK TWIN                        │
│                                                      │
│          [ Explore 3D Network → ]                    │
└──────────────────────────────────────────────────────┘
```

The dashboard should prioritize **information and action**, not statistics alone.

---

# 11. Give the 3D Network Twin Much More Importance

The existing 3D visualization is a major differentiating feature.

It should no longer feel like a secondary page hidden behind several navigation steps.

Make it a first-class feature.

The dashboard should include a meaningful preview of the spatial network.

Example:

```text
SPATIAL INTELLIGENCE

Your infrastructure, mapped in space.

        [3D NETWORK VISUALIZATION]

127 devices
18 clients
4 suspicious devices

[Open Network Twin →]
```

The 3D view should communicate:

* Device positions
* Client positions
* Device categories
* Suspicious devices
* Locations
* Connectivity
* Activity
* Spatial anomalies

Use the existing 3D functionality.

Do not replace it with a fake visualization.

---

# 12. Device Management

Completely redesign the device interface.

Do not present devices as a basic CRUD table.

The device page should feel like an **intelligence explorer**.

Suggested structure:

```text
DEVICES

Network Devices
127 discovered

[Search devices]
[Filter]
[Classification]
[Location]
[Status]


DEVICE
────────────────────────────────────────────

Device Name
Vendor
Type
Location
Status
Last Seen
Risk

────────────────────────────────────────────
```

Clicking a device should open a rich detail experience.

---

# 13. Device Detail Page

The device detail page should become one of the most informative pages in the platform.

Suggested hierarchy:

```text
DEVICE INTELLIGENCE

Xiaomi Device

ANDROID MOBILE
94% classification confidence

● ONLINE
⌖ FLOOR 2 / ROOM 4
◷ LAST SEEN 12 SECONDS AGO


OVERVIEW

Identity
Vendor
IP
MAC
Hostname

CLASSIFICATION

Android Mobile
94%
ML
device-classifier-v1


LOCATION

Floor 2
Room 4

[Open in Network Twin →]


OBSERVATIONS

DHCP
mDNS
SSDP
LLMNR


ACTIVITY

Timeline of important observations
```

Use progressive disclosure.

Don't display every technical field simultaneously.

---

# 14. Client Management

Clients should have their own visual identity.

Present them as active infrastructure agents.

Example:

```text
CLIENTS

18 active agents

Healthy       15
Warning         2
Offline         1


CLIENT AGENT

CLIENT-07

● HEALTHY

CPU        24%
Memory     51%
Network    12 Mbps

Last heartbeat
12 seconds ago

[Open Client →]
```

Client pages should make health and connectivity immediately visible.

---

# 15. Alerts

Redesign alerts into an **incident intelligence** experience.

Avoid a simple list of red warning boxes.

Use severity intelligently.

Example:

```text
ATTENTION REQUIRED

4 active events


HIGH

Unknown device detected
Floor 2 / Training Room 3

2 minutes ago

[Investigate →]


MEDIUM

Client scanner degraded
CLIENT-07

8 minutes ago
```

Eventually this page should support:

* Alert grouping
* Correlation
* Severity
* Location
* Device
* Timeline
* Investigation

This will prepare the UI for future ML-based alert correlation.

---

# 16. Spatial / Location Interface

Location should become a major navigation concept.

Instead of treating location as just a field:

```text
Location: Floor 2
```

make it an interactive system.

Example:

```text
SPATIAL INTELLIGENCE

FLOOR 2

        ┌───────────────┐
        │ TRAINING ROOM │
        │               │
        │ ● ● ● ●       │
        │               │
        └───────────────┘

        32 devices
        5 clients
        1 alert

[Open Spatial View →]
```

The interface should connect:

```text
Location
    ↕
Devices
    ↕
Clients
    ↕
Alerts
    ↕
3D Twin
```

The user should not feel like these are separate systems.

---

# 17. Navigation Philosophy

The new UI should organize the application around **user intent**, not backend modules.

Instead of presenting:

```text
Scanner
DHCP
mDNS
Spatial-Temporal Rogue Device Triangulation
Client Management
Storage
```

as unrelated technical features, organize the experience around:

```text
OVERVIEW

NETWORK
    Devices
    Clients
    Activity

SPATIAL
    Network Twin
    Locations
    Spatial Intelligence

SECURITY
    Alerts
    Suspicious Devices
    Investigations

INTELLIGENCE
    Device Classification
    Network Intelligence
    Predictions

SYSTEM
    Settings
```

Technical implementation details should remain behind the interface.

---

# 18. Empty States

Every page should have intentional empty states.

Do not use:

```text
No data.
```

Instead:

```text
NO DEVICES DETECTED

The network discovery agents haven't reported
any devices yet.

[Check Clients →]
```

Make empty states useful and actionable.

---

# 19. Loading States

Replace generic loading indicators with contextual skeletons.

Examples:

```text
Loading Network Intelligence...
```

or skeleton representations of:

* Device cards
* Tables
* Statistics
* Spatial data
* Alerts

Avoid flashing blank screens.

---

# 20. Animations

Use subtle motion.

Recommended:

* Page transitions
* Card hover elevation
* Button transitions
* Navigation transitions
* Data updates
* 3D interaction feedback
* Alert appearance
* Expand/collapse transitions

Keep animations short and professional.

Avoid:

* Excessive bouncing
* Constant pulsing
* Large animated gradients
* Decorative motion everywhere

Motion should communicate state.

---

# 21. Responsive Design

The application must work properly on:

* Desktop
* Laptop
* Tablet
* Smaller screens

Do not simply shrink desktop layouts.

Create intentional responsive behavior.

For example:

Desktop:

```text
[Navigation] [Main content] [Context panel]
```

Mobile:

```text
Header
   ↓
Primary content
   ↓
Context sections
```

Navigation should collapse into an accessible mobile menu.

No functionality should disappear on smaller screens.

---

# 22. Accessibility

Ensure:

* Proper contrast.
* Keyboard navigation.
* Visible focus states.
* Semantic HTML.
* Accessible buttons.
* Accessible tooltips.
* Meaningful labels.
* Icons paired with accessible text where necessary.

Do not rely solely on color to communicate status.

---

# 23. Design System

Before redesigning individual pages, establish reusable components.

Create a coherent design system containing:

```text
Button
Card
Badge
Status
Metric
SectionHeader
PageHeader
Navigation
Tabs
DataTable
EmptyState
Modal
Drawer
Tooltip
Search
Filter
Dropdown
Timeline
Alert
DeviceCard
ClientCard
LocationCard
```

Use these components throughout the application.

Do not implement every page independently.

---

# 24. CSS / Styling Rules

Use centralized design tokens.

Example:

```css
:root {
  --color-card-navy: #1B326B;
  --color-background-navy: #081329;
  --color-accent: #2563EB;
  --color-white: #FFFFFF;
  --color-muted: #94A3B8;
  --color-badge: rgba(255, 255, 255, 0.12);

  --radius-card: 24px;
  --radius-pill: 9999px;

  --space-section: 64px;
  --space-card: 32px;
}
```

Do not scatter arbitrary colors throughout the application.

---

# 25. Important UX Transformation

The most important requirement is:

> **Do not simply make the current UI look like this color palette.**

The information architecture should also be redesigned.

The current application may have technically separate features, but the new interface should make them feel like one intelligent platform.

For example:

```text
Client connects
        ↓
Discovery happens
        ↓
Devices appear
        ↓
Devices are classified
        ↓
Devices are localized
        ↓
Devices appear in 3D
        ↓
Alerts are generated
        ↓
User investigates
```

The UI should represent this workflow naturally.

The user should not have to manually navigate through unrelated pages to understand what happened.

---

# 26. Connect Features Contextually

Whenever an object appears in the UI, provide contextual connections.

For example, a device card should be able to expose:

```text
Device
  ↓
Classification
  ↓
Location
  ↓
Observations
  ↓
Alerts
  ↓
3D position
  ↓
Related clients
```

A client should expose:

```text
Client
  ↓
Health
  ↓
Connected status
  ↓
Discovered devices
  ↓
Location
  ↓
Diagnostics
```

A location should expose:

```text
Location
  ↓
Devices
  ↓
Clients
  ↓
Alerts
  ↓
3D view
```

This creates a **connected UX**.

---

# 27. Visual Hierarchy

Every page must have one obvious primary element.

Ask:

> "What should the user look at first?"

Then:

> "What should they understand second?"

Then:

> "What action should they take?"

Avoid giving every component equal visual weight.

Use:

```text
Primary
    ↓
Secondary
    ↓
Supporting information
    ↓
Technical details
```

---

# 28. Technical Information

This is a technical network platform, so do not hide important information.

However, use progressive disclosure.

Example:

```text
DEVICE

Android Smartphone
94% confidence

────────────────────

Basic Information

Vendor
Xiaomi

Location
Floor 2

Status
Online


[Technical Details ▼]

MAC
DHCP fingerprint
mDNS records
SSDP headers
Raw observations
```

This keeps the interface approachable while preserving technical depth.

---

# 29. Visual Language

Use:

* Large typography
* Generous whitespace
* Strong navy blocks
* Bright blue actions
* Rounded cards
* Compact pills
* Crisp white surfaces
* Clear section separation
* Strong alignment
* Consistent spacing

Avoid:

* Excessive borders
* Tiny text everywhere
* Dense legacy admin-dashboard layouts
* Too many cards
* Excessive gradients
* Excessive shadows
* Random colors
* Inconsistent border radii
* Inconsistent spacing

---

# 30. Implementation Strategy

Do not attempt to rewrite the entire frontend in one uncontrolled change.

Implement the redesign in stages.

### Stage 1 — Foundation

Create:

* Color tokens
* Typography
* Spacing system
* Radius system
* Button system
* Card system
* Badge system
* Global layout
* Navigation

### Stage 2 — Application Shell

Redesign:

* Header
* Navigation
* Responsive menu
* Page container
* Global background
* Global transitions

### Stage 3 — Dashboard

Completely redesign the dashboard around:

```text
Network Overview
+
Attention Required
+
Network Activity
+
Spatial Intelligence
+
3D Twin
```

### Stage 4 — Devices

Redesign:

* Device list
* Device filters
* Device details
* Classification
* Observations
* Location

### Stage 5 — Clients

Redesign:

* Client list
* Client health
* Client details
* Diagnostics
* Discovered devices

### Stage 6 — Spatial Intelligence

Redesign:

* Locations
* Spatial device visualization
* 3D network twin
* Device positioning
* Spatial alerts

### Stage 7 — Alerts

Redesign:

* Alert overview
* Alert details
* Investigation
* Location/device relationships

### Stage 8 — Remaining Pages

Bring:

* Settings
* Administration
* Other existing features

into the new design system.

---

# 31. Preserve Functionality

During the redesign:

DO NOT:

* Delete existing APIs.
* Remove existing functionality.
* Change backend contracts unnecessarily.
* Remove routes.
* Remove existing discovery mechanisms.
* Replace working functionality with placeholders.
* Fake data.
* Remove technical information simply to make the UI cleaner.

The objective is:

```text
Existing functionality
        +
New information architecture
        +
New design system
        +
Better UX
```

not:

```text
New UI
-
Existing functionality
```

---

# 32. Code Quality Requirements

The redesign should:

* Reuse components.
* Avoid duplicated CSS.
* Avoid massive page-specific stylesheets where reusable components are appropriate.
* Use existing project conventions where sensible.
* Keep frontend logic separated from presentation.
* Avoid unnecessary dependencies.
* Preserve existing state management.
* Preserve API hooks.
* Keep components maintainable.

Before creating a new component, check whether an existing component can be generalized.

---

# 33. Final UX Goal

The final application should feel like this:

```text
                 NETWORK INTELLIGENCE
────────────────────────────────────────────────

        Everything happening across
        your infrastructure.

────────────────────────────────────────────────

 NETWORK                     ATTENTION

 127 Devices                  4 Alerts
 18 Clients                   2 Suspicious
 6 Locations                  1 Client Issue


────────────────────────────────────────────────

                 SPATIAL INTELLIGENCE

              ┌───────────────────┐
              │                   │
              │   3D NETWORK      │
              │      TWIN         │
              │                   │
              └───────────────────┘

              127 devices mapped

                 Explore Twin →


────────────────────────────────────────────────

                 DEVICE INTELLIGENCE

       Android       Windows       Apple
          31            54           17


────────────────────────────────────────────────

                  RECENT ACTIVITY

  12:42   New device discovered
  12:39   Client connected
  12:37   Device localized
  12:31   Suspicious activity detected
```

The application should feel like a **single intelligent system** where discovery, devices, clients, locations, alerts, classification, and 3D visualization continuously reinforce one another.

---

# 34. Success Criteria

The redesign is successful when:

* [ ] The entire application uses the new visual language.
* [ ] The old UI does not simply appear recolored.
* [ ] Navigation is intuitive.
* [ ] Pages feel connected rather than isolated.
* [ ] The 3D Network Twin has significantly more visual importance.
* [ ] Device → Location → Client → Alert relationships are obvious.
* [ ] Device classification is naturally integrated.
* [ ] Important actions are easy to discover.
* [ ] Technical details remain accessible.
* [ ] The dashboard communicates system state immediately.
* [ ] Responsive behavior works correctly.
* [ ] Existing functionality remains intact.
* [ ] Components are reusable.
* [ ] Colors and typography are consistent.
* [ ] The interface feels like a coherent enterprise product rather than a collection of technical modules.

## Most Important Instruction

**Treat this as a complete product redesign, not a CSS recoloring exercise.**

Before modifying individual pages, understand the existing application, identify its current navigation and feature relationships, and then establish a new design system and information architecture.

The result should make the user feel:

> **"I'm looking at my entire network as one intelligent, spatially-aware system."**

rather than:

> **"I'm navigating between a collection of separate admin pages."**
