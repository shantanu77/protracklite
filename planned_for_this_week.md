# Planned For This Week

## Objective

Improve the Monday Report so it clearly supports weekly planning, not just weekly review.

Today, the report explains the past well:

- `Worked Last Week` shows actual effort
- `Completed Tasks` shows closures
- `Pending Tasks` shows carry-forward work

But it does not clearly answer:

- what am I committing to this week?
- which tasks am I planning to pick up?
- what should my manager understand as my intended focus for the week?

This document proposes a lightweight `This Week Plan` layer inside Monday Report.


## Problem

The current Monday Report is strong for retrospective visibility and weak for prospective planning.

### What works today

- `Worked Last Week` is reliable because it is backed by actual hour logs
- `Pending Tasks` shows open work inventory
- `This Week Tasks` shows tasks already scheduled into the current week

### What is missing

When a user discusses the coming week, there is no explicit visual signal for:

- the items they intend to focus on
- the tasks they want to carry forward
- the items they want to prioritize in the current week

This means users and managers have to infer the plan by scanning multiple sections, which is noisy and ambiguous.


## Recommendation

Add a dedicated `This Week Plan` section to Monday Report.

This should be:

- explicit
- lightweight
- non-consequential
- easy to edit during Monday planning discussion

Non-consequential means:

- adding a task to the weekly plan does not change task status
- it does not automatically log hours
- it does not automatically mark the task as active
- it does not automatically change task dates or estimates

It is a planning artifact, not an execution artifact.


## Core Idea

Let the user build a temporary weekly plan by selecting tasks from relevant report sections.

### Primary source sections

- `Pending Tasks`
- `Worked Last Week`

### Optional source section

- `Backlog`

This lets the user say:

- I am continuing this item
- I am carrying this over
- I am picking this back up
- I want this included in my focus for this week


## Proposed UX

### 1. Add `This Week Plan` section

Place a new section near the top of Monday Report, after the retrospective summary blocks and before the long task tables.

This section becomes the answer to:

- `What am I going to work on this week?`

Each item in the section should show:

- task ID
- task name
- current status
- due date if present
- optional planned note


### 2. Add task selection actions

In these sections:

- `Pending Tasks`
- `Worked Last Week`
- optionally `Backlog`

add a simple action such as:

- `Plan This Week`

When clicked, the task gets added to the `This Week Plan` list.


### 3. Planned items should be visually distinct

Inside source tables, planned tasks should have a visible planning marker.

Examples:

- badge: `Planned This Week`
- subtle row tint
- small flag icon

Important:

- the marker is a support signal only
- it should not replace the dedicated `This Week Plan` section


### 4. Plan should be editable

Users should be able to:

- add tasks
- remove tasks
- reorder tasks
- optionally add a short note per planned task

Examples of short notes:

- `continue`
- `close this week`
- `need support`
- `waiting for input`


### 5. Add optional weekly focus note

At the top of `This Week Plan`, optionally allow one short planning note for the week.

Example:

- `Main focus this week is closing API audit work and finishing dashboard follow-ups.`

This is useful in review discussions and later reporting.


## What Should Happen To `Completed Tasks`

Recommendation for MVP:

- keep the separate `Completed Tasks` section for now
- add a completed signal in `Worked Last Week`
- later evaluate whether `Completed Tasks` is still needed

Reason:

- removing it immediately changes the report structure too much at once
- keeping it for MVP reduces rollout risk
- once `This Week Plan` is added, we can reassess whether `Completed Tasks` still adds value

Longer term, it may be possible to reduce or de-emphasize `Completed Tasks` if `Worked Last Week` becomes rich enough.


## Data Model Recommendation

Do not store this as pure frontend state.

Store it as a weekly planning artifact so it can survive refresh, manager review, and future comparison.

Recommended new table:

- `weekly_task_plans`

Suggested columns:

- `id`
- `org_id`
- `user_id`
- `week_start`
- `week_end`
- `focus_note`
- `created_at`
- `updated_at`

Recommended child table:

