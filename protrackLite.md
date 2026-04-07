# Protrack*Lite* — Product Specification

> *Lite* is italicized in all UI usage. Theme: blue-centric (#1565C0 primary, #E3F2FD background accents). Fully mobile-first, responsive design.

---

## 1. Overview

**Protrack*Lite*** is a lightweight, organization-scoped personal task tracker designed for software product organizations. Every employee logs their daily work as tasks. Tasks are public within the organization by default, fostering transparency and accountability. The application enables individuals to track their own progress while giving teams and managers visibility into workload, effort, and output.

### Core Philosophy
- An employee owns their task list, but the organization can see it.
- Tasks are how effort gets documented — bugs, features, research, demos, all go in as tasks.
- Weekly planning (Monday Demo Day) and month-to-date reporting (My Standing) drive a culture of intentional work.

---

## 2. Technology Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11+ with **FastAPI** |
| Database | MySQL 8.0+ |
| ORM | SQLAlchemy 2.x with Alembic migrations |
| Authentication | JWT (access + refresh tokens), bcrypt password hashing |
| Frontend | **Vue 3** + Vite, **Tailwind CSS**, **Ionic components** for mobile-feel |
| API Style | RESTful JSON API |
| Email | SMTP via Python `smtplib` / SendGrid for password delivery |
| Captcha | hCaptcha (server-side verify) |
| Hosting | Any Linux VPS; Nginx as reverse proxy |
| Caching | Redis (session, rate limiting) |

**Why Vue 3 + Tailwind + Ionic:** Ionic components (IonCard, IonList, IonFab, IonTabBar etc.) provide native-feeling mobile UI out of the box. Tailwind handles all custom styling with the blue theme. Vue 3 Composition API keeps frontend logic clean.

---

## 3. URL & Tenant Structure

The organization context is derived from the URL path segment:

```
https://task.omnihire.in/{org-slug}/
```

Examples:
- `task.omnihire.in/solulever/` → Solulever organization
- `task.omnihire.in/acmecorp/` → Acme Corp organization

**Rules:**
- If `{org-slug}` is not found in the database, show a "Organization not found" error page.
- All routes under an org slug are scoped to that organization.
- A user account belongs to exactly one organization; logging in under a wrong slug is rejected.
- The slug is stored in the `organizations` table and is URL-safe lowercase (a-z, 0-9, hyphens).

---

## 4. Authentication

### 4.1 Login Flow
- No self-registration. Accounts are created by the **Admin** only.
- User visits `/{org-slug}/login`
- Enters **email address**
- Enters **password**
- On success → JWT issued, redirect to dashboard

### 4.2 Forgot Password
- User clicks "Forgot Password" on login page
- Prompted to solve an **hCaptcha** challenge
- On captcha success, the system emails the user their **temporary password** (randomly generated, 10 chars, mixed case + digits)
- User logs in with temporary password; system forces a **password change** on first login with temp password
- Temporary password expires in **24 hours**

### 4.3 JWT Tokens
- Access token TTL: 60 minutes
- Refresh token TTL: 7 days, stored in HttpOnly cookie
- Refresh endpoint auto-renews access token silently

### 4.4 Roles
| Role | Description |
|---|---|
| `employee` | Default role. Can manage own tasks, view others' public tasks, view own reports |
| `admin` | All employee permissions + project management, user management, holiday management, org-wide reports |

---

## 5. Data Model

### 5.1 Organizations
```
organizations
  id            INT PK AUTO_INCREMENT
  name          VARCHAR(150)         -- "Solulever Technologies"
  slug          VARCHAR(60) UNIQUE   -- "solulever"
  created_at    DATETIME
  is_active     BOOLEAN DEFAULT TRUE
```

### 5.2 Users
```
users
  id                    INT PK AUTO_INCREMENT
  org_id                INT FK organizations.id
  email                 VARCHAR(255) UNIQUE
  full_name             VARCHAR(150)
  password_hash         VARCHAR(255)
  role                  ENUM('employee','admin') DEFAULT 'employee'
  is_active             BOOLEAN DEFAULT TRUE
  force_password_change BOOLEAN DEFAULT FALSE
  temp_password_expires DATETIME NULL
  created_at            DATETIME
  updated_at            DATETIME
```

### 5.3 Projects
```
projects
  id            INT PK AUTO_INCREMENT
  org_id        INT FK organizations.id
  name          VARCHAR(200)
  code          VARCHAR(10)   -- e.g. "MYP", "CRM" — used in task IDs
  description   TEXT
  is_active     BOOLEAN DEFAULT TRUE
  created_by    INT FK users.id
  created_at    DATETIME
```

**On project creation:** The default set of activity types is automatically linked to the project (see §5.5).

### 5.4 Task ID Generation
Task IDs are auto-generated per project:
- Format: `{PROJECT_CODE}{SEQUENCE_NUMBER_ZERO_PADDED_4}`
- Examples: `MYP0001`, `MYP0042`, `CRM0007`
- Sequence is per-project, incrementing, stored in a `project_task_sequence` column on `projects`.

### 5.5 Activity Types (Task Types)
Activity types describe the nature of work. They have a `is_chargeable` flag used in work-rate calculations.

**Default activity types (seeded globally, linked per project):**

| Code | Name | Chargeable |
|---|---|---|
| SPEC | Specification Writing | Yes |
| RES | Research | Yes |
| DES | Design (UI/UX, Architecture) | Yes |
| DEV | Development / Coding | Yes |
| TEST | Testing & QA | Yes |
| REV | Code Review | Yes |
| BUG | Bug Fix | Yes |
| DOC | Documentation | Yes |
| DEP | Deployment / DevOps | Yes |
| MTG | Meeting / Discussion | Yes |
| DEMO | Demo Preparation & Delivery | Yes |
| PLAN | Planning | Yes |
| STUDY | Self Study / Learning | No |
| TRAIN | Training / Seminar / Workshop | No |
| ADMIN | Administrative Work | No |
| SUPPORT | Support / Helpdesk | Yes |
| REVIEW | Performance / Process Review | No |
| OTHER | Other | No |

Admins can add custom activity types or toggle chargeability per organization.

### 5.6 Tasks
```
tasks
  id                INT PK AUTO_INCREMENT
  task_id           VARCHAR(20) UNIQUE    -- e.g. MYP0001
  org_id            INT FK organizations.id
  project_id        INT FK projects.id
  assigned_to       INT FK users.id
  created_by        INT FK users.id
  name              VARCHAR(300)
  description       LONGTEXT              -- HTML supported (sanitized on render)
  activity_type_id  INT FK activity_types.id
  status            ENUM('not_started','started','stalled','closed') DEFAULT 'not_started'
  is_private        BOOLEAN DEFAULT FALSE -- private = only owner can see
  start_date        DATE                  -- defaults to today
  end_date          DATE NULL
  estimated_hours   DECIMAL(5,2) NULL
  logged_hours      DECIMAL(6,2) DEFAULT 0.00  -- sum of time_logs
  created_at        DATETIME
  updated_at        DATETIME
  closed_at         DATETIME NULL
```

### 5.7 Time Logs (Effort Tracking)
```
time_logs
  id          INT PK AUTO_INCREMENT
  task_id     INT FK tasks.id
  user_id     INT FK users.id
  log_date    DATE
  hours       DECIMAL(4,2)
  notes       TEXT NULL
  created_at  DATETIME
```

Time logs allow partial effort tracking across multiple days for a single task. `tasks.logged_hours` is a denormalized sum kept in sync.

### 5.8 Leaves
```
leaves
  id          INT PK AUTO_INCREMENT
  user_id     INT FK users.id
  leave_date  DATE
  leave_type  ENUM('full','half_am','half_pm') DEFAULT 'full'
  reason      VARCHAR(255) NULL
  created_at  DATETIME
  UNIQUE KEY  (user_id, leave_date)
```

### 5.9 Holidays
```
holidays
  id          INT PK AUTO_INCREMENT
  org_id      INT FK organizations.id
  holiday_date DATE
  name        VARCHAR(150)
  created_at  DATETIME
  UNIQUE KEY  (org_id, holiday_date)
```

### 5.10 Weekends Configuration
```
org_settings
  id          INT PK AUTO_INCREMENT
  org_id      INT FK organizations.id UNIQUE
  weekend_days JSON    -- e.g. [5, 6] for Saturday=5, Sunday=6 (0=Monday)
  work_hours_per_day DECIMAL(4,2) DEFAULT 8.00
```

---

## 6. Task Management

### 6.1 Creating a Task
- User selects a **Project** from dropdown (only active projects in their org)
- Enters **Name** (required)
- Selects **Activity Type** (required)
- Enters **Description** (rich HTML editor — Quill.js or TipTap)
- **Start Date** defaults to today (editable)
- **End Date** optional
- **Estimated Hours** optional
- **Status** defaults to `not_started`
- **Private** toggle (defaults OFF — task is public)

### 6.2 Editing a Task
All fields editable. Status transitions are free-form (no enforced state machine for now). When status is changed to `closed`, `closed_at` timestamp is recorded automatically.

### 6.3 Logging Time on a Task
From a task detail view, user can add a time log entry:
- Date (defaults to today)
- Hours (decimal, e.g. 2.5)
- Notes (optional)

Multiple entries per task per day are allowed. Running total shown on task card.

### 6.4 Task List / My Tasks View
Default view: **This Week + All Pending (non-closed) tasks**

Filters available:
- Status (multi-select)
- Activity Type
- Project
- Date Range
- Search by name / task ID

Sort options: Due Date, Created Date, Status, Project

### 6.5 Viewing Others' Tasks
Any employee can browse another employee's public tasks:
- Navigate via `/{org-slug}/team/{user-id}/tasks`
- Private tasks are hidden
- Read-only view (cannot edit others' tasks)

---

## 7. Reports

### 7.1 My Tasks — Default View
Shown on dashboard after login:
- **This week's tasks** (start_date or end_date falls within current Mon–Fri)
- **All pending tasks** (status ≠ `closed`, regardless of date)
- Grouped by: Today's Focus / This Week / Overdue / Pending (no date)
- Each task card shows: Task ID, Name, Project, Status badge, Activity type, Estimated vs Logged hours, Days pending

### 7.2 Work Rate Report
Available under "My Reports" → "Work Rate"

**Inputs:** Date range (default: current month)

**Calculations:**

```
Available Working Days = Calendar days in range
                        - Weekend days
                        - Public holidays in org
                        - Approved leaves (full = 1 day, half = 0.5 day)

Available Hours = Available Working Days × work_hours_per_day (default 8)

Total Hours Placed = SUM(time_logs.hours) for user in range

Total Work Rate (%) = (Total Hours Placed / Available Hours) × 100

Chargeable Hours = SUM(time_logs.hours) WHERE activity_type.is_chargeable = TRUE

Effective Work Rate (%) = (Chargeable Hours / Available Hours) × 100
```

Display:
- Summary cards: Available Hours | Total Logged | Total Rate % | Chargeable Logged | Effective Rate %
- Visual gauge/progress bars in the blue theme
- Breakdown table by activity type showing hours and % of total
- Breakdown table by project

### 7.3 Task Closure Report
Available under "My Reports" → "Closed Tasks"

**Filters:** This Week / This Month / Last Month / Custom Range

Shows:
- Table of all tasks with `status = 'closed'` in the period
- Columns: Task ID, Name, Project, Activity Type, Start Date, Closed Date, Days Taken, Estimated Hours, Logged Hours, Variance (Est - Logged)
- Summary: Count closed, Avg days to close, Total hours logged

### 7.4 Monday Demo Day Report
Available as a prominent shortcut: "Monday Report" (accessible any day, not just Monday)

**Sections:**

#### Section A — Pending Tasks (Carry-forwards)
All tasks with `status ≠ 'closed'` created before the **start of the current week** (Monday 00:00).

| Column | Description |
|---|---|
| Task ID | Clickable link |
| Task Name | |
| Project | |
| Activity Type | |
| Status | |
| Created / Start Date | |
| Pending Since | Human-readable: "12 days", "3 weeks" |
| Pending Days (count) | Integer |
| Estimated Hours | |
| Logged Hours so far | |

Sorted by: Pending days descending (oldest first).

#### Section B — Tasks Completed Last Week
All tasks with `status = 'closed'` AND `closed_at` within the previous Monday–Friday window.

| Column | Description |
|---|---|
| Task ID | |
| Task Name | |
| Project | |
| Activity Type | |
| Closed On | |
| Est. Hours | |
| Logged Hours | |

#### Section C — This Week's Plan
Tasks with `start_date` within the current Mon–Fri window (tasks the user has planned for this week).

Note: It is expected practice that every Monday, an employee creates tasks representing what they plan to accomplish that week. This section shows those planned tasks.

**Export:** The Monday Report can be exported as a clean PDF or copied as formatted text for sharing in standups/meetings.

### 7.5 My Standing Report
Available under "My Reports" → "My Standing"

**Purpose:** Show the current user's effort for the current month and allow comparison with any peer.

**Layout:**

Left panel — **My Effort (current month):**
- Work Rate summary (same as §7.2 but locked to current month)
- Task list with hours logged per task (sorted by logged hours desc)
- Activity type breakdown (pie chart)

Right panel / Compare mode:
- Dropdown: "Compare with…" — lists all active employees in the org
- On selection, the right panel mirrors the left panel format but for the selected employee
- Only public tasks are shown for the comparison employee
- Private tasks of the other person are excluded from count too (hours not shown to maintain privacy — show "Some hours from private tasks are excluded")

**Visibility rules:**
- Task names and details: visible for public tasks only
- Hours: visible for public tasks; private task hours are excluded from the displayed total for the other person
- Own private tasks: visible to self only

---

## 8. Leave Management

### 8.1 Marking Leave
- User navigates to "My Leaves" or accesses it from the Work Rate report
- Selects date(s) from a calendar
- Selects leave type: Full Day / Half Day AM / Half Day PM
- Optionally adds a reason
- Leave is saved and immediately reflected in Available Hours calculation

### 8.2 Leave Calendar
- Monthly calendar view showing:
  - Green: Working day
  - Blue: Holiday (org holiday)
  - Grey: Weekend
  - Yellow: Half-day leave
  - Orange: Full-day leave

---

## 9. Admin Panel

### 9.1 User Management
- List all users with status (active/inactive), role, last login
- Add new user: Full name, email, role — system generates and emails a temporary password
- Edit user: name, role, active status
- Deactivate user (soft delete — tasks remain)
- Reset password for a user (generates new temp password, emails it)

### 9.2 Project Management
- List all projects with task count, active members
- Add project: Name, Code (2–6 chars, validated unique), Description
- On project creation → default activity types are auto-linked
- Edit project: name, description, active status
- Archive project (tasks remain visible, no new tasks can be added)

### 9.3 Holiday Management
- Annual holiday calendar per organization
- Add holiday: date + name
- Delete holiday
- Bulk import: paste CSV of date, name
- Holidays affect Available Hours for ALL employees in the org

### 9.4 Weekend Configuration
- Set which days are weekends (default: Saturday, Sunday)
- Set standard work hours per day (default: 8)
- These settings apply org-wide

### 9.5 Activity Type Management
- View all default activity types (seeded)
- Toggle `is_chargeable` flag per activity type
- Add org-specific custom activity types
- Deactivate unused activity types (hidden from task forms)

### 9.6 Admin Dashboard
Accessible at `/{org-slug}/admin/dashboard`

**Summary Cards:**
- Total active employees
- Tasks created this month (org-wide)
- Tasks closed this month (org-wide)
- Org-wide Total Work Rate % (current month)
- Org-wide Effective Work Rate % (current month)

**Team Performance Table (current month):**

| Employee | Available Hrs | Logged Hrs | Total Rate % | Chargeable Hrs | Effective Rate % | Open Tasks | Closed Tasks |
|---|---|---|---|---|---|---|---|

Sortable by any column. Click employee → drill-down to their task list and work rate detail.

**Charts:**
- Stacked bar: daily hours logged across the team (last 30 days)
- Pie: org-wide activity type distribution
- Line: weekly task closure rate trend

---

## 10. Notifications & UX Details

### 10.1 In-App Alerts
- Reminder on Monday morning (on login): "Time to plan your week! You have X pending tasks."
- If a task has been in `started` or `stalled` status for > 7 days: a small warning badge on the task card.

### 10.2 Mobile UX
- Bottom tab bar: Home | My Tasks | Reports | Admin (if admin)
- FAB (Floating Action Button) on task list for quick task creation
- Task cards swipeable: swipe left for "Log Time", swipe right for "Change Status"
- Full-page task detail with HTML description rendered safely
- All tables scroll horizontally on small screens with frozen first column

### 10.3 Theme
- Primary: `#1565C0` (Blue 800)
- Primary light: `#1E88E5` (Blue 600)
- Accent: `#29B6F6` (Light Blue 400)
- Background: `#F0F7FF`
- Card background: `#FFFFFF`
- Text primary: `#0D1B2A`
- Success: `#2E7D32`
- Warning: `#F57F17`
- Danger: `#C62828`
- Status badges: color-coded (not started: grey, started: blue, stalled: orange, closed: green)

---

## 11. API Structure (FastAPI)

```
/api/v1/
  auth/
    POST   login
    POST   refresh
    POST   logout
    POST   forgot-password

  tasks/
    GET    /                  -- list tasks (filters via query params)
    POST   /                  -- create task
    GET    /{task_id}         -- task detail
    PUT    /{task_id}         -- update task
    DELETE /{task_id}         -- soft delete
    POST   /{task_id}/time-log   -- add time log
    GET    /{task_id}/time-logs  -- list time logs

  projects/
    GET    /                  -- list projects
    POST   /                  -- create (admin)
    GET    /{id}
    PUT    /{id}              -- update (admin)

  users/
    GET    /                  -- list users (admin or for compare)
    GET    /me                -- current user profile
    PUT    /me                -- update own profile / password
    GET    /{id}/tasks        -- another user's public tasks

  reports/
    GET    /work-rate          -- query: user_id, from, to
    GET    /closures           -- query: user_id, from, to
    GET    /monday-demo        -- query: user_id
    GET    /my-standing        -- query: compare_user_id

  leaves/
    GET    /                   -- list own leaves
    POST   /                   -- add leave
    DELETE /{id}               -- remove leave

  admin/
    GET    /dashboard
    users/ ...
    projects/ ...
    holidays/ ...
    settings/ ...
    activity-types/ ...
```

---

## 12. Security Considerations

- All HTML descriptions sanitized server-side (bleach / html-sanitizer) before storage and on render
- JWT tokens signed with RS256 (asymmetric keys)
- Rate limiting on login endpoint (5 attempts per 15 minutes per IP)
- hCaptcha verified server-side on forgot-password; never trust client-side result
- Org isolation enforced at the database query level — every query includes `org_id` filter
- Private tasks filtered out in all endpoints that return data belonging to other users
- Passwords hashed with bcrypt (cost factor 12)
- CSRF protection on all state-changing endpoints
- SQL injection prevention via SQLAlchemy parameterized queries only (no raw string interpolation)

---

## 13. Deployment Architecture

```
Internet
    |
 Nginx (SSL termination, static files, reverse proxy)
    |
FastAPI (uvicorn / gunicorn workers)
    |          |
  MySQL      Redis
```

- Vue 3 frontend built as static files, served by Nginx from `/dist`
- FastAPI mounted at `/api/v1/`
- Org slug routing handled in Vue Router (frontend) and validated on every API call (backend middleware)
- Alembic migrations run on deploy
- Environment variables via `.env` file (never committed)

---

## 14. Future Enhancements (Out of Scope for Lite)

- Slack / Teams integration for Monday Report push notifications
- Task dependencies (blocked by / blocks)
- Approval workflow for task closure
- File attachments on tasks
- Git commit linking to tasks
- Mobile native app (wrap with Capacitor)
- SSO / LDAP authentication
- Multi-org admin (super-admin role)

---

*Document version: 1.0 — 2026-04-07*
