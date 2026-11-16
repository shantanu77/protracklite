# ProTrack Win — Business Requirements, UI and API Specification

**Document status:** Expanded draft for product and engineering review  
**Product:** ProTrack Win  
**Audience:** Product, design, Windows engineering and ProTrack API engineering  
**Scope:** A small personal Windows task app. The app operates only on the signed-in user's own work and reports.

## 1. Product summary

ProTrack Win is a lightweight Windows companion for capturing tasks, grouping them into personal lists, completing work with one click, and seeing a small personal progress report. It stays available in the Windows notification area (system tray), uses Windows notifications for reminders, and syncs through ProTrack APIs.

The experience should be familiar to Microsoft To Do users: clear lists, a quick add box, completion circles, and a compact Today/Upcoming view. Natural-language or dictated task narration is the primary task-entry method. The app should not grow into a project-management client.

## 2. Product goals and boundaries

### Goals

- Capture a task quickly from a short written or dictated description.
- Add tasks to user-managed lists and manage those lists.
- Complete a task with one click and automatically book the configured default effort (4 hours initially) to ProTrack.
- Remind the user through native Windows notifications.
- Show a few useful reports about the signed-in user only.
- Remain available in the system tray while running, without opening multiple app instances.

### Not in the first release

- Assigning or reviewing another person's tasks.
- Shared/team list administration, comments, mentions, or team reports.
- Projects, sprint boards, subtasks, attachments, approval flows, or complex task dependencies.
- Replacing the ProTrack web app for organization-wide administration.

## 3. Users and main scenarios

**Primary user:** A ProTrack employee who wants a small personal task organizer connected to their ProTrack account.

1. The user opens the tray menu and selects **Add task**, or opens the main window and enters a task narration.
2. ProTrack Win extracts a title, due date, reminder time, destination list, and optional effort estimate. The user can review the fields before saving.
3. The user manages personal lists and moves between Today, Upcoming, My Tasks, Completed, and named lists.
4. The user single-clicks a task's completion control. The task is marked complete and the current default completion effort (4.0 hours initially) is booked to its linked ProTrack task. A brief Undo action is offered.
5. A Windows notification appears when a reminder is due. Selecting it opens the task in ProTrack Win.
6. The user opens **My report** to see their task and effort totals for a chosen period.

## 4. Functional requirements

### 4.1 Task capture and task fields

- The app must provide a natural-language text field and Windows dictation-compatible text input. Dictation itself may use Windows voice typing; a custom speech-recognition service is not required in v1.
- AI-assisted parsing must identify, when present: task title, due date, reminder date/time, destination list, ProTrack project/activity type, and estimated effort.
- The app must present interpreted values for review before saving. No task is created from narration without the user's explicit Add action.
- If a field is unclear, leave it unset and retain the relevant words in the narration/description for the user to edit.
- Title is required. Description, due date, reminder, estimate and list are optional. A new task without a selected list goes into **My Tasks**.
- Task effort estimate defaults from the signed-in user's ProTrack defaults when available; otherwise the app preference is used. The estimate is editable and is distinct from booked actual effort.
- A task created in ProTrack Win must be a personal ProTrack task assigned to and created by the signed-in user, and may be placed in one personal list.

### 4.2 Lists

- Provide a default **My Tasks** destination and allow the user to create, rename, reorder and archive personal lists.
- A list displays open and completed tasks, with completion count and optional target date.
- Users can add a task to a list, move a task between their lists, and filter a list to Open, Completed or All.
- Archiving a list preserves its tasks and history. The archive action requires a short confirmation and is reversible if the API supports restore.
- V1 list management is personal. The app must not expose sharing, participants or another user's list content.

### 4.3 One-click completion and effort booking

