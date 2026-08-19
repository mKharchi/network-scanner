# Network Monitoring Client --- Graphical Interface Implementation Plan

## 1. Objective

The next stage of the project is to build the graphical interface for
the network monitoring system.

Before implementing any UI, the IDE AI must first understand the
existing project completely.

The goal is **not** to immediately start creating screens.

The first goal is to:

1.  Inspect the entire project.
2.  Understand all existing functionality.
3.  Identify what information is already available.
4.  Identify what can be displayed in the GUI.
5.  Decide where each feature belongs.
6.  Define the navigation and page structure.
7.  Define the data required by each screen.
8.  Only then begin implementing the interface step by step.

Do not invent functionality that does not exist in the project unless it
is explicitly identified as a future feature.

------------------------------------------------------------------------

# Phase 1 --- Full Project Audit

## Step 1. Inspect the project structure

Go through the complete project structure.

Identify:

-   server application
-   client application
-   shared modules
-   configuration
-   database
-   API/socket communication
-   authentication
-   background tasks
-   logging
-   alert system
-   network discovery
-   DHCP listener
-   activity monitoring
-   process monitoring
-   existing frontend/UI code, if any
-   tests
-   documentation

Produce a concise project map.

Do not modify code during this step.

## Step 2. Inventory existing functionality

For every feature, document:

-   feature name
-   where it is implemented
-   client or server
-   data it produces
-   how data reaches the server
-   whether data is persisted
-   existing API/message
-   whether it is ready for GUI display

Inspect at minimum:

### Client management

-   registration
-   identification
-   connection status
-   client IP
-   client metadata
-   disconnection
-   commands

### Activity monitoring

-   available activity logs
-   supported periods
-   collected information
-   storage
-   transfer mechanism

### Alerts

-   alert types
-   fields
-   severity
-   timestamps
-   deduplication
-   storage
-   retrieval

### Network discovery

-   ARP/neighbour discovery
-   OUI/vendor lookup
-   hostname resolution
-   mDNS
-   DHCP passive observation
-   network neighbour messages

Determine exactly which fields are currently available.

### Unmanaged devices

-   managed-device identification
-   unmanaged-device identification
-   persistence
-   history
-   current presence

### Logs

-   application logs
-   client logs
-   activity logs
-   network discovery logs
-   alert logs
-   storage location

Do not assume functionality that is not present.

------------------------------------------------------------------------

# Phase 2 --- Understand the Data Flow

Document how information moves through the system.

For example:

``` text
Client
  ├── Activity monitoring → Logs → Server
  ├── ARP discovery → Neighbours → Server
  ├── DHCP listener → Device information → Server
  └── Alerts → Server

Server
  ↓
Storage
  ↓
API / socket layer
  ↓
GUI
```

Document the actual flow found in the project.

Identify which data is:

-   real-time
-   periodically reported
-   requested on demand
-   persisted
-   only available locally on a client

------------------------------------------------------------------------

# Phase 3 --- Inspect the Existing UI Technology

Determine whether a frontend already exists.

Inspect:

-   framework
-   entry point
-   routing
-   components
-   styling
-   state management
-   API client
-   socket integration
-   authentication
-   layouts

If a frontend exists, extend it.

Do not replace the framework without a strong reason.

If no frontend exists, determine the most appropriate architecture based
on the existing project before adding dependencies.

------------------------------------------------------------------------

# Phase 4 --- Define the Operator's Main Questions

The UI should answer practical questions such as:

### Network

-   How many devices are connected?
-   How many are managed?
-   How many are unmanaged?
-   Are there suspicious devices?
-   Are there recent alerts?

### Managed clients

-   Which clients are online?
-   Which are offline?
-   What information is available for each?
-   What alerts/activity belong to each client?

### Unmanaged devices

-   Which devices have no client?
-   When were they last seen?
-   What IP/MAC do they have?
-   What hostname was detected?
-   What vendor was detected?
-   What OS information is available?
-   What DHCP information is available?
-   How was the device discovered?

### Alerts

-   What happened?
-   When?
-   Which device caused it?
-   What is the severity?
-   What is its current status?

### History

-   When was a device first seen?
-   When was it last seen?
-   How often did it appear?
-   What changed over time?

Only include questions that can be supported by existing or explicitly
planned backend data.

------------------------------------------------------------------------

# Phase 5 --- Establish the Information Architecture

Before coding, propose the application's navigation.

A possible starting point is:

``` text
Dashboard
Devices
  ├── Managed
  └── Unmanaged
Network
  ├── Live Devices
  ├── Discovery
  └── Scan History
Alerts
Activity
Settings
```

This is only a proposal.

Inspect the actual project and recommend the final structure.

For every page, explain its responsibility and what information belongs
there.

------------------------------------------------------------------------

# Phase 6 --- Map Existing Functionality to UI

