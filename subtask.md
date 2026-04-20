# Subtask Design

## Goal

Add simple subtasks under a main task so a user can break work into smaller checkpoints without turning subtasks into full tasks.

The subtask model should stay lightweight:
- title
- optional short description
- deadline
- completion status
- created/completed timestamps

No time logging is needed for subtasks.


## Core Behavior

A subtask is a child item inside a parent task.

Each subtask should support:
- add subtask under a task
- edit subtask title and deadline
- mark subtask complete
- reopen subtask if needed
- delete subtask if created by mistake

Each subtask should have:
- `id`
- `task_id`
- `title`
- `description` optional
- `deadline` nullable date
- `status` with only `open` and `completed`
- `created_at`
- `updated_at`
- `completed_at` nullable
- `sort_order`


## Why Keep It Simple

Subtasks are only for breaking a task into smaller deliverables or checkpoints.

They should not have:
- separate assignee
- separate project
- separate activity type
- time log
- estimated hours
- archive flow

If a child item needs effort tracking or independent ownership, it should be a full task, not a subtask.


## User Flow

### 1. Add Subtask

From the main task detail page:
- user clicks `Add Subtask`
- a small modal or inline row opens
- user enters:
  - subtask title
  - deadline
- save adds the subtask under that task

Optional:
- description field can be hidden under `More details`


### 2. View Subtasks

On task detail page:
- show a `Subtasks` section
- open subtasks first
- completed subtasks after them
- each row shows:
  - checkbox or status icon
  - title
  - deadline
  - completion state

Suggested indicators:
- green for completed
- amber for due today
- red for overdue
- muted for no deadline


### 3. Complete Subtask

When user marks a subtask complete:
- `status = completed`
- `completed_at = now`
- row moves to completed area or gets completed styling

When user reopens:
- `status = open`
- `completed_at = null`


## Deadline Rules

Subtask deadline is independent from task deadline, but should still be validated sensibly.

Recommended rules:
- allow blank deadline
- if parent task has `end_date`, subtask deadline can exceed it only with a warning, not a hard block
- overdue means:
  - `status = open`
  - `deadline < today`


## Task History Integration

This is important.

The main task history/timeline should show subtask events the same way effort allocation currently appears in task history.

Examples of history events:
- `Subtask added: Prepare final draft`
- `Subtask deadline set to 2026-04-18`
- `Subtask completed: Prepare final draft`
- `Subtask reopened: Prepare final draft`
- `Subtask updated: Prepare final draft`

This keeps the main task timeline meaningful without adding another reporting surface.


## Timeline Display

In the task history timeline, subtask events should appear mixed with existing task events in chronological order.

Suggested visual treatment:
- use a dedicated icon for subtask events
- label the event type clearly:
  - `Subtask Added`
  - `Subtask Completed`
  - `Subtask Reopened`
  - `Subtask Deadline Updated`

This should feel similar to effort log entries, but clearly separate from them.


## Suggested Data Model

### `subtasks`

Recommended columns:

```sql
id
task_id
title
description
deadline
status
sort_order
created_at
updated_at
completed_at
```

Status enum:
- `open`
- `completed`


### `task_history`

If there is already a task history/event table, subtask changes should write into it.

If not, add a generic task event table:

```sql
id
task_id
event_type
event_label
event_body
created_at
created_by
meta_json
```

Subtask events can then be stored cleanly and rendered in the main task timeline.


## API / Backend Behavior

Suggested endpoints:
- `POST /tasks/{task_code}/subtasks`
- `POST /tasks/{task_code}/subtasks/{subtask_id}`
- `POST /tasks/{task_code}/subtasks/{subtask_id}/complete`
- `POST /tasks/{task_code}/subtasks/{subtask_id}/reopen`
- `POST /tasks/{task_code}/subtasks/{subtask_id}/delete`

Each write action should also create a task history event.


## UI Recommendation

### Task Detail Page

Add a `Subtasks` panel with:
- `Add Subtask` button
- compact rows
- checkbox for complete
- title
- deadline badge
- edit action

Do not place subtasks inside the existing effort log timeline directly.
They should have their own clean section, while their events also appear in the task history timeline.


## Reporting Impact

Subtasks should not affect:
- logged hours
- effort booked
- chargeable hours
- work-rate

Subtasks are execution checkpoints, not worklog units.


## Minimal MVP

The first version should include only:
- create subtask
- deadline
- mark complete / reopen
- show subtasks on task detail page
- write subtask events into task history timeline

Do not add:
- nested subtasks
- assignee per subtask
- hours per subtask
- dashboard/report rollups


## Future Extensions

Only if needed later:
- drag-and-drop ordering
- filter open vs completed subtasks
- due-soon badge count on parent task
- auto-close parent task when all subtasks are completed

This should not be part of the first implementation.


## Summary

Subtasks should behave like lightweight checklist items with deadlines, not mini tasks.

The design should optimize for:
- fast breakdown of work
- clear visibility of pending steps
- visible completion trail in task history
- no extra effort logging complexity