- One click on the completion circle marks the task complete and submits the configured completion effort to ProTrack. The initial default is **4.0 hours**; users can change the value in Settings.
- Do not show a required confirmation dialog on every completion. Show a short-lived Undo action after successful completion.
- A completion action must atomically record the task's closed status and the associated effort entry, or return a clear failure without leaving only one of those records saved.
- If the task cannot be completed (for example, there is no valid ProTrack project/activity target), the UI must retain the task as open and explain what setting must be fixed.
- Each completion effort entry uses today's local date and a generated, honest note such as “Completed in ProTrack Win: <task title>.” If the ProTrack time-log API's minimum-note rule applies, the server must generate a compliant note rather than fabricate work details.
- Reopening a completed task must not silently erase or reverse booked effort. V1 may support reopening task status while retaining the historical time log; any correction to effort must use an explicit edit/correction flow.
- The server must prevent duplicate effort logs if the app retries a request after a timeout.

### 4.4 Notifications

- A task may have one reminder date/time. The user can enable or disable reminders globally and per task.
- Show a Windows toast at the scheduled local time with task title and **Open** action. A **Snooze 10 minutes** action is recommended.
- Notifications are local to this Windows installation in v1. They are scheduled only while the app is installed and the user is signed into Windows; missed reminders after shutdown are not replayed by default.
- A task completion, deletion or reminder edit must update/cancel its scheduled notification.
- Notification actions must open the relevant task, restoring the window from the tray if needed.

### 4.5 Personal report

- Provide a basic **My report** screen with a period selector (week, month, custom range) and only the signed-in user's information.
- Show: tasks completed in the period, tasks still open/overdue, estimated hours on open work, effort hours booked in the period, and a simple daily effort trend.
- Report figures must be sourced from ProTrack; the app must not compare the user with coworkers or expose team data.
- Include a link/action to refresh and a visible “as of” sync timestamp.

### 4.6 Sync and offline handling

- ProTrack is the source of truth. The app keeps an encrypted local cache for fast startup, tray reminders and offline viewing.
- If offline, allow viewing cached tasks and lists. Queue user edits/completions locally and sync them when connected.
- Queue entries must carry an idempotency key. On reconnection, reconcile with server state and show conflicts instead of silently overwriting newer server data.
- A queued completion must not display as successfully booked until the server confirms both completion and effort booking. It may be shown as **Waiting to sync**.
- Provide a visible last-sync time and a retry action.

## 5. Non-functional requirements

### Single instance and tray behavior

- ProTrack Win is single-instance per Windows user session. Use a named OS mutex; a second launch brings the existing window to the foreground rather than starting another process/window.
- The app provides a tray icon and remains running when the main window is closed/minimized. **Exit** is available from the tray menu and fully stops background reminders.
- Tray icon states: current/synced, syncing, offline/error, and pending actions. Provide accessible tooltips.
- Startup with Windows is an opt-in Settings choice. Do not silently add a startup entry.

### Usability and accessibility

- Keep the interface intuitive, compact, keyboard-accessible, DPI-aware, and usable at common Windows scaling settings.
- The main task actions should be reachable without navigating a settings hierarchy.
- Support screen readers, visible focus, meaningful accessible labels, and high-contrast Windows themes.
- Keyboard shortcuts: `Ctrl+N` add task, `Ctrl+F` search, `Enter` save in the add form, `Esc` close a panel, and `Space` complete a focused task.

### Security and privacy

- Use HTTPS only. Never embed ProTrack service secrets, AI provider keys or database credentials in the Windows client.
- Never store the user's plaintext password. Store authentication material only in the WebView2 protected cookie store or Windows Credential Manager as appropriate.
- The server derives the user identity from the authenticated session; clients must not choose arbitrary user IDs for task or report requests.
- Store offline cache data per Windows user, encrypt it at rest, and clear it on sign-out.
- Logs must not contain passwords, cookies, access tokens or full private narration unless the user explicitly opts into diagnostics.

### Suggested implementation platform

- Windows 10/11, .NET 8 (or current supported .NET LTS at implementation time), WPF for a small native desktop UI, WebView2 only for ProTrack sign-in, and Windows App SDK notifications or supported Windows toast APIs.
- Keep API and sync logic in a separate .NET service layer so the view can be changed without altering contracts.
- Use SQLite with OS-protected encryption for the local cache/outbox; verify licensing and encryption library support before selecting the exact package.

## 6. UI specification

### 6.1 Tray icon and right-click menu

Right-click opens a short menu:

```text
┌─────────────────────────────┐
│ Open ProTrack Win            │
│ Add task…                    │
│ My Tasks                 ›   │
│ Today                        │
│ Upcoming                     │
│ My report                    │
│ Sync now                     │
├─────────────────────────────┤
│ Open ProTrack in browser     │
│ Settings                     │
│ Exit                         │
└─────────────────────────────┘
```

The **My Tasks** submenu lists recent personal lists and offers **New list…**. Menus should remain short; lists are managed in the main window. Left-click opens the compact window. Double-click behavior should match left-click.

### 6.2 Main window

```text
┌──────────────────────────────────────────────────────────────────────┐
│ ProTrack Win     [ Search tasks…                         ]  ⚙   —  × │
├──────────────────┬───────────────────────────────────────────────────┤
│ My Tasks         │ Today                              + Add task     │
│ Today            │                                                   │
│ Upcoming         │  ○  Prepare monthly utilization summary  10:00   │
│ Completed        │     My Tasks · due today                          │
│                  │                                                   │
│ MY LISTS         │  ○  Review design notes                Tomorrow   │
│ + New list       │     Product work · reminder 9:00 AM               │
│ Product work     │                                                   │
│ Home             │                                                   │
│                  │                                                   │
│ My report        │                                                   │
├──────────────────┴───────────────────────────────────────────────────┤
│ ● Synced 2 min ago                                      2 open tasks │
└──────────────────────────────────────────────────────────────────────┘
```

- Left navigation: My Tasks, Today, Upcoming, Completed, a **My Lists** section, and My report.
- Main pane: quick add, search/filter, task rows and useful empty states.
- Task row: one-click completion control, title, list, due/reminder labels, and optional priority indicator. Avoid extra controls on the row; click the title to open details.
- Footer/status bar: sync state, last-sync time and pending-action count.
- Closing the window hides it to the tray; Exit is explicit in the tray menu.

### 6.3 Natural-language add panel

```text
┌─────────────────────────────────────────────────────────┐
│ Add task                                           [×]  │
│                                                         │
│ What do you need to do?                                 │
│ [ Prepare the monthly report tomorrow at 10…        ]   │
│                                                         │
│ Review before adding                                    │
│ Title       Prepare the monthly report                  │
│ Due         Tomorrow                                    │
│ Reminder    Tomorrow, 10:00 AM                          │
│ List        My Tasks                             [Edit] │
│ Project     [Default project                     ▾]     │
│ Activity    [Default activity                    ▾]     │
│ Estimate    [ 4.0 ] hours                               │
│                                                         │
│                                    [Cancel] [Add task]  │
└─────────────────────────────────────────────────────────┘
```

AI extraction is presented as a draft. Project and activity selection use ProTrack's available defaults/options; if these are required and no valid default exists, the user must select them before adding. The task's estimated effort is not automatically booked.

### 6.4 Task details

A side panel shows editable title, description, list, due date, reminder, project/activity, estimated effort, status and effort history. Save applies edits. Delete/archive is secondary and requires confirmation. Do not expose team-assignment controls.

### 6.5 Completion feedback

A click immediately completes and books the configured value. Show a toast such as **Completed · 4.0h booked** with **Undo** available briefly. On failure, revert the visible completion state and show a useful retry message. If offline, show **Completion queued · effort not booked yet** and retain Undo while the action is still pending.

### 6.6 List management

A list view includes the list title, optional target date/description, Open/Completed/All filters, progress count, and **Add task**. A compact list menu provides Rename, Reorder, Archive. New list asks only for a title; description and target date are optional.

### 6.7 My report

Keep the report to four summary cards and one small chart:

- Completed tasks.
- Open and overdue tasks.
- Estimated hours remaining.
- Actual ProTrack effort booked.
- Daily effort trend for the selected date range.

Below, provide a compact completed-task list with completion date and booked hours. Every result is scoped to the current user.

### 6.8 Settings

- ProTrack organization and signed-in user; Sign out.
- Default effort to book on completion: **4.0 hours** initially, editable in 0.25-hour increments.
- Default estimated task hours.
- Default ProTrack project and activity type.
- Notifications on/off; default reminder time; sound/snooze behavior.
- Start ProTrack Win with Windows (off by default).
- Cache/sync status and clear local cached data.