Create a table like:

  ----------------------------------------------------------------------------
  Functionality   UI Location    Main Data       Backend        Status
                                                 Support        
  --------------- -------------- --------------- -------------- --------------
  Client status   Dashboard /    status          Yes/No         Existing
                  Devices                                       

  Network devices Network        IP/MAC/etc.     Yes/No         Existing

  DHCP            Device details DHCP metadata   Yes/No         Existing
  discoveries                                                   

  Alerts          Alerts         alert records   Yes/No         Existing

  Activity logs   Activity /     logs            Yes/No         Existing
                  Device details                                

  Scan history    Network        observations    Yes/No         Existing

  Settings        Settings       configuration   Yes/No         Existing
  ----------------------------------------------------------------------------

Fill this from the actual project.

Do not guess.

------------------------------------------------------------------------

# Phase 7 --- Define the Dashboard

The dashboard should provide an operational overview, not every detail.

Determine which statistics are actually available.

Potential elements:

``` text
Managed Devices
Unmanaged Devices
Online Devices
Offline Devices
Active Alerts
Devices Detected Today
Recent Alerts
Recently Detected Devices
```

Only create charts when real data supports them.

Avoid decorative charts with no operational value.

------------------------------------------------------------------------

# Phase 8 --- Define Device Views

Separate:

## Managed devices

Potential information:

-   device name
-   IP
-   MAC
-   OS
-   client status
-   last seen
-   alerts
-   activity

## Unmanaged devices

Potential information:

-   IP
-   MAC
-   hostname
-   vendor
-   OS
-   DHCP information
-   discovery source
-   first seen
-   last seen
-   presence history

The exact fields must come from the project audit.

------------------------------------------------------------------------

# Phase 9 --- Define Device Details

The device details page should answer:

> What do we know about this device?

Possible structure:

``` text
Device Header
    ↓
Identity
    ↓
Network Information
    ↓
Detection Sources
    ↓
Presence History
    ↓
Alerts
    ↓
Activity / Logs
```

Use sections or tabs where appropriate.

Do not overload the page.

------------------------------------------------------------------------

# Phase 10 --- Define Network Monitoring

The network page should focus on current network state.

Potential information:

-   current devices
-   managed/unmanaged status
-   IP
-   MAC
-   hostname
-   vendor
-   OS
-   discovery source
-   last seen

Potential filters:

``` text
All
Managed
Unmanaged
Online
Recently detected
```

Only implement filters supported by the backend.

------------------------------------------------------------------------

# Phase 11 --- Define Alerts

Inspect the existing alert system first.

### Alert list

Potential fields:

-   severity
-   type
-   message
-   device
-   timestamp
-   status

### Alert details

Potential fields:

-   what happened
-   affected device
-   timestamp
-   reason
-   related information

Reuse the existing alert system.

Do not create a separate alert model for the GUI.

------------------------------------------------------------------------

# Phase 12 --- Define Activity / Logs

Inspect the existing activity logs and determine their actual types.

Possible organization:

``` text
Activity
├── All activity
├── By device
└── By log type
```

Device details may expose:

``` text
Device
  └── Activity
      ├── Browser history
      ├── Shell commands
      ├── Processes
      └── Other existing logs
```

Use the real log types found in the project.

Keep the existing log-storage architecture.

------------------------------------------------------------------------

# Phase 13 --- Define Scan History

If scan history exists, expose it clearly.

Potential fields:

``` text
Started
Completed
Duration
Devices discovered
Managed
Unmanaged
Status
```

A scan details view can show:

``` text
Scan
 ↓
Devices observed
```

------------------------------------------------------------------------

# Phase 14 --- Real-Time vs Refresh-Based Data

Determine which information should update automatically.

Potential real-time data:

-   client connection status
-   new alerts
-   DHCP discoveries
-   new network devices

Potential refresh-based data:

-   historical logs
-   previous scans
-   device history
-   reports

Inspect the existing socket architecture before introducing new
real-time infrastructure.

------------------------------------------------------------------------

# Phase 15 --- UI States

Every screen must handle:

### Loading

``` text
Loading...
```

### Empty

``` text
No unmanaged devices detected.
```

### Error

``` text
Unable to load network devices.
Retry
```

### Connection loss

``` text
Server connection lost.
```

### Partial data

For example:

``` text
Hostname: Unknown
OS: Unknown
Vendor: Xiaomi
```

Do not hide devices because enrichment data is missing.

------------------------------------------------------------------------

# Phase 16 --- Establish the Design System

Before implementing many pages, establish consistency for:

-   typography
-   spacing
-   colors
-   cards
-   tables
-   badges
-   buttons
-   navigation
-   dialogs
-   alerts
-   status indicators
-   loading states
-   empty states

Prioritize:

``` text
Clarity
Readability
Operational visibility
Consistency
```

Avoid excessive decoration and unnecessary animation.

------------------------------------------------------------------------

# Phase 17 --- Build the Application Shell First

Implement the shared layout before individual pages.

Possible structure:

