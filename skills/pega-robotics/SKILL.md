---
name: pega-robotics
description: Use when working with Pega Intelligent Automation — Pega Robot Studio (RPA development, automations, components, adapters, UI interrogation), Pega Robot Runtime (attended/unattended execution, runtime configuration), Pega Robot Manager (robot fleet management, deployment, scheduling, monitoring, work queues, analytics), automation design patterns, credential management, error handling, and integration with Pega Platform (case management, decisioning). Part of the pega-* skill family.
---

# Pega Intelligent Automation — Robotics

Covers the full Pega RPA stack: Robot Studio (development), Robot Runtime (execution), and Robot Manager (fleet management). For Pega Platform case management and decisioning there is no dedicated skill yet — answer from general knowledge, or use `web-research` for current Pega Platform documentation.

<HARD-RULE>
Never hard-code credentials in automations — always use the credential vault with per-environment overrides. Hard-coded credentials create security vulnerabilities, break across environments, and make rotation impossible.
</HARD-RULE>

<HARD-RULE>
Always implement explicit wait conditions instead of fixed sleep delays — sleep-based automations break with application performance variation. Use WaitForControl, WaitForProperty, or WaitForScreen with appropriate timeouts instead.
</HARD-RULE>

<HARD-RULE>
Never rely solely on image recognition when text-based interrogation is available — image recognition is fragile across resolution/DPI/theme changes. Prefer control-based identification (Win32, UIA, MSAA, HTML selectors) and reserve image recognition only for Citrix/RDP scenarios where no alternative exists.
</HARD-RULE>

<HARD-RULE>
Always design automations as idempotent operations — robots may be interrupted and restarted mid-execution, so partial completion must not corrupt data. Use status checks before actions, implement compensation logic, and ensure re-running the same work item produces the same result.
</HARD-RULE>

---

## 1. Robot Studio Overview

Robot Studio is the Windows desktop IDE for developing Pega RPA automations. It provides a visual drag-and-drop design surface, component library, adapter framework for target application connectivity, and debugging/testing tools.

### Project Structure

```
MyRPAProject/
├── Automations/           # Top-level orchestration flows
│   ├── ProcessInvoice.auto
│   └── UpdateCRM.auto
├── Components/            # Reusable building blocks
│   ├── Login_SAP.comp
│   ├── ExtractTableData.comp
│   └── NavigateToScreen.comp
├── Adapters/              # Target application connectors
│   ├── WebApp_Chrome.adapter
│   ├── SAPGui.adapter
│   └── Mainframe3270.adapter
├── GlobalVariables/       # Shared configuration
├── References/            # External assembly references
└── Project.rsproj         # Project file (XML-based)
```

### Key Concepts

| Concept | Description |
|---|---|
| **Automation** | Top-level orchestration — sequences components, handles high-level error flow, manages the end-to-end process. Deployed as a unit to Robot Manager. |
| **Component** | Reusable building block — encapsulates a discrete task (login, extract data, fill form). Has defined inputs/outputs. Shareable across automations. |
| **Adapter** | Connector to a target application — provides interrogation (control discovery) and interaction (click, type, read) capabilities for a specific technology (Web, Win32, Java, SAP, Terminal, Citrix). |
| **Interrogation** | Process of identifying UI controls in the target application — captures control properties (Name, ClassName, AutomationId, XPath) to build reliable selectors. |
| **Project** | Container for automations, components, adapters, and shared resources. Compiles into a deployment package (.zip) for Robot Manager. |

### Automation vs Component

- **Automations** orchestrate the process — they call components in sequence, handle top-level exceptions, manage process state, and are the deployable unit.
- **Components** do the work — they interact with target applications through adapters, are independently testable, and are reusable across multiple automations.
- Rule of thumb: if you would copy-paste a section of logic, extract it into a component.

---

## 2. Automation Design

### Automation Flow Structure

A well-structured automation follows this pattern:

```
Initialize
├── Load configuration (environment-specific)
├── Retrieve credentials from vault
├── Launch/attach to target applications
├── Validate prerequisites (app version, screen state)
│
Main Processing
├── Get work item from queue (or input parameters)
├── FOR EACH work item:
│   ├── Navigate to starting screen
│   ├── Process item (call components)
│   ├── Validate result
│   ├── Update work item status (completed/failed)
│   └── Log outcome
│
Cleanup
├── Close/detach target applications
├── Release credentials
└── Report summary (items processed, failed, skipped)
```

### Component Design Principles

- **Single Responsibility** — one component does one thing (e.g., "Login to SAP", not "Login to SAP and navigate to transaction and extract data").
- **Defined Contract** — every component declares explicit input and output parameters with types.
- **Adapter Independence** — components reference adapters by logical name, not hard-coded paths. This allows adapter swapping between environments.
- **Error Propagation** — components should throw typed exceptions, not silently swallow errors. Let the calling automation decide how to handle failures.