## 7. Data contract and concepts

### Task model

A visible task is a ProTrack `Task` assigned to the signed-in user. Minimum client fields:

```json
{
  "task_id": "PT-1234",
  "name": "Prepare the monthly report",
  "description": "Source narration or user-edited detail",
  "status": "not_started",
  "project_id": 12,
  "activity_type_id": 4,
  "estimated_hours": 4.0,
  "start_date": "2026-11-09",
  "end_date": "2026-11-10",
  "list_id": 31,
  "reminder_at": "2026-11-10T10:00:00+05:30"
}
```

`list_id` and `reminder_at` are app-facing fields requiring the API extensions below; current `Task` storage does not have either field. Due date maps to the existing task `end_date`. List association must be stored in a server-side relation, not only in the Windows cache.

### List model

A personal ProTrack `WorkList` holds references to ProTrack tasks for grouping. Current `WorkListItem` is a separate checklist record, not a ProTrack `Task`; the API extension must either associate it to a `Task` via `task_id` or introduce a desktop-specific list-task relation. Do not treat a plain checklist toggle as a ProTrack effort booking.

### Completion effort

A completed task uses a `TimeLog` against the linked ProTrack `Task`, with `log_date`, `hours` and server-generated `notes`. Completion and log creation are one logical idempotent operation. The current client-visible time-log route alone does not atomically complete a task.

## 8. Authentication and API conventions

### Authentication model

Current ProTrack authentication uses signed `access_token` and `refresh_token` HttpOnly cookies; `/api/v1/auth/login` accepts credentials and sets both cookies, `/api/v1/auth/refresh` renews the access cookie, and `/api/v1/auth/logout` clears cookies. Protected routes use `get_org_user`, which resolves the authenticated user and organization from the cookie subject.

**Desktop sign-in recommendation:** Use WebView2 to display the organization's ProTrack login page, letting the user complete the normal login/MFA/password-change experience. Reuse WebView2's protected cookie store for API calls, call `/api/v1/users/me` after login, and renew through `/api/v1/auth/refresh` when a protected API returns 401. Never ask the desktop client to persist a password or parse tokens from page HTML. If WebView2 cookie sharing is not viable in the selected .NET HTTP stack, add a server-issued, one-time desktop authorization-code flow; do not ship a long-lived bearer token or embed client secrets.

### Request conventions

- Base URL: `https://tasks.omnihire.in` (organization is selected during sign-in and bound to the cookie session).
- JSON requests: `Content-Type: application/json`, `Accept: application/json`; send auth cookies over HTTPS.
- Date-only values use ISO `YYYY-MM-DD`; timestamps include an explicit timezone offset.
- Decimal effort values use hours with a maximum of two decimal places; UI step is 0.25 hours.
- Respect HTTP status and JSON `detail` error responses. `401` refreshes/re-authenticates; `403` ends the operation and informs the user; `409` means conflict/duplicate; `5xx` is retryable with idempotency protection.
- Never send `user_id` to choose the acting user. The server must derive ownership from the session.
- All new mutating desktop endpoints accept an `Idempotency-Key` UUID header and return the prior result if that key was already processed.

## 9. API inventory

### 9.1 Existing ProTrack endpoints reusable by the app