- `weekly_task_plan_items`

Suggested columns:

- `id`
- `weekly_task_plan_id`
- `task_id`
- `planned_note`
- `sort_order`
- `created_at`
- `updated_at`

Constraints:

- unique plan per `(org_id, user_id, week_start)`
- task can appear once per weekly plan


## Why Persistence Is Better Than Temporary Coloring

If the feature is only visual and temporary:

- it disappears on refresh
- it cannot be reviewed later
- managers cannot reliably see what was planned
- it cannot be compared with actual effort

If it is persisted:

- Monday discussion becomes a saved commitment artifact
- users can return and update it during the week
- future reporting becomes possible
- `planned vs worked` can be added later


## Scope For MVP

### MVP should include

- `This Week Plan` section on Monday Report
- add tasks from `Pending Tasks`
- add tasks from `Worked Last Week`
- optional add from `Backlog`
- remove from plan
- reorder planned items
- planned badge in source lists
- one optional weekly focus note
- persisted per user per week

### MVP should not include

- automatic task state changes
- manager approval workflow
- prediction or enforcement
- auto-generated weekly plan
- comparing plan vs actual in the same release


## Behavioral Rules

### Rule 1

Planning a task for the week does not change:

- `status`
- `start_date`
- `end_date`
- `estimated_hours`
- `logged_hours`


### Rule 2

A task may appear in:

- `Worked Last Week`
- `Pending Tasks`
- `This Week Plan`

at the same time, and that is acceptable.

These represent different lenses:

- historical effort
- current open inventory
- intended weekly focus


### Rule 3

The same task should not be added twice to the same weekly plan.


### Rule 4

If a user removes a task from `This Week Plan`, the task itself remains unchanged.


## UI Structure Proposal

Recommended order on Monday Report:

1. Page header
2. Weekly summary / AI summary panels
3. Stats and previous-week summary
4. `This Week Plan`
5. `Worked Last Week`
6. `Pending Tasks`
7. `This Week Tasks`
8. `Completed Tasks`
9. `Stalled Tasks`

This order better matches the Monday conversation:

- what happened
- what is the plan
- what supports that plan


## Action Design Options

### Option A: explicit button

Per task row:

- `Plan This Week`

Pros:

- clear
- fast
- easy to understand

Cons:

- adds one more action button to already busy rows


### Option B: checkbox selection + bulk add

In source sections:

- checkbox per task
- `Add Selected To Week Plan`

Pros:

- efficient for multiple items
- cleaner than many buttons

Cons:

- slightly more interaction complexity


### Option C: drag into plan

Drag tasks into `This Week Plan`

Pros:

- polished interaction

Cons:

- unnecessary complexity for MVP


## Recommended Interaction Choice

Use a hybrid approach:

- checkbox selection in `Pending Tasks` and `Worked Last Week`
- one section-level action: `Add Selected To This Week Plan`

Then inside `This Week Plan`:

- allow remove
- allow reorder
- allow edit note

Why this is best:

- lower row-action clutter
- easier to add multiple tasks at once
- cleaner for planning discussion


## Future Enhancement

Once the weekly plan exists, phase 2 can compare:

- planned this week
- actually worked this week
- completed this week
- planned but untouched

That would make Monday Report much stronger as a review and coaching tool.


## Implementation Intent

If approved, implementation should proceed like this:

1. add `weekly_task_plans` and `weekly_task_plan_items`
2. extend Monday report payload with current-week plan data
3. add `This Week Plan` UI section
4. add source-list selection and add-to-plan action
5. add remove and reorder support
6. add planned-task badges in source lists
7. optionally add weekly focus note field


## Final Position

The right solution is not only color and not only a visual flag.

The right solution is:

- a dedicated `This Week Plan` section
- backed by persisted weekly plan data
- with lightweight selection from `Pending Tasks` and `Worked Last Week`
- supported by planning badges in source lists

That gives the user a real answer to:

- `What am I going to work on this week?`

without pretending that planned work and actual work are the same thing.