### Adapter Types

| Adapter | Target Technology | Identification Method |
|---|---|---|
| **Web** | Chrome, Edge, Firefox, IE | CSS selectors, XPath, HTML attributes (id, name, class, data-*) |
| **Windows (Win32)** | Native Windows applications | Window class, control name, AutomationId, UI Automation tree |
| **Java** | Java Swing/AWT/SWT applications | Java Access Bridge, component hierarchy, role/name |
| **SAP** | SAP GUI for Windows | SAP GUI scripting API, transaction codes, field IDs |
| **Terminal** | 3270/5250 mainframe | Screen position (row/col), field labels, screen title matching |
| **Citrix/RDP** | Remote desktop sessions | Image recognition, OCR, coordinate-based (last resort) |

---

## 3. Component Development

### Design Surface

Robot Studio's visual designer presents components as flowchart-like diagrams with:

- **Start** — entry point, defines input parameters.
- **End** — exit point, defines output parameters.
- **Steps** — actions (click, type, read, set variable, call component).
- **Decisions** — conditional branches (if/else, switch).
- **Loops** — iteration (for each, while, do-while).
- **Error Handling** — try/catch/finally blocks.
- **Connectors** — flow control arrows between elements.

### Variable Management

| Scope | Description | Use Case |
|---|---|---|
| **Local** | Visible only within the current component | Temporary calculations, loop counters |
| **Input** | Passed into the component by the caller | Account number, search criteria |
| **Output** | Returned to the caller when the component completes | Extracted data, status codes |
| **Global** | Shared across all components in the automation | Configuration values, session handles |

### Data Types

```
String          — text values
Integer         — whole numbers (Int32)
Long            — large whole numbers (Int64)
Double          — decimal numbers
Boolean         — true/false
DateTime        — date and time values
DataTable       — tabular data (rows and columns)
List<T>         — typed collections
Object          — generic (avoid when possible — prefer typed)
SecureString    — encrypted credential values
```

### Expressions and VB.NET Snippets

Robot Studio uses VB.NET syntax for expressions in steps and decisions:

```vb
' String manipulation
result = AccountNumber.Trim().Substring(0, 8).ToUpper()

' Date formatting
formattedDate = DateTime.Now.ToString("yyyy-MM-dd")

' Null/empty checks (common in decisions)
Not String.IsNullOrEmpty(CustomerName)

' DataTable row access
cellValue = MyTable.Rows(rowIndex)("ColumnName").ToString()

' Collection operations
itemCount = MyList.Count
exists = MyList.Contains("SearchValue")

' Type conversion
amount = CDbl(amountString.Replace(",", ""))
intValue = CInt(textValue)

' Regex matching
Dim match As Boolean = System.Text.RegularExpressions.Regex.IsMatch(input, "^\d{8}$")
```

### Collections — DataTable Operations

```vb
' Create a DataTable
Dim dt As New DataTable()
dt.Columns.Add("Name", GetType(String))
dt.Columns.Add("Amount", GetType(Double))

' Add rows
dt.Rows.Add("Invoice001", 1500.00)

' Filter rows
Dim filtered() As DataRow = dt.Select("Amount > 1000")

' Sort
Dim view As New DataView(dt)
view.Sort = "Amount DESC"

' Loop (in the designer, use a For Each loop step targeting DataRow)
For Each row As DataRow In dt.Rows
    Dim name As String = row("Name").ToString()
Next
```

---

## 4. Adapters & Interrogation

### Web Adapter (Chrome / Edge / Firefox)

The Web adapter connects to browsers via native messaging extensions. It provides full DOM access for control identification.

**Interrogation strategies (in order of preference):**

1. **ID attribute** — `#submitButton` — most stable, survives layout changes.
2. **data-* attributes** — `[data-testid="login-btn"]` — designed for automation, framework-agnostic.
3. **Name attribute** — `[name="username"]` — stable for form fields.
4. **CSS selector** — `div.modal-content > form > input:nth-child(2)` — flexible but fragile if DOM restructures.
5. **XPath** — `//table[@id='results']//tr[3]/td[2]` — powerful for complex traversal, but verbose and brittle.

**Common operations:**

```
SetValue        — type text into an input field
Click           — click a button/link/element
GetValue        — read text from an element
GetAttribute    — read an HTML attribute value
GetTable        — extract an HTML table into a DataTable
WaitForControl  — wait until an element appears in the DOM
ExecuteScript   — run JavaScript in the browser context
SelectItem      — choose from a dropdown (by text/value/index)
```

