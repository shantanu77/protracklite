# Goal Update V2 Review

## Review Objective

Review the existing KRA, yearly performance goal, activity-list, management,
reporting, review, and communication features against the intended workflow:

1. goals are assigned to managers
2. managers work on those goals throughout the financial year
3. progress and supporting activity are recorded
4. management periodically reviews progress
5. the goals are submitted, reviewed, and concluded at financial-year end


## Current Assessment

The application already has a useful foundation:

- yearly performance plans
- weighted goals within a plan
- weighted KPIs within a goal
- checklist-style KPI items
- calculated KPI, goal, and plan achievement percentages
- admin and manager plan-management permissions
- employee plan visibility
- manager dashboard goal-progress visibility
- monthly work reports and manager comments
- separate activity types, tasks, and collaborative work lists

However, the current implementation is best considered a weighted-goal
prototype. It does not yet provide the complete lifecycle needed to assign a
manager's KRAs, track their work through a financial year, conduct periodic
reviews, and formally close the plan.


## Critical Findings

### 1. Manager Goals Page Is Likely Broken

`managed_user_ids()` is defined twice in `app/main.py`.

The first definition accepts an `include_self` keyword argument. The later
definition overwrites it but does not accept that argument. The Goals module
calls the function with `include_self=True`, which will produce a `TypeError`
when a manager opens the Goals page.

Relevant locations:

- `app/main.py:1558`
- `app/main.py:2946`
- `app/main.py:3662`
- `app/main.py:3683`

Required correction:

- keep one canonical manager-scope helper
- make the distinction between direct reports and self explicit
- update all task, report, and goal permissions to use the canonical helper
- add tests for employee, manager, and admin access


### 2. A Manager Cannot Progress Their Own Assigned Plan

An admin can create a performance plan for a manager, but the manager's update
permissions are based on whether the plan owner is a direct report. A manager
is not their own direct report.

As a result, a manager assigned their own plan cannot reliably:

- add KPI items
- edit KPI items
- mark KPI items complete
- conclude their own assigned work

The UI displays manager controls based only on role, but the backend can reject
the action with HTTP 403.

Relevant locations:

- `app/main.py:418`
- `app/main.py:4732`
- `app/main.py:4846`
- `app/templates/goals.html:214`

Required correction:

- distinguish `can_view_plan`, `can_manage_plan_structure`,
  `can_update_plan_progress`, and `can_review_plan`
- permit a manager to update progress and evidence on a plan assigned to them
- retain appropriate separation between self-assessment and reviewer approval
- derive UI controls from the same permissions used by the backend


### 3. Finalization Prevents Financial-Year Execution

The plan currently has only two states:

- `draft`
- `finalized`

Finalizing a plan locks everything, including KPI-item creation, editing, and
completion. This makes `finalized` suitable only for year-end archival. It
cannot also represent an agreed and assigned plan that should remain active
during the year.

Relevant locations:

- `app/main.py:143`
- `app/main.py:414`
- `app/main.py:4474`
- `app/main.py:4823`
- `app/templates/goals.html:79`

Recommended lifecycle:

1. `draft` - goals and weights are being prepared
2. `assigned` or `active` - structure is approved and work is in progress
3. `submitted_for_review` - owner has submitted the year-end result
4. `under_review` - reviewer is evaluating the result and evidence
5. `reviewed` - review decision and rating have been recorded
6. `closed` - plan is fully locked and retained as a historical record

Structure locking and progress locking should be separate concepts:

- after assignment, structural changes to goals and weights may require a
  controlled amendment
- while active, the owner must still be able to add progress, actual values,
  comments, and evidence
- only closure should make the full plan read-only


## Functional Gaps

### 4. Calendar Year Is Used Instead of Financial Year

`PerformancePlan` stores a single integer `year`. The manager dashboard selects
plans using `date.today().year`.

This does not correctly represent a financial year that crosses calendar-year
boundaries, such as April 2026 to March 2027.

Relevant locations:

- `app/models.py:287`
- `app/models.py:294`
- `app/main.py:3776`
- `app/templates/goals.html:28`

Recommended model:

- add a reusable performance or review cycle
- store `cycle_start`
- store `cycle_end`
- store a display label such as `FY 2026-27`
- allow the organization to configure its financial-year start month
- associate every plan, report, checkpoint, and reminder with that cycle


### 5. KRA Types Are Not Modelled

Goals and KPIs currently contain free-text titles and descriptions. There is no
KRA type or classification.

Useful configurable KRA types may include:

- financial
- customer or stakeholder
- delivery and execution
- operational excellence
- people management
- capability development
- compliance and governance
- innovation and improvement
- organization-specific categories