``` text
┌─────────────────────────────────────────┐
│ Header                                  │
├────────────┬────────────────────────────┤
│ Sidebar    │                            │
│            │       Main Content         │
│ Dashboard  │                            │
│ Devices    │                            │
│ Network    │                            │
│ Alerts     │                            │
│ Activity   │                            │
│ Settings   │                            │
└────────────┴────────────────────────────┘
```

Adapt it to the actual requirements.

------------------------------------------------------------------------

# Phase 18 --- Implementation Order

## Milestone 1 --- Project Audit

-   [ ] Inspect complete project
-   [ ] Map architecture
-   [ ] Inventory functionality
-   [ ] Identify data sources
-   [ ] Identify APIs/socket messages
-   [ ] Identify missing backend support
-   [ ] Identify frontend technology

## Milestone 2 --- Information Architecture

-   [ ] Define navigation
-   [ ] Define pages
-   [ ] Define sections
-   [ ] Assign functionality to pages
-   [ ] Define page responsibilities

## Milestone 3 --- Data Contracts

For every page define:

-   [ ] required endpoint/message
-   [ ] request parameters
-   [ ] response structure
-   [ ] loading state
-   [ ] empty state
-   [ ] error state

Do this before connecting the UI.

## Milestone 4 --- Design System

-   [ ] typography
-   [ ] colors
-   [ ] spacing
-   [ ] buttons
-   [ ] cards
-   [ ] tables
-   [ ] badges
-   [ ] dialogs
-   [ ] navigation
-   [ ] status indicators

## Milestone 5 --- Application Shell

-   [ ] layout
-   [ ] sidebar
-   [ ] header
-   [ ] routing
-   [ ] responsive behavior
-   [ ] global connection state

## Milestone 6 --- Dashboard

-   [ ] summary cards
-   [ ] recent alerts
-   [ ] network overview
-   [ ] recent devices
-   [ ] useful statistics

## Milestone 7 --- Devices

-   [ ] managed devices
-   [ ] unmanaged devices
-   [ ] filtering
-   [ ] search
-   [ ] device details

## Milestone 8 --- Network

-   [ ] current devices
-   [ ] discovery information
-   [ ] scan history
-   [ ] scan details

## Milestone 9 --- Alerts

-   [ ] alert list
-   [ ] filtering
-   [ ] details
-   [ ] severity indicators
-   [ ] acknowledgement/status if supported

## Milestone 10 --- Activity

-   [ ] activity list
-   [ ] device-specific activity
-   [ ] existing log types
-   [ ] log references/files

## Milestone 11 --- Real-Time Updates

-   [ ] client status
-   [ ] network discovery
-   [ ] DHCP discovery
-   [ ] alert updates

Implement this only after the basic UI works.

## Milestone 12 --- Testing and Polish

-   [ ] UI tests
-   [ ] integration tests
-   [ ] loading states
-   [ ] empty states
-   [ ] error states
-   [ ] responsive layout
-   [ ] accessibility
-   [ ] performance
-   [ ] visual consistency

------------------------------------------------------------------------

# Phase 19 --- Rules for the IDE AI

## Rule 1 --- Inspect before modifying

Do not start coding immediately.

First produce the project audit.

## Rule 2 --- Reuse existing functionality

Do not duplicate:

-   models
-   socket messages
-   APIs
-   authentication
-   alert mechanisms
-   logging systems

## Rule 3 --- Do not invent backend data

If the UI requires data that does not exist:

``` text
Identify missing data
        ↓
Identify where it should come from
        ↓
Propose the smallest backend change
        ↓
Implement it as a separate step
```

Do not use fake data to make the UI appear complete.

## Rule 4 --- One milestone at a time

After every milestone:

1.  Explain what changed.
2.  List modified files.
3.  List created files.
4.  Explain the implementation.
5.  Run relevant tests/build/lint.
6.  Report failures.
7.  Stop before moving to the next major milestone.

## Rule 5 --- Preserve the current architecture

Do not rewrite working backend/client functionality just to accommodate
the GUI.

The GUI should integrate with the existing system.

------------------------------------------------------------------------

# First Task for the IDE AI

**Do not implement the GUI yet.**

Start with **Phase 1 --- Full Project Audit**.

Produce a report containing:

1.  Complete project structure.
2.  Client architecture.
3.  Server architecture.
4.  Communication architecture.
5.  Database/storage architecture.
6.  Existing monitoring features.
7.  Existing network discovery features.
8.  Existing DHCP functionality.
9.  Existing alert functionality.
10. Existing log/activity functionality.
11. Existing frontend/UI functionality.
12. All data currently available for display.
13. Existing APIs/socket messages relevant to the GUI.
14. Missing backend functionality required by the UI.
15. Recommended information architecture.
16. Recommended navigation.
17. Recommended page list.

**Do not start implementing pages until this audit and proposed
information architecture are complete.**

The next step will be to review the audit and decide exactly what goes
where before writing the first UI component.