**Browser extension requirement:** Each target browser needs the Pega Robot Studio browser extension installed and enabled. Chrome and Edge (Chromium) use the same extension. Firefox uses a separate extension.

### Windows Adapter (Win32 / UI Automation / MSAA)

Connects to native Windows applications using the UI Automation (UIA) framework, with fallback to MSAA and raw Win32 messaging.

**Identification hierarchy:**

1. **AutomationId** — assigned by the developer, most reliable.
2. **Name** — visible text label or accessible name.
3. **ClassName** — Win32 window class (e.g., `Edit`, `Button`, `SysListView32`).
4. **ControlType** — UIA control type (Button, Edit, DataGrid, TreeItem).
5. **Window title + child index** — last resort, positional.

**Diagnostics:** Use the Interrogation Spy tool (magnifying glass icon) to inspect live control trees. Compare with Windows Accessibility Insights or Inspect.exe for verification.

### SAP Adapter

Connects through the SAP GUI Scripting API. Requires SAP GUI Scripting to be enabled on both the SAP application server (`sapgui/user_scripting = TRUE` in profile parameter `rdisp/gui_comp_level`) and the local SAP GUI client.

**Key operations:**

```
SetField        — populate a SAP GUI field by technical name (e.g., "usr/txtRSYST-BNAME")
GetField        — read a field value
PressButton     — activate a SAP GUI button
SelectNode      — navigate tree controls
RunTransaction  — execute a transaction code (e.g., "VA01", "ME21N")
GetStatusBar    — read the SAP status bar message (type + text)
ReadGridView    — extract ALV grid data into a DataTable
```

**Field identification:** Use SAP GUI's built-in script recorder (Alt+F12 → Script Recording) or Robot Studio's SAP Interrogation mode to discover field technical names.

### Terminal Adapter (3270 / 5250 Mainframe)

Connects to mainframe terminal sessions via terminal emulators (IBM Personal Communications, Micro Focus Rumba, HLLAPI-compatible emulators).

**Identification:** Position-based using row and column coordinates. Screen identification uses title fields or unique text at known positions.

```
SetField(row, col, value)    — type text at a screen position
GetField(row, col, length)   — read text from a screen position
SendKey(key)                 — send a terminal key (Enter, PF1-PF24, Tab, Clear)
WaitForScreen(identifier)    — wait for a specific screen to appear
GetScreenText()              — capture entire screen as text
```

**Screen navigation pattern:**

```
1. WaitForScreen("MAIN MENU")         — verify starting screen
2. SetField(21, 7, "3")               — type option number
3. SendKey(Keys.Enter)                 — submit
4. WaitForScreen("CUSTOMER INQUIRY")  — verify target screen loaded
5. SetField(5, 22, customerNumber)     — populate search field
6. SendKey(Keys.Enter)                 — execute search
7. WaitForField(8, 22, isNotEmpty)     — wait for results
```

### Citrix / RDP Adapter

Used when the target application runs in a remote session where direct control-tree access is unavailable. This is the adapter of last resort.

**Capabilities:**

- **Image recognition** — locate UI elements by matching bitmap templates (buttons, icons, text regions).
- **OCR** — read text from screen regions using built-in or external OCR engines.
- **Coordinate-based clicks** — click at pixel positions relative to anchors.
- **Keyboard simulation** — send keystrokes to the remote session.

**Mitigations for fragility:**

- Pin display resolution, DPI scaling, color depth, and Windows theme on the Citrix/RDP host.
- Use anchored regions (relative to a stable reference point) rather than absolute coordinates.
- Implement generous wait conditions with image-based screen verification.
- Maintain separate image libraries per environment if UI differs.
- Prefer OCR text matching over image matching where possible.

---

## 5. Error Handling & Resilience

### Try/Catch Pattern

Every component and automation should use structured error handling:

```
TRY
├── Navigate to screen
├── Fill form fields
├── Submit
├── WaitForControl("ConfirmationMessage", timeout: 30s)
│
CATCH (ElementNotFoundException)
├── Take screenshot
├── Log "Target control not found — UI may have changed"
├── Throw (propagate to automation for work-item-level handling)
│
CATCH (TimeoutException)
├── Take screenshot
├── Check if application is responding (WaitForControl with short timeout)
├── IF application frozen:
│   ├── Kill and restart application
│   └── Throw RetryableException
├── ELSE:
│   └── Throw (non-recoverable)
│
CATCH (Exception)    — generic catch-all, always last
├── Take screenshot
├── Log full exception details (type, message, stack trace)
├── Throw (never silently swallow)
│
FINALLY
├── Reset to known state (navigate to home screen)
└── Release any locks held
```

### Wait Conditions

