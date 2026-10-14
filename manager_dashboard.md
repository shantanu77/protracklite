# Manager dashboard

## Purpose and approved design

Replace the manager dashboard's counts and execution table with the reviewed manager workspace concept: a weekly briefing, four actionable summary cards, an attention queue, project pulse, capacity table, goal plans, and upcoming leave. Keep the app's existing navigation and manager permissions. Use the prototype's muted green palette, warm background, white panels, compact typography, and responsive layout.

Reviewed prototype: https://tasks.omnihire.in/static/prototypes/manager-dashboard.html

Application route: `/{org_slug}/manager/dashboard`.

## Research informing the design

- [Asana reporting](https://help.asana.com/s/article/universal-reporting?language=en_US): reporting across tasks, projects, portfolios and goals. Adaptation: delivery health with goal achievement alongside it.
- [monday.com Workload](https://support.monday.com/hc/en-us/articles/360010699760-The-Workload-Widget): effort compared with work schedules and time off. Adaptation: leave-adjusted capacity and individual overload.
- [ClickUp dashboard cards](https://help.clickup.com/hc/en-us/articles/25757497269143-Intro-to-cards): modular overviews and reporting cards. Adaptation: clickable summary cards and focused sections.

Research was reviewed on 13 October 2026. The prototype uses fictional data; the implementation uses application records.

## Implemented experience

1. **Weekly briefing:** rule-based summary of projects needing review, overloaded people, pending requests and missing estimates.
2. **Summary cards:** overdue tasks, remaining estimated work versus remaining capacity, people above capacity, and projects without stalled or overdue work. Cards navigate to the relevant section.
3. **Attention queue:** stalled task reasons, overdue tasks, overload, pending leave and attendance requests, missing estimates, missing capacity snapshots, and effort-record gaps. Delivery items appear before approvals and data checks. Filter buttons show all, delivery, approvals, or data quality.
4. **Project pulse:** task completion and health for projects with open work assigned to the scoped team. The link opens the earliest-due open task for review. Counts deliberately describe team scope rather than whole-project completion.
5. **Team capacity and execution:** remaining estimated hours, available hours, overload indicator, missing estimates, open/overdue counts, elapsed effort and financial-year goal achievement. Search by name or department.
6. **Goals:** current financial-year plans, actual weighted achievement, existing plan status and direct links to plan details.
7. **Leave and coverage:** upcoming approved leave from saved snapshots; links open leave details to review handoff and backup. Coverage is not inferred or invented when absent from the snapshot.
8. **Scope and export:** server-side department filtering within the authorised team. CSV exports only visible table members, with missing data left blank and spreadsheet formula characters neutralised.
9. **Transparency:** leave snapshot timestamps and an accessible metric-definitions dialog. Empty sections and missing source data have explicit states.

## Calculations and data semantics

The application timezone determines today. The planning window is the current Monday–Sunday week; organisation settings determine working days, hours and holidays.

- **Overdue:** non-archived open tasks whose end date is before today. Due-today tasks are not overdue.
- **Commitments:** open tasks due by the current Sunday (including overdue work, provided their start date is not later than Sunday), plus open tasks explicitly selected in this week's weekly plan. Undated backlog and future work outside the weekly plan are excluded.
- **Remaining work:** sum of `max(estimated_hours − logged_hours, 0)` for those commitments. Logged hours here are task lifetime totals. A missing estimate is excluded and flagged separately. This is an estimate-based planning signal; spending the estimate does not prove completion.
- **Remaining available hours:** sum of each working day's scheduled hours from today to Sunday after approved full/half-day absences; subtract effort already logged today, flooring each day's capacity at zero. Future available days are not reduced by past effort. This is daily planning capacity, not an intraday clock countdown.
- **Leave source:** shared saved Zoho capacity snapshots, with valid local approval decisions applied. Only approved absences reduce capacity. Pending/rejected/cancelled leave and remote work do not reduce it. Each working month must contain a saved snapshot mapping that employee; otherwise their available and elapsed capacity are Unknown. No network refresh occurs during page rendering.
- **Load:** remaining work / remaining available hours. Zero capacity with outstanding work produces an overload alert rather than division by zero. Team capacity is Unknown if any member's capacity is unknown. Missing estimates are flagged even when known load is low.
- **Effort check:** recorded task hours from Monday through yesterday divided conceptually by the same elapsed working capacity. Today's unfinished logs are excluded. A gap prompts review of records; it is not a productivity score or an attendance verdict.
- **Project health:** Blocked if any scoped open task is stalled; otherwise At risk if any is overdue; otherwise On track. Progress is closed tasks / all non-archived scoped tasks, across all dates. This does not forecast a deadline or identify a project owner.
- **Goal achievement:** reuse the app's weighted plan achievement and actual workflow status for the current April–March financial year. No invented quarterly goals or health labels.

## Actions and permissions

Managers see active direct reports using the existing `managed_people` rules. Admins see active organisation employees. Department selection only narrows this set. All task, project, effort, approval and goal queries retain organisation and team restrictions. Regularization requests also require the current manager assignment. Existing destination pages continue enforcing their own permissions.

This dashboard is read-only. Task editing, workload changes, leave approval and attendance review use existing authorised workflows. Prototype-only state changes and reminder simulations are not copied into production. The page does not send notifications, mutate tasks, refresh Zoho, or approve leave automatically.

## Files

- `app/manager_dashboard.py`: scoped overview data and calculations.
- `app/main.py`: manager route, department validation and existing goal calculation integration.
- `app/templates/manager_dashboard.html`: server-rendered dashboard extending the current app shell.
- `app/static/manager_dashboard.css`: page-scoped styling, responsive grids and tables.
- `app/static/manager_dashboard.js`: attention filters, member search, metric dialog and CSV export.
- `tests/test_manager_dashboard.py`: calculation, source availability, privacy and rendering tests.

The prototype remains available under `app/static/prototypes/` for comparison. Existing unrelated employee-dashboard edits are preserved.

## Verification and rollout

Run the manager dashboard tests and the relevant capacity, approval, goal and employee-dashboard regression tests against an isolated SQLite database. Check Python compilation and JavaScript syntax. Render a real template in tests to verify escaping and data serialization. Review desktop and mobile layouts in an authenticated browser when available.

Implementation in the workspace does not itself deploy the application. Use the existing release process after review; no schema migration is required.

## Follow-up enhancements

Consider task-level workload reassignment with skills and due-date checks, explicit dependency owners and blocker history, confirmed leave coverage, trend history, saved manager views and an optional weekly digest. Those need additional product rules or stored data; this release focuses on real signals supported by the existing model.

### Completed checks

- 73 tests passed: manager dashboard plus capacity, capacity sync, leave approvals, manager team leaves, manager effort digest, performance goals, employee dashboard and template compilation regressions.
- Python compilation, JavaScript syntax and `git diff --check` passed.
- JavaScript interaction checks passed for attention categories, member search, empty states, visible-row export, formula neutralisation, unknown capacity values and dialog controls.
- The actual manager template was rendered in tests, including escaped employee names and saved snapshot timestamps.
- Authenticated desktop/mobile browser review remains outstanding. Production deployment has not been performed.
