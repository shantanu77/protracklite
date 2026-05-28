# Manager Role Proposal

## Objective

Introduce a `Manager` role between `Employee` and `Admin`.

The manager role should not be a reduced version of admin. It should be a team-scoped operational role focused on planning, execution visibility, workload management, and team-level reporting.


## Role Philosophy

Recommended role split:

- `Employee`
  - works on own tasks
  - logs own time
  - views own goals
  - can suggest KPI items where allowed

- `Manager`
  - manages direct reports or assigned team members
  - owns team planning and team-level tracking
  - sees team reports and manager-level summaries
  - does not get full organizational control

- `Admin`
  - full organization-wide access
  - settings, users, master data, and all team access


## Manager Scope

Managers should be scoped to their reporting line or explicitly assigned team.

Recommended access boundary:

- can manage only direct reports
- can view only team-level data for those reports
- cannot access unrelated users or other teams unless given broader scope later


## What Manager Should Be Able To Do

### 1. Team Planning

Managers should be able to:

- create yearly performance plans for direct reports
- create and edit goals for direct reports
- create and edit KPIs under those goals
- add KPI items for direct reports
- review employee-added KPI items
- mark KPI item completion for direct reports
- finalize plans for their team, within team scope

Reason:

- managers are the first real owners of team execution and appraisal readiness
- this prevents admin from becoming the bottleneck for all people-management workflows


### 2. Task And Workload Oversight

Managers should be able to:

- view all tasks for direct reports
- create tasks for direct reports
- edit tasks for direct reports
- reprioritize team tasks
- mark tasks stalled or completed for team members
- reassign tasks within their team if that workflow is allowed
- identify overloaded and underutilized team members
- spot tasks with weak progress signals

Useful manager views:

- all team tasks
- tasks due this week
- overdue tasks
- stalled tasks
- tasks without recent time logs


### 3. Leave And Availability Control

Managers should be able to:

- view leave calendar for direct reports
- see future availability gaps
- compare team capacity against active work
- identify delivery risk from overlapping leaves

Future enhancement:

- leave approval workflow can be added later if required


### 4. Team Reporting

Managers should be able to see:

- team booking rate
- task completion trends
- overdue and stalled trends
- KPI and goal achievement by employee
- manager summary for weekly or monthly review
- exception reports such as:
  - no logs submitted
  - growing overdue tasks
  - low KPI movement
  - below-threshold effort patterns

This should be stronger than employee reporting, but narrower than admin organization-wide reporting.


## Move To Phase 2

The following capabilities should not be part of the first manager release.

### 5. Review Workflow

Move to Phase 2:

- manager comments on goals or KPIs
- manager notes per employee
- periodic check-in records
- review status flow like draft / under review / finalized / closed
- self-review vs manager-review comparison

Reason:

- useful, but not required for the first operational manager layer
- this introduces additional workflow states and more UI complexity


### 6. Team Hygiene Controls

Move to Phase 2:

- enforce logging discipline for the team
- enforce note quality rules beyond system defaults
- visibility audits for private/public tasks
- stale plan cleanup and archival controls
- compliance or discipline-oriented reminder workflows

Reason:

- valuable later, but not the first thing a manager role needs
- better added after core planning and reporting are stable


## Recommended Phase 1 Manager Permissions

Manager should be able to:

- access a manager dashboard
- view direct-report tasks
- manage direct-report tasks
- view direct-report yearly plans
- create and manage goals/KPIs for direct reports
- add and complete KPI items for direct reports
- view team leave and capacity
- view team-level reports

Manager should not be able to:

- edit organization settings
- manage all users across the company
- edit global holidays
- control master projects or activity types unless explicitly allowed
- access unrelated teams


## Suggested Role Matrix

### Employee

- own task access: yes
- own time logs: yes
- own goal visibility: yes
- add KPI items: yes, if enabled
- mark KPI items complete: no
- team reports: no


### Manager

- direct-report task access: yes
- direct-report goal/KPI management: yes
- direct-report KPI completion: yes
- team reports: yes
- organization reports: limited manager-level scope only
- admin settings: no


### Admin

- all employee and manager powers: yes
- org setup and settings: yes
- full organization reporting: yes


## Recommended Data/Model Changes Later

To support manager role cleanly, the system will likely need:

- `manager_id` or reporting structure on users
- helper query methods for direct reports
- manager-scoped dashboards and reports
- permission checks that distinguish:
  - self
  - direct report
  - org-wide admin


## Implementation Recommendation

Phase 1:

1. add `MANAGER` role
2. define direct-report mapping
3. add manager-scoped task visibility
4. add manager-scoped goals visibility and editing
5. add manager dashboards and reports

Phase 2:

1. review workflow
2. team hygiene controls
3. approval-style flows
4. richer audit and coaching features


## Recommendation

Manager role should be introduced as a team execution and planning role, not as a read-only reporting role and not as a weak admin clone.

The most important first-release manager capabilities are:

- team planning
- task oversight
- leave/capacity visibility
- team reporting

Review workflow and team hygiene controls should be intentionally delayed to Phase 2.