| Method | Use Case | Example |
|---|---|---|
| `WaitForControl` | Wait for a UI element to appear | Wait for a success banner after form submission |
| `WaitForProperty` | Wait for a control property to reach a value | Wait for a button's `Enabled` property to become `True` |
| `WaitForScreen` | Wait for a terminal screen to load | Wait for mainframe screen title to match |
| `WaitForControlVanish` | Wait for a control to disappear | Wait for a loading spinner to vanish |
| `WaitForImage` | Wait for a bitmap to appear on screen | Citrix/RDP — wait for a dialog to render |

All wait methods accept a `timeout` parameter (in seconds). Always set explicit timeouts — the default may be too short for slow applications or too long for responsive ones.

**Anti-pattern — fixed sleep:**
```
❌  Sleep(5000)                                    — arbitrary, wastes time or breaks
✅  WaitForControl("ResultGrid", timeout: 30)      — precise, adapts to app speed
```

### Retry Logic

Implement retry at the work-item level, not inside individual steps:

```
FOR EACH workItem IN queue:
    retryCount = 0
    maxRetries = 3

    WHILE retryCount < maxRetries:
        TRY:
            ProcessWorkItem(workItem)
            MarkCompleted(workItem)
            BREAK    — success, exit retry loop
        CATCH RetryableException:
            retryCount += 1
            Log("Retry {retryCount}/{maxRetries} for {workItem.Id}")
            ResetApplicationState()
            IF retryCount >= maxRetries:
                MarkFailed(workItem, "Exceeded max retries")
        CATCH NonRetryableException:
            MarkFailed(workItem, exception.Message)
            BREAK    — no point retrying
```

### Screenshot on Failure

Always capture a screenshot when an exception occurs — it is the most valuable diagnostic artifact for RPA failures:

```
CATCH (Exception ex)
    screenshotPath = "C:\RobotLogs\Screenshots\" +
                     DateTime.Now.ToString("yyyyMMdd_HHmmss") +
                     "_" + workItemId + ".png"
    TakeScreenshot(screenshotPath)
    Log.Error("Failed processing " + workItemId, ex, screenshotPath)
    THROW
```

---

## 6. Design Patterns

### Page Object Model (POM)

Abstract the UI layer from business logic — just as in test automation:

```
Component: SAP_LoginPage
├── Inputs: username (String), password (SecureString)
├── Outputs: isLoggedIn (Boolean)
├── Methods:
│   ├── EnterUsername(username)     — SetField("usr/txtRSYST-BNAME", username)
│   ├── EnterPassword(password)    — SetField("usr/pwdRSYST-BCODE", password)
│   ├── ClickLogin()               — PressButton("btn[0]")
│   └── IsOnMainMenu() → Boolean  — GetStatusBar().Type != "E"

Component: SAP_TransactionVA01
├── Inputs: orderData (DataTable)
├── Outputs: orderNumber (String)
├── Methods:
│   ├── NavigateToTransaction()    — RunTransaction("VA01")
│   ├── FillHeader(...)
│   ├── AddLineItems(orderData)
│   └── SaveAndGetOrderNumber() → String
```

Benefits: when SAP screens change (field IDs, layout), you update only the page component — the calling automation is untouched.

### Configuration-Driven Automations

Externalize environment-specific values — never embed them in automation logic:

```
Configuration values (stored in Robot Manager or external config):
├── TargetURL           = "https://crm.prod.company.com"
├── MaxRetries          = 3
├── TimeoutSeconds      = 30
├── ReportEmailAddress  = "rpa-team@company.com"
├── SAPSystemId         = "PRD"
├── SAPClient           = "100"
└── LogLevel            = "Info"
```

Load configuration at automation start. Components receive config values as input parameters — they never read config directly.

### Logging Best Practices

```
Log levels:
├── DEBUG   — control-level detail (clicked button X, read value Y) — dev/test only
├── INFO    — business milestones (processing item 42, invoice created)
├── WARN    — recoverable issues (retry triggered, fallback used)
├── ERROR   — failures (exception details, screenshot path)
└── FATAL   — automation cannot continue (application crash, credential failure)

Every log entry should include:
├── Timestamp (UTC)
├── Automation name
├── Component name
├── Work item ID (if applicable)
├── Robot machine name
└── Message with context
```

### Modular Component Design

Structure components in layers:

```
Layer 1 — Adapters (technology coupling)
├── Web_Chrome.adapter
├── SAPGui.adapter
└── Terminal3270.adapter

Layer 2 — Page Components (UI abstraction)
├── CRM_LoginPage.comp
├── CRM_SearchCustomer.comp
├── SAP_CreateOrder.comp
└── Mainframe_AccountInquiry.comp

Layer 3 — Business Components (process logic)
├── ValidateInvoiceData.comp
├── CalculateDiscount.comp
└── FormatOutputReport.comp

Layer 4 — Automations (orchestration)
├── ProcessInvoice.auto        — calls Layer 2 + 3 components
└── ReconcileAccounts.auto
```