| Method and path | Purpose | Contract notes |
|---|---|---|
| `POST /api/v1/auth/login` | Sign in | JSON body: `{"org_slug":"solulever","email":"person@example.com","password":"…"}`. Returns `{ok,user_id,org_slug}` and sets HttpOnly cookies. Prefer WebView2 login page rather than collecting credentials in the native UI. |
| `POST /api/v1/auth/refresh` | Renew access cookie | Cookie-authenticated; returns `{ok:true}` and sets a renewed access cookie. |
| `POST /api/v1/auth/logout` | Sign out | Clears auth cookies. |
| `GET /api/v1/users/me` | Load current identity | Returns `id`, `full_name`, `email`, `role`, `department`. |
| `GET /api/v1/tasks/quick-create/options` | Load valid task defaults | Returns `projects`, `activity_types`, `project_activity_map`, `statuses`, and `defaults` with `project_id`, `activity_type_id`, `status`, `start_date`. Use this to populate project/activity selections. |
| `GET /api/v1/tasks/?status=&project_id=&q=` | List tasks | Returns tasks visible to the user as creator/assignee, including `task_id`, `name`, `status`, `estimated_hours`, `logged_hours`, project/activity labels, dates and private/shared flags. Client must still display only personal tasks assigned to the user unless explicitly included as created-by-me. |
| `POST /api/v1/tasks/` | Create ProTrack task | Required current fields include `project_id`, `activity_type_id`, `name`; optional fields include `description`, `status`, `tags`, `is_private`, `is_backlog`, `start_date`, `end_date`, `estimated_hours`, `complexity_weight`, `is_high_priority`. Returns `{task_id}`. Server assigns task to current user. |
| `GET /api/v1/tasks/{task_code}` | Load task details | Returns task identity, status, description, estimated/logged hours and related properties. |
| `PUT /api/v1/tasks/{task_code}` | Edit/close task | JSON may include fields accepted by current update handler, including `name`, `description`, `project_id`, `activity_type_id`, dates, estimates and `status`. Returns `{ok:true}`. Current route does not create a time log atomically. |
| `POST /api/v1/tasks/{task_code}/time-log` | Book effort | Current JSON body requires `log_date`, `hours`, `notes`. Returns `{ok:true,logged_hours}`. Current note normalization enforces a minimum detail length. Use the combined endpoint below for one-click close plus effort; do not separately call this then update status. |
| `GET /api/v1/tasks/{task_code}/time-logs` | Read task effort history | Returns entries with `id`, `date`, `hours`, `notes`. |
| `GET /api/v1/lists` | List summaries | Returns current visible WorkList summaries: id, title, description, target date, order, progress, sharing/owner fields. Filter to owned lists for this personal app. |
| `GET /api/v1/reports/work-rate?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD` | Personal work-rate summary | Server scopes calculation to authenticated user. Use as an optional report card only after confirming definitions match the UI. |
| `GET /api/v1/reports/closures?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD` | Personal task closures | Returns closed task IDs, names, close timestamps, estimates and logged hours for the signed-in user. |

### 9.2 Existing routes not suitable as the desktop API

The web app has useful HTML/form routes such as `POST /{org_slug}/lists`, `POST /{org_slug}/lists/{list_id}/items`, item toggle/update, list update/archive, and AI list creation. Some return redirects and several APIs are only GET summaries. The Windows app should not depend on HTML redirects, parse rendered pages, or reuse routes whose semantics mutate shared lists. Add versioned JSON endpoints below for a stable desktop contract.

### 9.3 Required new JSON endpoints

These contracts are proposed for ProTrack API engineering. Paths are versioned under `/api/v1/desktop` to keep the Win client independent from HTML route details.

#### AI narration parse

`POST /api/v1/desktop/task-drafts/parse`

Request:

```json
{
  "text": "Prepare the monthly summary tomorrow at 10 and book 4 hours",
  "locale": "en-IN",
  "timezone": "Asia/Kolkata",
  "default_list_id": 31
}
```

Response is a draft only; it must not persist a task:

```json
{
  "draft": {
    "name": "Prepare the monthly summary",
    "description": "Prepare the monthly summary tomorrow at 10 and book 4 hours",
    "due_date": "2026-11-10",
    "reminder_at": "2026-11-10T10:00:00+05:30",
    "list_id": 31,
    "project_id": 12,
    "activity_type_id": 4,
    "estimated_hours": 4.0,
    "confidence": {
      "name": 0.96,
      "due_date": 0.90,
      "reminder_at": 0.84
    },
    "needs_review": ["reminder_at"]
  }
}
```

The server uses its configured AI provider/key. It must return extracted fields, not book time. On provider failure, return a useful `503` or a local-parser draft and let the user edit manually.

#### Personal list CRUD and detail

