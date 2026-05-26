# Yearly Performance Goal

## Objective

Add a yearly performance goal system for team members where:

- each employee has a yearly goal plan
- a yearly plan contains multiple goals
- each goal contains one or more KPIs
- each KPI contains a checklist of tasks/items
- completing KPI items increases KPI achievement %
- KPI achievement contributes to the yearly result based on weightage

This should support review planning after annual or periodic team reviews.


## Core Idea

The current `Lists` feature already supports checklist-style work:

- a list
- multiple items
- completion state
- progress %

That makes it a useful UI reference, but not a complete data model for performance goals.

Reason:

- `WorkList` is personal and generic
- it has no yearly cycle
- it has no goal hierarchy
- it has no KPI weightage
- it has no annual roll-up logic

So the right approach is:

- reuse the interaction style of Lists
- create a dedicated performance-goal data model


## Proposed Business Structure

Recommended hierarchy:

1. `PerformancePlan`
2. `PerformanceGoal`
3. `PerformanceKPI`
4. `PerformanceKPIItem`

Meaning:

- one employee has one `PerformancePlan` for a given year
- one `PerformancePlan` contains multiple `PerformanceGoal` rows
- one `PerformanceGoal` contains multiple `PerformanceKPI` rows
- one `PerformanceKPI` contains multiple checklist items


## Example Structure

Employee: Rahul  
Year: 2026

### Goal 1

Title: Improve delivery ownership  
Weight within annual plan: 40%

KPIs:

- Release predictability
- Sprint commitment discipline

### Goal 2

Title: Strengthen team capability  
Weight within annual plan: 35%

KPIs:

- Mentoring
- Documentation

### Goal 3

Title: Improve stakeholder communication  
Weight within annual plan: 25%

KPIs:

- Weekly updates
- Escalation quality

Total annual plan weight = 100%


## Calculation Logic

### KPI achievement

Each KPI has checklist items.

If a KPI has 10 items:

- each completed item contributes `10%`
- 4 completed items means KPI achievement is `40%`

Formula:

`kpi_achievement_percent = (completed_items / total_items) * 100`


### Goal achievement

A goal can contain multiple KPIs.

Two implementation options exist:

1. KPI weightage inside a goal
2. equal KPI contribution inside a goal

Recommended:

- support KPI weightage explicitly

Formula:

`goal_achievement_percent = sum(kpi_weightage * kpi_achievement_percent)`

Where KPI weights inside a goal sum to `100`.


### Annual plan achievement

Each goal also has weightage in the yearly plan.

Formula:

`annual_achievement_percent = sum(goal_weightage * goal_achievement_percent)`

Where goal weights inside a yearly plan sum to `100`.


## Finalized Product Decisions

- one yearly plan per employee per year
- goal weights inside the yearly plan must total `100`
- KPI weights inside each goal must total `100`
- KPI items inside a KPI are always equal-weight
- KPI items do not need custom per-item weights
- admin creates plans
- admin edits goals, KPIs, plan structure, and completion state
- employees can view their own plans
- employees can add KPI items to their own plans
- admin remains the only role that marks KPI items complete or incomplete
- plans can be finalized and locked
- finalized plans are read-only until reopened by admin
- admin can manage plans for everyone


## Weight Model

Use weightage at two levels:

1. Goal weightage inside yearly plan
2. KPI weightage inside goal

This is better than only weighting KPIs directly because:

- managers usually think in goals first
- yearly review summaries are easier to read
- goals create a cleaner structure for discussion and reporting

This is part of the agreed MVP and should be implemented from the start.


## Recommended Database Model

### 1. `performance_plans`

Purpose:

- one row per employee per year

Suggested columns:

- `id`
- `org_id`
- `user_id`
- `year`
- `title`
- `description`
- `status`
- `created_by`
- `created_at`
- `updated_at`

Constraints:

- unique on `(org_id, user_id, year)`


### 2. `performance_goals`

Purpose:

- major goal areas inside a yearly plan

Suggested columns:

- `id`
- `performance_plan_id`
- `title`
- `description`
- `weightage`
- `sort_order`
- `created_at`
- `updated_at`