### Data-Driven Automation

Separate test/process data from automation logic:

```
Input sources:
├── Work queues (Robot Manager)     — preferred for production
├── Excel/CSV files                  — batch processing
├── Database queries                 — dynamic data sets
├── API responses                    — real-time integration
└── Pega case data                  — platform integration

Pattern:
1. Read all input records into a DataTable
2. Validate each record before processing (schema, required fields, format)
3. Process valid records, skip and report invalid ones
4. Write results back to source (queue status, output file, API callback)
```

---

## 7. Robot Manager Architecture

Robot Manager is the web-based management console for the Pega RPA fleet. It runs on the Pega Platform application server and provides centralized control over robot agents, deployments, work queues, schedules, and monitoring.

### Architecture Overview

```
┌─────────────────────────────────────────────────┐
│              Pega Platform Server                │
│  ┌───────────────────────────────────────────┐  │
│  │           Robot Manager                    │  │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────┐ │  │
│  │  │Deployment│ │  Work    │ │ Scheduling│ │  │
│  │  │ Manager  │ │  Queues  │ │  Engine   │ │  │
│  │  └──────────┘ └──────────┘ └───────────┘ │  │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────┐ │  │
│  │  │ Fleet    │ │Analytics │ │ Credential│ │  │
│  │  │ Monitor  │ │Dashboard │ │  Vault    │ │  │
│  │  └──────────┘ └──────────┘ └───────────┘ │  │
│  └───────────────────────────────────────────┘  │
└───────────────────────┬─────────────────────────┘
                        │ HTTPS
        ┌───────────────┼───────────────┐
        │               │               │
   ┌────▼────┐    ┌─────▼────┐   ┌─────▼────┐
   │ Robot   │    │ Robot    │   │ Robot    │
   │ Agent 1 │    │ Agent 2  │   │ Agent 3  │
   │(Attended)│   │(Unattend)│   │(Unattend)│
   │ Desktop  │   │  VM 1    │   │  VM 2    │
   └──────────┘   └──────────┘   └──────────┘
```

### Environment Hierarchy

```
Organization
└── Environment
    ├── Development    — Robot Studio connected, debugging enabled
    ├── Test/QA        — pre-production validation, test queues
    └── Production     — live execution, full monitoring
```

Each environment has its own Robot Manager instance (or tenant), credential vault entries, configuration sets, and robot agents.

### RBAC — Roles

| Role | Permissions |
|---|---|
| **Administrator** | Full access — manage environments, users, credentials, global configuration |
| **Manager** | Manage automations, deployments, queues, schedules, view analytics |
| **Operator** | View robot status, trigger attended automations, view own queue items |

---

## 8. Robot Fleet Management

### Robot Agent Registration

Each machine running automations requires a Robot Runtime agent registered with Robot Manager:

1. Install Pega Robot Runtime on the target machine (Windows desktop or VM).
2. Configure the agent to connect to Robot Manager (server URL, port, TLS certificate).
3. Register the agent in Robot Manager — assign a name, group, and mode (attended/unattended).
4. Verify connectivity — agent status should show as "Connected" in the fleet dashboard.

### Attended vs Unattended Modes

| Aspect | Attended | Unattended |
|---|---|---|
| **Trigger** | User-initiated (system tray, hotkey, Pega case) | Schedule, queue, API, or event trigger |
| **User session** | Runs alongside the user on their desktop | Runs on a locked/logged-in VM session (no user present) |
| **Interaction** | Can prompt the user for input mid-execution | Fully autonomous — no human prompts |
| **Use case** | Desktop assistance, guided data entry, real-time lookups | Batch processing, overnight jobs, high-volume work |
| **Machine** | User's workstation | Dedicated VM (one automation per VM at a time) |

### Robot Groups

Group robots by function, environment, or capacity:

```
Robot Groups:
├── Finance-Attended        — 50 user desktops, attended mode
├── Finance-Unattended      — 10 VMs, invoice processing
├── HR-Unattended           — 5 VMs, employee onboarding
└── IT-Unattended           — 3 VMs, account provisioning
```

Automations are assigned to groups, not individual robots. Robot Manager distributes work across available robots in the group.

### License Management

Robot Runtime licenses are consumed per concurrent agent connection. Monitor license usage in Robot Manager:

- **Active licenses** — currently connected agents.
- **Peak usage** — maximum concurrent agents in a period.
- **License pool** — total available licenses by type (attended/unattended).

---

## 9. Deployment Pipeline

### Package Creation (Robot Studio)