- `GET /api/v1/desktop/lists?include_archived=false` — list only the current user's lists and include list IDs/task IDs needed for the UI.
- `POST /api/v1/desktop/lists` — create a personal list. Body: `{"title":"Product work","description":"","target_date":"2026-11-30"}`. Return the full list object.
- `GET /api/v1/desktop/lists/{list_id}` — list detail and tasks; enforce owner access.
- `PATCH /api/v1/desktop/lists/{list_id}` — rename/edit description/target date/order. Body is a partial update.
- `POST /api/v1/desktop/lists/{list_id}/archive` — archive owned list; return `{ok:true,is_archived:true}`. Optional restore endpoint if reversible archive ships.
- `POST /api/v1/desktop/lists/reorder` — body `{"list_ids":[31,34,35]}`; only current user's active lists are accepted.

#### Create a task and put it in a personal list

`POST /api/v1/desktop/tasks`

Request:

```json
{
  "name": "Prepare the monthly summary",
  "description": "Source narration or edited detail",
  "project_id": 12,
  "activity_type_id": 4,
  "list_id": 31,
  "due_date": "2026-11-10",
  "reminder_at": "2026-11-10T10:00:00+05:30",
  "estimated_hours": 4.0,
  "is_private": true
}
```

The API creates the ProTrack `Task` assigned to the authenticated user and associates it to a personal list in one transaction. It returns task and list identifiers plus normalized values. List association and reminder fields require new persistent columns/relations. If `list_id` is absent, associate with the user's default **My Tasks** list (created on first use) or return the configured default ID.

#### List tasks and move a task

- `GET /api/v1/desktop/tasks?view=today|upcoming|open|completed&list_id=&q=&from_date=&to_date=` — return paginated personal tasks with list, due/reminder state and booked effort summary. `today` and dates must use the user's/org timezone.
- `PATCH /api/v1/desktop/tasks/{task_code}` — edit name, description, list, due date, reminder, project/activity and estimated effort. Validate target list belongs to current user and project/activity pair is permitted.
- `DELETE /api/v1/desktop/tasks/{task_code}` — soft archive/delete only the authenticated user's own task. Preserve time logs and completion history.

#### Complete and book effort atomically

`POST /api/v1/desktop/tasks/{task_code}/complete`

Headers: `Idempotency-Key: <uuid>`

Request:

```json
{
  "effort_hours": 4.0,
  "log_date": "2026-11-09",
  "timezone": "Asia/Kolkata"
}
```

Response:

```json
{
  "ok": true,
  "task": {"task_id":"PT-1234","status":"closed","closed_at":"2026-11-09T14:25:00+05:30"},
  "time_log": {"id": 9021,"log_date":"2026-11-09","hours":4.0,"logged_hours":8.0},
  "idempotency_key":"<uuid>"
}
```

The API verifies ownership and a valid task/project/activity, validates effort limits, creates a compliant time-log note, updates task status/closed timestamp, and commits both atomically. Repeated requests with the same idempotency key return the same result and never add a second log. If a task is already complete, return its existing completion record or `409` with current state; do not book another 4 hours. Support a separate explicit reopen endpoint only if product approves reopening semantics; reopening never deletes effort logs.

#### Reminder scheduling data

The server persists `reminder_at` as an ISO timestamp with timezone and returns it in task payloads. Windows notifications are scheduled locally; no push-notification backend is needed in v1. API edits/deletes must return normalized reminder values so the local scheduler can replace/cancel notifications.

#### Personal report aggregate

`GET /api/v1/desktop/reports/me?from_date=YYYY-MM-DD&to_date=YYYY-MM-DD`

Response:

```json
{
  "from_date": "2026-11-02",
  "to_date": "2026-11-09",
  "completed_count": 8,
  "open_count": 12,
  "overdue_count": 2,
  "estimated_open_hours": 22.5,
  "booked_effort_hours": 31.0,
  "daily_effort": [
    {"date":"2026-11-02","hours":5.0},
    {"date":"2026-11-03","hours":4.0}
  ],
  "completed_tasks": [
    {"task_id":"PT-1234","name":"Prepare the monthly summary","closed_at":"2026-11-09T14:25:00+05:30","booked_hours":4.0}
  ],
  "generated_at":"2026-11-09T14:30:00+05:30"
}
```

This endpoint must scope every query to the current user and organization. It must not accept a `user_id` query parameter.

### 9.4 Required server data changes