The types should be organization-configurable rather than permanently
hard-coded. Reporting should support grouping progress and achievement by KRA
type.


### 6. KPI Measurement Is Limited to Checklist Completion

KPI achievement is calculated only as:

`completed checklist items / total checklist items * 100`

This is useful for milestone KPIs but cannot accurately represent measurable
outcomes such as:

- revenue target
- SLA achievement
- defect reduction
- customer satisfaction
- utilization
- hiring completion
- cost savings
- delivery predictability
- employee-retention targets

Relevant locations:

- `app/models.py:321`
- `app/models.py:337`
- `app/main.py:378`

Recommended KPI measurement modes:

1. checklist or milestone completion
2. numeric target where higher is better
3. numeric target where lower is better
4. percentage target
5. binary achieved/not achieved
6. manually rated KPI with reviewer justification

Recommended KPI fields:

- measurement type
- unit
- baseline value
- target value
- current or actual value
- target date
- measurement frequency
- owner update or self-assessment
- reviewer-approved value


### 7. Goals Are Not Connected to Tasks or Activity Types

Tasks already contain project and activity-type information. Work Lists also
provide checklist items and communication. The performance-goal records are
separate from both systems.

There is currently no way to identify:

- which tasks contributed to a KRA
- which activities consumed effort for a KRA
- which completed work supports a KPI result
- whether a claimed achievement has operational evidence

Recommended evidence model:

- allow a KPI or progress update to link one or more tasks
- allow links to Work Lists or Work List items
- allow links to releases or other internal records where relevant
- support an external URL or document reference
- capture evidence notes and the person who submitted them
- optionally roll up logged hours and activity types from linked tasks

Generic Work Lists should remain separate from performance goals. They can be
linked as evidence without becoming the main performance-goal data model.


### 8. Review and Goal Communication Are Missing

Work Lists have comments, but performance plans, goals, and KPIs do not have a
dedicated discussion or check-in history.

Monthly reports contain one manager-comment field. That field is not tied to a
particular goal and is replaced when changed rather than acting as an ongoing
review record.

Missing capabilities include:

- plan-level discussion
- goal or KPI comments
- periodic check-in records
- employee progress commentary
- manager feedback
- acknowledgement of feedback
- employee self-review
- reviewer assessment
- review decisions and ratings
- amendment requests
- change and status history

The communication record should be chronological and should retain author and
timestamp information.


### 9. Notifications and Reminders Do Not Cover Goals

The application has reminder and digest infrastructure for effort and lists,
but the goal lifecycle does not appear to use it.

Recommended notifications:

- plan assigned
- plan awaiting acceptance
- review checkpoint approaching
- progress update overdue
- KPI has had no movement
- target date approaching or overdue
- plan submitted for review
- reviewer feedback added
- amendment requested
- plan reviewed or reopened
- financial-year closure approaching

Notifications should appear in-app where possible, with email digests used for
important exceptions and deadlines.


## Reporting Gaps

### 10. Manager Dashboard Provides Only Basic Goal Progress

The manager dashboard displays one achievement percentage for the current
calendar year. This is a helpful starting point but not enough for active KRA
management.

Relevant locations:

- `app/main.py:3776`
- `app/templates/manager_dashboard.html:53`

Recommended manager views:

- financial-year cycle selector
- plan status by manager or employee
- KRA progress by type
- on-track, at-risk, overdue, and no-update indicators
- progress change since the previous check-in
- KPIs awaiting manager verification
- plans awaiting submission or review
- plans with missing or weak evidence


### 11. Monthly Reports Do Not Include KRA Progress

Monthly work reports include tasks, time logs, effort, leave, weekly focus, and
weekly summaries. They do not include goal progress, KPI progress, KRA-linked
activity, or review checkpoints.

Relevant location:

- `app/templates/monthly_report.html:73`

Recommended additions:

- active KRAs for the selected financial year
- progress at the beginning and end of the month
- progress updates recorded during the month
- linked task and activity evidence
- manager feedback and unresolved actions
- at-risk or overdue KPIs


### 12. Year-End Review Reporting Is Missing

The system does not yet provide a complete financial-year review output.

Recommended year-end report:

- employee and reviewer details
- financial-year cycle
- plan status and review dates
- KRA and KPI weights
- target, actual, and approved achievement
- employee self-assessment
- manager assessment
- supporting evidence
- weighted final achievement
- final rating and review comments
- acknowledgement and closure history
- export to printable HTML or PDF

Useful management reports should also include:

- department-level progress
- KRA-type distribution
- year-over-year comparison
- completion and closure status
- overdue review actions
- low-movement and missing-evidence exceptions


## Validation, Audit, and Data-Quality Gaps

### 13. Weight Validation Is Incomplete