```
1. Build the project in Robot Studio (Build → Build Solution)
2. Resolve any compilation errors
3. Create a deployment package (Build → Create Package)
4. Package output: .zip file containing compiled automations, components, adapters, and dependencies
5. Version the package (follows semantic versioning: MAJOR.MINOR.PATCH)
```

### Deployment to Robot Manager

```
1. Upload the package to Robot Manager (Deployments → Upload Package)
2. Select target environment (dev/test/prod)
3. Assign to robot groups
4. Configure runtime parameters (if any)
5. Activate the deployment
6. Robot agents in the assigned group pull the new package on next check-in
```

### Version Management

- Robot Manager retains previous package versions.
- Only one version of an automation can be active per environment at a time.
- Agents running an older version complete their current execution before switching to the new version.

### Environment Promotion

```
Development                    Test/QA                      Production
┌──────────────┐   promote    ┌──────────────┐   promote   ┌──────────────┐
│ Package v1.3 │────────────►│ Package v1.3 │────────────►│ Package v1.3 │
│ Dev config   │             │ Test config  │             │ Prod config  │
│ Test queues  │             │ QA queues    │             │ Live queues  │
│ Dev creds    │             │ Test creds   │             │ Prod creds   │
└──────────────┘             └──────────────┘             └──────────────┘
```

Each environment uses its own configuration, credentials, and queue data. The automation package binary is identical across environments — only configuration changes.

### Rollback

If a deployment causes issues:

1. Deactivate the current package version.
2. Reactivate the previous version.
3. Agents pick up the rolled-back version on next check-in.
4. Active executions on the faulty version complete (or are terminated) before the rollback takes effect.

---

## 10. Work Queues

Work queues are the primary mechanism for distributing work items to unattended robots.

### Queue Structure

```
Queue: InvoiceProcessing
├── Properties:
│   ├── Name: InvoiceProcessing
│   ├── Description: Incoming invoices from AP mailbox
│   ├── Priority: Normal (1-10 scale, 10 = highest)
│   ├── SLA: 4 hours from creation
│   ├── Max retries: 3
│   └── Retry delay: 5 minutes
│
├── Work Item Fields:
│   ├── InvoiceNumber (String, required)
│   ├── VendorName (String, required)
│   ├── Amount (Decimal, required)
│   ├── DueDate (DateTime)
│   └── AttachmentPath (String)
```

### Work Item Lifecycle

```
        ┌──────┐
        │ New  │◄──── Item added to queue (API, case, manual)
        └──┬───┘
           │ Robot picks up item
        ┌──▼────────┐
        │In Progress │
        └──┬────┬───┘
           │    │
    success │    │ failure
           │    │
   ┌───────▼┐  ┌▼─────────┐
   │Complete│  │  Failed   │
   └────────┘  └──┬───────┘
                   │ retry policy
                   │ (if retries remaining)
               ┌───▼──┐
               │ New  │ — re-queued with incremented retry count
               └──────┘
```

### Work Item States

| State | Description |
|---|---|
| **New** | Awaiting processing — available for any robot in the assigned group |
| **In Progress** | Locked by a robot — other robots cannot pick it up |
| **Completed** | Successfully processed — includes output data and completion timestamp |
| **Failed** | Processing failed — includes error message, screenshot reference, retry count |
| **On Hold** | Manually paused — requires operator intervention to resume |

### Queue Operations from Automations

```
' Get next work item (called at automation start or in processing loop)
workItem = Queue.GetNext("InvoiceProcessing")

' Check if item was returned (queue may be empty)
IF workItem Is Nothing THEN
    Log.Info("Queue empty, exiting")
    EXIT
END IF

' Read work item data
invoiceNumber = workItem.GetField("InvoiceNumber")
amount = CDbl(workItem.GetField("Amount"))

' Process...

' Mark complete with output data
workItem.SetField("ProcessedBy", Environment.MachineName)
workItem.SetField("ERPReference", erpDocNumber)
workItem.MarkCompleted()

' Or mark failed
workItem.MarkFailed("Vendor not found in ERP system")
```

### Queue Monitoring

Key metrics to track per queue:

- **Backlog** — number of items in "New" state.
- **Throughput** — items completed per hour.
- **Failure rate** — percentage of items that failed after all retries.
- **Average processing time** — time from "In Progress" to "Completed".
- **SLA compliance** — percentage of items completed within the defined SLA.
- **Oldest item** — age of the longest-waiting item (indicates bottlenecks).

---

## 11. Scheduling

### Schedule Types

| Type | Trigger | Use Case |
|---|---|---|
| **Time-based** | Cron-like schedule (daily, hourly, specific times) | Nightly batch processing, hourly data sync |
| **Calendar-based** | Business calendar aware (skip holidays, weekends) | End-of-month reconciliation, business-day-only processing |
| **Trigger-based** | Event-driven (queue threshold, file arrival, API call) | Process items as they arrive, react to system events |
| **Manual** | Operator-initiated from Robot Manager console | Ad-hoc runs, testing, emergency processing |