Current `WorkList`/`WorkListItem` tables support personal/shared lists and simple checklist items; current `Task` supports ProTrack assignment, project/activity, estimate, status and effort. To meet this specification:

- Add a server-side relation from a personal list to ProTrack tasks (for example `work_list_items.task_id` with a unique nullable FK) or a dedicated desktop task/list association table. Define cascade behavior so archiving a list never deletes tasks/time logs.
- Persist task due date using `Task.end_date`; add `reminder_at` and timezone normalization for desktop notifications.
- Create a default **My Tasks** list on first desktop use or return a stable default virtual-list ID.
- Add a durable idempotency record for completion requests keyed by user and idempotency UUID.
- Add/confirm user-level default completion-effort preference (initial 4.0h), default estimate, and optional default list. Defaults should be editable in Settings and stored server-side or consistently synchronized; never let client defaults silently drift between devices.
- Ensure the completion operation generates a valid time-log note under current ProTrack validation rules and is atomic with task closure.

## 10. Error and retry behavior

| Situation | App behavior |
|---|---|
| Invalid/expired session | Attempt `/api/v1/auth/refresh` once; if it fails, open sign-in and keep unsent drafts locally. |
| AI parsing unavailable | Keep narration text, allow manual fields, and offer retry. Do not block task entry. |
| No default project/activity | Explain that a ProTrack work target is needed; open a project/activity selector before task save. |
| Network failure on create/edit | Keep the draft in encrypted outbox and show **Waiting to sync**. Avoid duplicate task creation using idempotency key. |
| Network failure on completion | Keep a pending completion intent and do not report effort as booked. Retry with same key. |
| Server validation failure | Do not retry automatically; show field-specific message and preserve entered values. |
| Conflict with another device | Refresh the server copy and offer user choice for editable fields; never overwrite a newly completed task silently. |
| List archived/deleted elsewhere | Move orphaned tasks to **My Tasks** only after showing a sync notice; preserve task and effort history. |

## 11. Acceptance criteria

1. A second launch activates the existing app instance; it does not create a second window or process.
2. Closing the window leaves the tray icon active; tray **Exit** stops the process and notification scheduler.
3. The tray right-click menu can open the app, add a task, reach personal lists, open Today/Upcoming/My report, sync, open Settings and exit.
4. The user can create, rename, reorder and archive personal lists and add/move tasks between them.
5. AI narration generates an editable draft; adding is explicit and creates one ProTrack task in the selected list.
6. A single click completes a task and books the configured effort once; default is 4.0 hours. Undo/failed sync behavior is clear and no duplicate time log is created on retry.
7. A reminder produces a Windows notification at the selected local time and opens the correct task when clicked.
8. The report shows task and effort totals for the signed-in user only.
9. The app handles expired login, offline viewing, retry and server conflicts without losing the user's draft.
10. Keyboard and screen-reader users can navigate and operate the primary flows.

## 12. Build sequence

1. **API foundation:** Add desktop JSON list/task/parse/complete/report endpoints, persistent list-task relation, reminder field, user preferences, idempotency and migration.
2. **Authentication spike:** Prove WebView2 sign-in cookie reuse and refresh/logout behavior; implement one-time desktop authorization code instead if cookie reuse is not secure/reliable.
3. **Windows shell:** Create .NET desktop app, single-instance mutex, tray icon/menu, compact main window and settings.
4. **Personal task flows:** Add list navigation, AI draft review, create/edit/move/archive and local cache/outbox.
5. **Completion and report:** Implement atomic one-click completion/effort, Undo semantics and self-only report.
6. **Notifications and release:** Add Windows notification scheduling, accessibility/DPI checks, installer, startup opt-in and update strategy.

## 13. Open product decisions

The following are intentionally left for review before implementation:

- Confirm whether desktop tasks should always require a ProTrack project/activity target (recommended, since completion books effort to a ProTrack task).
- Confirm whether default 4.0 hours should be booked automatically on every one-click completion (specified above) or only after a per-completion effort prompt.
- Confirm whether **Undo** reopens only task status while preserving booked effort (recommended) or requires an explicit compensating effort edit.
- Confirm local reminder behavior while Windows is asleep/off or when the app is not running. V1 recommendation is local reminders while the app is installed and user session is active.