Constraints:

- goal weightage across one plan should total `100`


### 3. `performance_kpis`

Purpose:

- measurable KPI groups under a goal

Suggested columns:

- `id`
- `performance_goal_id`
- `title`
- `description`
- `weightage`
- `sort_order`
- `created_at`
- `updated_at`

Constraints:

- KPI weightage across one goal should total `100`


### 4. `performance_kpi_items`

Purpose:

- checklist items that drive KPI completion

Suggested columns:

- `id`
- `performance_kpi_id`
- `title`
- `notes`
- `is_completed`
- `completed_at`
- `sort_order`
- `created_at`
- `updated_at`


## Recommended MVP Scope

### Phase 1

Build the minimum useful system:

- create yearly performance plan for an employee
- add multiple goals
- assign goal weightage
- add multiple KPIs inside each goal
- assign KPI weightage
- add checklist items under KPI
- toggle KPI items complete/incomplete
- show KPI progress %
- show goal weighted achievement %
- show annual weighted achievement %


### Phase 2

Manager and review enhancements:

- manager can create/edit plans for team members
- employee can update progress
- reviewer comments
- due dates / review checkpoints
- plan lock after review closure
- archived past-year plans


### Phase 3

Reporting:

- team-wide goal dashboard
- department-wise progress
- yearly comparison
- export summary for appraisal


## UI Recommendation

Do not overload the current generic `Lists` page.

Instead add a new section:

- `Performance Goals`

Suggested screens:

1. `/{org_slug}/performance-goals`
   - list of employee-year plans
   - quick status
   - overall completion %

2. `/{org_slug}/performance-goals/{plan_id}`
   - yearly plan summary
   - goal cards
   - weighted overall progress

3. inside plan detail:
   - each goal expands into KPIs
   - each KPI expands into checklist items similar to current task lists

UI pattern can reuse:

- cards
- progress bars
- inline edit patterns
- checklist completion interactions

These already exist in `lists.html`.


## Can Existing Lists Be Reused?

### Reuse directly as `KPI type list`

Possible, but not recommended for final implementation.

Why not:

- no yearly grouping
- no employee review structure
- no goal parent
- no weightage logic
- no reporting model
- generic lists and performance lists would start colliding conceptually


### Reuse as design/reference

Recommended.

Reuse:

- list item completion interaction
- progress bar rendering
- add/edit item patterns
- compact checklist layout

Do not reuse:

- `work_lists` table as the main KPI storage


## Validation Rules

Recommended validations:

- one employee can have only one plan per year
- goal weights inside a plan must total `100`
- KPI weights inside a goal should total `100`
- a KPI with zero items shows `0%`
- unchecking a completed item recalculates KPI, goal, and annual achievement immediately


## Access Model

Initial recommendation:

- admin/manager creates and edits plans
- employee can view own plan
- optional employee self-update for KPI items

Later we can refine with role-based control:

- admin full access
- manager access to assigned team
- employee access to own plan


## Suggested Implementation Path In This Codebase

1. add new SQLAlchemy models
2. add startup schema ensure functions like the current pattern in `app/main.py`
3. add helper functions for achievement calculations
4. add pages and forms
5. add sidebar navigation entry
6. reuse current list/checklist UI patterns where practical


## Current MVP Rules

1. Exactly one yearly plan per employee per year.
2. Goal weights must total `100` inside the yearly plan.
3. KPI weights must total `100` inside each goal.
4. KPI items are equal-weight within a KPI.
5. Employees can add KPI items but cannot mark them complete.
6. Admin controls finalization and reopening.


## Recommendation

Recommended final direction:

- create a new `Performance Goals` module
- keep `Lists` unchanged for generic personal checklists
- reuse checklist UX from Lists
- implement a proper performance hierarchy with weighted roll-ups

This gives:

- clean reporting
- clean future extensibility
- less data-model debt
- better review workflows


## Immediate Next Step

After this document is approved:

1. finalize the hierarchy and weight rules
2. design SQLAlchemy models
3. build the MVP schema and page flow