### Schedule Configuration

```
Schedule: NightlyInvoiceProcessing
├── Automation: ProcessInvoice v2.1
├── Robot Group: Finance-Unattended
├── Frequency: Daily at 22:00 UTC
├── Business Calendar: US-Banking (skip federal holidays)
├── Concurrent limit: 5 robots max
├── Timeout: 4 hours (kill if exceeds)
├── Blackout windows:
│   ├── Last day of quarter: 18:00-06:00 (month-end close)
│   └── Maintenance windows: per IT calendar
├── On failure: Alert rpa-team@company.com
└── Enabled: Yes
```

### Concurrent Execution Limits

Set maximum concurrent robots per automation to prevent:

- Overwhelming target application servers.
- License conflicts on target applications (e.g., SAP GUI licenses).
- Database contention from parallel writes.

```
Concurrency planning:
├── Target app can handle 10 concurrent sessions → set limit to 8 (20% headroom)
├── Available unattended robots in group: 10
├── Available target app licenses: 15
└── Effective concurrency: min(8, 10, 15) = 8
```

### Blackout Windows

Prevent automation execution during:

- System maintenance windows.
- Month-end/quarter-end close periods.
- Peak user hours (for attended robots that share resources).
- Deployment windows.

---

## 12. Monitoring & Analytics

### Execution Dashboard

Robot Manager provides real-time dashboards showing:

```
Fleet Status:
├── Connected: 45/50 agents
├── Executing: 12 robots
├── Idle: 30 robots
├── Disconnected: 5 robots (investigate!)
└── Disabled: 3 robots (maintenance)

Today's Execution Summary:
├── Total executions: 1,247
├── Successful: 1,189 (95.3%)
├── Failed: 42 (3.4%)
├── In Progress: 16 (1.3%)
└── Average duration: 3m 22s

Queue Health:
├── InvoiceProcessing: 142 pending, 4h avg wait
├── CustomerOnboarding: 0 pending, current
├── AccountReconciliation: 23 pending, 1h avg wait
└── ReportGeneration: 567 pending, SLA breach risk ⚠
```

### Key Metrics

| Metric | Description | Alert Threshold (example) |
|---|---|---|
| **Success rate** | % of executions completing without error | Below 90% |
| **Average duration** | Mean execution time per automation | Above 2x baseline |
| **Queue backlog** | Items waiting in queues | Above SLA-breach horizon |
| **Robot utilization** | % of time robots are actively executing | Below 40% (over-provisioned) or above 95% (under-provisioned) |
| **Failure clusters** | Multiple failures on same robot/automation | 3+ consecutive failures |
| **SLA compliance** | % of work items completed within SLA window | Below 95% |

### Audit Trail

Robot Manager logs all administrative and execution events:

- Deployment actions (upload, activate, rollback) — who, when, what version.
- Schedule changes — who modified, old vs new configuration.
- Robot status changes — connected, disconnected, disabled.
- Work item state transitions — with timestamp and robot identity.
- Credential access — which robot accessed which credential, when.

### Alerting

Configure alerts for:

- Robot disconnection (agent offline for > N minutes).
- Automation failure (single failure or consecutive failure threshold).
- Queue SLA breach risk (backlog * avg processing time > remaining SLA window).
- License utilization (approaching maximum concurrent licenses).
- Schedule missed execution (automation did not start at scheduled time).

---

## 13. Credential Management

### Credential Vault

Robot Manager provides a centralized credential vault — the only sanctioned location for storing automation credentials.

```
Credential Store:
├── SAP-Production
│   ├── Username: svc_rpa_sap_prd
│   ├── Password: ********** (encrypted)
│   ├── Environment: Production
│   ├── Robot override: None (all robots in group use this)
│   └── Rotation: 90 days
│
├── SAP-Test
│   ├── Username: svc_rpa_sap_tst
│   ├── Password: **********
│   ├── Environment: Test
│   └── Rotation: 90 days
│
├── WebApp-Production
│   ├── Username: rpa_service@company.com
│   ├── Password: **********
│   ├── Environment: Production
│   ├── Robot override:
│   │   ├── Robot-VM-01: rpa_service_01@company.com
│   │   └── Robot-VM-02: rpa_service_02@company.com
│   └── Rotation: 60 days
```

### Credential Access from Automations

