# Lists Specification

## Purpose

Lists are lightweight checklist-style planning objects for reminders, milestone plans, and grouped things-to-do that should not behave like full tasks.

They are intended for cases such as:

- 30 / 60 / 90 day plans
- AI-generated growth plans
- reminder bundles
- preparation checklists
- grouped outcomes that do not need effort logging or deadline-heavy scheduling

Lists are separate from tasks because forcing them into the task model creates noise in Today, Monday Report, Calendar, Dashboard, and work-rate reporting.

## Core Difference From Tasks

### Task

- Has status flow
- Can have start date and end date
- Can have estimated effort
- Supports time logging
- Appears in operational reports
- Used for execution tracking

### List

- Has a title, optional description, optional target date
- Contains many checkable items
- Tracks progress as completed items divided by total items
- Does not require start date, end date, or booked hours
- Does not affect work-rate or task reporting
- Used for lightweight planning and completion tracking

## Data Model

### WorkList

- `id`
- `org_id`
- `owner_user_id`
- `title`
- `description`
- `target_date` nullable
- `is_archived`
- `created_at`
- `updated_at`

### WorkListItem

- `id`
- `work_list_id`
- `title`
- `notes`
- `is_completed`
- `completed_at` nullable
- `sort_order`
- `created_at`
- `updated_at`

## Progress Model

Each list displays:

- total items
- completed items
- progress percentage

Progress formula:

- `completed_items / total_items * 100`

## Required UX

### Lists Workspace

Route:

- `/{org_slug}/lists`

Main experience:

- create a manual list
- create a list using AI
- open an existing list
- tick items complete / incomplete
- see percent complete
- archive a list

Layout:

- left side: create form + list summaries
- right side: selected list details + items

### List Summary Card

Should show:

- title
- optional short description
- completed count
- total count
- progress percentage
- target date when present

### Selected List Detail

Should show:

- title
- description
- target date
- progress
- completed count
- updated date
- item add form
- checklist items with tick boxes

## AI List Creation

### Goal

The user can paste:

- a rough plan
- a reminder dump
- a copied checklist
- a 90-day action plan from AI

The system should create one clean named list in the backend with multiple checklist items.

### Input

- optional list title
- free-form plan text

### Output

One `WorkList` with:

- clean title
- optional description
- optional target date when strongly inferable
- normalized checklist items

### AI Behavior

The model should:

- create one list only
- split combined actions into separate items
- make each item concise and checkable
- preserve user intent
- infer a target date only when reliable

### Fallback

If AI is unavailable:

- split pasted input into one item per bullet or line
- create a list using the supplied title or a fallback title

## Boundaries

Lists should not:

- appear in Today
- appear in Monday Report
- affect Work Rate
- require start/end scheduling
- require hours logging

## Future Extensions

- convert one list item into a task
- convert selected list items into tasks
- sections inside a list
- recurring lists
- team-shared lists
- priorities on items
- drag to reorder items
- archive completed items automatically

## Product Rule

If something needs:

- scheduling
- execution status
- time logging
- operational reporting

use a Task.

If something is:

- a plan
- a reminder bundle
- a milestone checklist
- a set of things to conclude

use a List.