The browser inputs specify a range of 0 to 100, but the backend accepts decimal
values without independently enforcing that range.

The finalization check verifies only that weights total exactly 100. Invalid
weights such as `-100` and `200` could therefore produce a valid total.

Recommended validation:

- every goal weight must be between 0 and 100
- every KPI weight must be between 0 and 100
- goal weights must total 100 before assignment or activation
- KPI weights must total 100 before assignment or activation
- every required KPI must have a measurement definition
- every checklist KPI must contain at least one item
- use database constraints where practical, in addition to application checks


### 14. Audit History Is Insufficient

KPI items retain completion timestamps and the completing user, but there is no
complete audit history for:

- goal or KPI edits
- weight changes
- target changes
- actual-value updates
- status transitions
- comments and reviews
- reopen decisions
- plan amendments
- deletion of goals, KPIs, or evidence

Performance records should have an immutable event or audit log, particularly
after the plan becomes active.


### 15. Automated Goal Tests Are Missing

The existing test suite does not contain dedicated tests for the performance
goal module. This allowed the duplicated manager-scope function and the
self-owned-manager permission mismatch to remain undetected.

Minimum required test coverage:

- employee can view only their own plan
- manager can view direct-report plans
- manager can view and update progress on their own assigned plan
- manager cannot access unrelated plans
- admin can manage all plans
- financial-year cycle selection
- each lifecycle transition and its permissions
- structure locking versus progress updating
- weight range and total validation
- KPI calculations for every measurement mode
- evidence-link authorization
- review and closure permissions
- reporting roll-ups


## Recommended V2 Workflow

### Plan Setup

1. Admin creates or selects the financial-year cycle.
2. Admin assigns a plan to a manager or employee.
3. Goals are classified by KRA type.
4. Goals and KPIs receive weights.
5. KPIs receive measurement definitions and targets.
6. Owner and reviewer discuss or amend the draft.
7. The plan is activated once weights and measurements are valid.


### Financial-Year Execution

1. Owner records KPI progress or actual values.
2. Owner links tasks, activities, lists, and evidence.
3. The system calculates progress where possible.
4. Monthly or quarterly checkpoints capture a progress snapshot.
5. Reviewer adds feedback and follow-up actions.
6. Notifications identify overdue, at-risk, and inactive KRAs.


### Year-End Review

1. Owner enters a self-assessment and submits the plan.
2. Reviewer evaluates actual results and evidence.
3. Reviewer confirms or adjusts approved achievement with justification.
4. Final weighted achievement and rating are calculated.
5. Owner acknowledges the review.
6. Reviewer or admin closes the plan.
7. The closed plan remains read-only and reportable.


## Recommended Implementation Order

### Priority 0: Correct Existing Breakages

1. Remove the duplicate `managed_user_ids()` implementation.
2. Introduce consistent scope and permission helpers.
3. Allow managers to progress their own assigned plans.
4. Align displayed UI actions with backend permissions.
5. Add goal-module permission and calculation tests.


### Priority 1: Complete the Core Lifecycle

1. Add configurable financial-year cycles.
2. Add active, submitted, review, reviewed, and closed states.
3. Separate structure locking from progress locking.
4. Add target dates and review checkpoints.
5. Add a full status and amendment audit trail.


### Priority 2: Improve KRA and KPI Quality

1. Add configurable KRA types.
2. Add numeric, percentage, binary, checklist, and manual measurement modes.
3. Add baseline, target, actual, unit, and approved-result fields.
4. Add stronger server-side and database validation.


### Priority 3: Connect Execution Evidence

1. Link KPIs and updates to tasks and activity types.
2. Link Work Lists and Work List items where useful.
3. Support URLs, notes, and document references.
4. Display evidence and attributable effort in the goal detail view.


### Priority 4: Add Review and Communication

1. Add goal-specific comment threads.
2. Add periodic check-ins and progress snapshots.
3. Add self-review and manager-review sections.
4. Add feedback acknowledgement and amendment requests.
5. Add goal notifications and exception digests.


### Priority 5: Complete Reporting

1. Include KRA progress in monthly work reports.
2. Expand the manager dashboard with risk and review indicators.
3. Add financial-year and department reporting.
4. Add year-over-year comparison.
5. Add a printable or exportable year-end appraisal summary.


## Conclusion

The existing implementation already provides the essential hierarchy and
weighted progress calculations. Those components should be extended rather
than replaced.

The most important V2 correction is to treat goal definition, financial-year
execution, and year-end closure as separate stages. Once manager self-access,
financial-year cycles, measurable KPIs, evidence links, review communication,
and integrated reporting are added, the module can support the intended KRA
management process from assignment through formal conclusion.