```
' Retrieve credential at runtime — never store in variables longer than needed
Dim cred As Credential = CredentialVault.Get("SAP-Production")

' Use immediately
SAPLogin.EnterUsername(cred.Username)
SAPLogin.EnterPassword(cred.SecurePassword)

' Do NOT log credentials
Log.Info("Logging in to SAP as " + cred.Username)    — OK (username only)
Log.Info("Password is " + cred.Password)              — NEVER DO THIS
```

### Per-Robot Overrides

Some applications require unique credentials per robot session (to avoid concurrent login conflicts). Configure per-robot credential overrides in Robot Manager:

- Same credential name used in the automation code.
- Robot Manager resolves the correct username/password based on which robot is executing.
- Automations are credential-agnostic — they request by name, Robot Manager supplies the right values.

### Rotation Policies

- Set expiry reminders in Robot Manager (e.g., 14 days before password expiry).
- Coordinate rotation with the target application's password policy.
- Test new credentials in the test environment before rotating production.
- Stagger rotation across robot groups to avoid simultaneous lockouts.

### Windows Credential Manager Integration

For attended robots, Robot Manager can integrate with Windows Credential Manager to store credentials locally (encrypted by Windows DPAPI), with centralized management and push from Robot Manager.

---

## 14. Pega Platform Integration

### Triggering Automations from Pega Cases

Pega Platform cases can invoke RPA automations as part of case processing:

```
Case: InsuranceClaim
├── Stage: Data Collection
│   ├── Step: Receive claim (human)
│   └── Step: Validate documents (human)
├── Stage: Processing
│   ├── Step: Extract claim data from legacy system ← ROBOT AUTOMATION
│   ├── Step: Calculate settlement (decisioning)
│   └── Step: Review settlement (human, if above threshold)
├── Stage: Resolution
│   └── Step: Post payment to ERP ← ROBOT AUTOMATION
```

The case lifecycle can seamlessly hand off work to robots and resume when the robot completes.

### Data Flow Between Cases and Robots

```
Pega Case                          Robot Automation
┌──────────────┐                  ┌──────────────────┐
│ ClaimNumber  │────────────────►│ Input: ClaimNumber│
│ PolicyId     │────────────────►│ Input: PolicyId   │
│ ClaimantName │────────────────►│ Input: ClaimantName│
│              │                  │                    │
│              │                  │ ... processing ... │
│              │                  │                    │
│ LegacyRef   │◄────────────────│ Output: LegacyRef  │
│ ClaimAmount  │◄────────────────│ Output: Amount     │
│ StatusCode   │◄────────────────│ Output: Status     │
└──────────────┘                  └──────────────────┘
```

Data mapping is configured in the Pega case flow — the automation shape maps case properties to robot input parameters and robot output parameters back to case properties.

### Decisioning Integration

Pega Decisioning (AI/ML engine) can determine whether to route work to a robot or a human:

```
Decision Strategy: RouteClaimProcessing
├── IF claim is straightforward (amount < $5,000, standard type, known vendor):
│   └── Route to Robot Queue (fully automated)
├── IF claim is complex but data extraction is robotic:
│   ├── Route data extraction to Robot Queue
│   └── Route review to Human Work Queue
└── IF claim requires judgment:
    └── Route entirely to Human Work Queue
```

This creates a hybrid workforce — robots handle high-volume repetitive work, humans handle exceptions and judgment calls, and decisioning optimally routes between them.

### DX API Integration

For custom integrations, Robot Manager exposes REST APIs:

```
# Queue management
POST   /api/v1/queues/{queueId}/items              — add work item
GET    /api/v1/queues/{queueId}/items/{itemId}      — get work item status
PUT    /api/v1/queues/{queueId}/items/{itemId}      — update work item
DELETE /api/v1/queues/{queueId}/items/{itemId}      — remove work item

# Robot management
GET    /api/v1/robots                                — list all robots
GET    /api/v1/robots/{robotId}/status               — get robot status
POST   /api/v1/robots/{robotId}/execute              — trigger automation on specific robot

# Deployment
POST   /api/v1/deployments                           — upload package
PUT    /api/v1/deployments/{deploymentId}/activate    — activate package
PUT    /api/v1/deployments/{deploymentId}/deactivate  — deactivate package

# Schedules
GET    /api/v1/schedules                             — list schedules
POST   /api/v1/schedules                             — create schedule
PUT    /api/v1/schedules/{scheduleId}                — update schedule

# Authentication: OAuth 2.0 bearer token or Pega operator credentials
# Content-Type: application/json
```

---

## Related Skills

| Domain | Skill |
|---|---|
| Pega Platform (case management, decisioning) | no dedicated skill yet — general knowledge / `web-research` |
| Windows automation scripting | `windows-powershell` |
| Windows CMD batch scripts | `windows-cmd` |
| Windows SSO and authentication | `windows-sso` |
| Docker containers for Pega services | `docker-admin` |
