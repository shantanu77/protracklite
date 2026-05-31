# AI Work Summary Spec

## Objective

Add an `AI Work Summary` flow to the Monday Report so a user can generate a short weekly work summary from the tasks they actually worked on in the previous week.

The summary should:

- be generated from selected tasks worked during the week
- use task name, task description, time-log comments, booked effort, and leave context
- be saved for that user and that week
- be shown at the top of the Monday Report once generated
- be limited to one short paragraph, ideally no more than 4 to 5 lines


## Product Intent

The Monday Report currently shows structured weekly evidence:

- tasks worked last week
- total booked hours per task
- detailed time-log comments for last week
- completed and pending tasks
- leave and day-allocation strip

This feature turns that evidence into a reusable weekly narrative, without forcing the user to manually write it.


## Scope

Phase 1 covers:

- user-triggered AI summary generation from the Monday Report
- task selection via checkbox
- persisted weekly summary per user per week
- display of saved summary at the top of the Monday Report
- hide the `AI Work Summary` button once a summary already exists

Phase 1 does not cover:

- regenerate or edit summary after generation
- manager/admin generation on behalf of employees
- exporting summaries
- monthly rollups from weekly summaries
- approval workflow


## UX

### 1. Monday Report Top Section

On `/solulever/reports/monday`, show the weekly summary panel before the existing stats and before the existing Monday report sections.

Behavior:

- if a weekly summary exists:
  - show it as the first panel on the page
  - title: `Weekly AI Summary`
  - subtitle: week range, for example `26 May 2026 to 01 Jun 2026`
  - body: saved generated paragraph
  - optionally show metadata in small text:
    - generated at
    - based on `N` selected tasks

- if a weekly summary does not exist:
  - show an `AI Work Summary` button in the page-head action area
  - clicking it opens a modal


### 2. AI Work Summary Modal

The modal should list tasks from `Worked Last Week`, because that section already represents all tasks where the user booked effort during the previous week.

Each row should show:

- checkbox
- task ID
- task name
- total effort booked for that task during the previous week
- optional short status badge

The modal should also show:

- previous week date range
- total booked hours in the week
- leave summary for that week
- helper text explaining that selected task details and work logs will be used to draft the summary

CTA:

- primary button: `Generate Summary`
- secondary button: close/cancel

Validation:

- at least one task must be selected
- if no tasks were worked last week, do not show the button; instead show a muted note that no AI summary can be generated because no booked work exists for the previous week


### 3. Post-Generation Behavior

After summary generation:

- save the summary
- redirect back to Monday Report
- show the generated summary at the top
- hide the `AI Work Summary` button


## Data Model

Add a new table dedicated to weekly summaries.

Recommended table: `weekly_ai_summaries`

Suggested columns:

- `id`
- `org_id`
- `user_id`
- `week_start`
- `week_end`
- `summary_text`
- `selected_task_ids_json`
- `total_selected_hours`
- `input_snapshot_json`
- `model_name`
- `prompt_version`
- `generated_at`
- `created_at`
- `updated_at`

Constraints:

- unique on `(org_id, user_id, week_start)`

Why a dedicated table is better than storing this elsewhere:

- one summary belongs to one user for one reporting week
- it needs a permanent saved output
- it may later support history, export, manager review, and regeneration audit


## Data Inputs For Summary Generation

The AI input should be assembled from the previous week only.

### Required Inputs

- user full name
- previous week start and end date
- total booked hours in the week
- available hours in the week
- booking percentage for the week
- leave entries in the week
- selected tasks only

For each selected task:

- task ID
- task name
- task description
- task status
- task start date
- task end date
- total booked hours for previous week
- all previous-week time-log comments for that task
- all previous-week time-log entries with date and hours


### Optional Helpful Inputs

- whether task was closed in the previous week
- whether task is still pending
- whether task is stalled
- stalled reason if present
- estimate vs actual for completed tasks


## Which Tasks Should Be Selectable

Source of selectable tasks:

- `report.worked_last_week_tasks`

This is the correct source because:

- the user explicitly asked to show the task and total effort put during the week
- this section already reflects actual booked effort in the prior week
- it avoids clutter from backlog or untouched tasks

Selection order in UI:

- sort by previous-week effort descending
- then by task ID


## Prompt Design

The model should not invent work. It should summarize only the selected inputs.

### System Prompt Requirements

The prompt should instruct the model to:

- write a concise weekly work summary in one paragraph
- keep it professional and factual
- stay within 4 to 5 short lines of typical UI width
- focus on work completed, progress made, major effort areas, and relevant blockers
- mention leave only if it materially affected the week
- use plain business language
- avoid bullet points
- avoid exaggeration
- avoid mentioning that AI generated the text
- avoid hallucinating tasks, outcomes, or meetings not present in the input


### Output Requirements

Expected output:

- one paragraph only
- target length about `350` to `550` characters
- hard upper limit recommended at `700` characters after trimming

If the model returns something longer:

- trim safely at sentence boundary if possible
- otherwise reject and retry once with a stricter prompt


## Example Output Shape

Example only:

`Last week I focused primarily on API integration, dashboard fixes, and manager-role rollout work across four active tasks, logging 34.5 hours in total. Key progress included closing the manager visibility changes, stabilizing admin user flows, and improving weekly reporting interactions, while some planned work remained open for carry-forward into the current week. Leave impact was minimal, and effort was concentrated on delivery-critical engineering tasks with clear movement across implementation and production deployment.`


## Permissions

Phase 1 permissions:

- employee can generate their own weekly summary
- manager can view their own summary only when acting as a normal user on their own Monday Report
- admin has no special generation path in Phase 1

Access rules:

- a user can only create or view their own weekly summary from their own Monday Report page
- no cross-user generation endpoint in Phase 1


## API and Route Design

Recommended additions:

### Read Path

Extend `monday_report(...)` to include:

- `weekly_ai_summary`
- `can_generate_weekly_ai_summary`
- `ai_summary_candidate_tasks`

### Write Path

Add a new POST route:

- `POST /{org_slug}/reports/monday/ai-summary`

Form payload:

- `selected_task_codes[]`

Server behavior:

1. resolve the authenticated user
2. determine previous week range
3. reject if a summary already exists for that user and week
4. load selected tasks only from worked-last-week task set
5. assemble AI input payload
6. call OpenAI
7. validate and trim output
8. save record
9. redirect to Monday Report


## AI Integration

Reuse the existing OpenAI integration pattern already used in the app for:

- list extraction
- bulk task extraction

Recommended new helper:

- `generate_weekly_ai_summary(...)`

Suggested placement:

- `app/main.py` initially, to stay consistent with the current OpenAI helpers
- later this can be moved to a dedicated AI service module if the feature grows

Recommended config:

- reuse `settings.openai_api_key`
- start with `settings.openai_backlog_model`
- later add a dedicated config like `openai_summary_model` if needed


## Input Snapshot

Store a structured snapshot of the generation input in JSON.

Reason:

- helps debugging poor summaries
- supports auditability
- supports later regenerate capability
- helps compare prompt versions and model behavior

The snapshot should include:

- week metadata
- selected task IDs
- selected task names
- per-task previous-week hours
- per-task comments used
- leave summary used
- totals used


## Failure Handling

If OpenAI is not configured:

- do not show a broken flow
- either hide the `AI Work Summary` button entirely, or show it disabled with text like `AI summary is not configured`

If generation fails:

- do not save partial data
- redirect back to Monday Report
- show a user-visible error flash/message:
  - `Unable to generate weekly summary right now. Please try again.`

If selected tasks are invalid:

- reject with `400`
- do not generate from tasks outside the user’s previous-week worked set


## Validation Rules

- one saved summary per user per week
- selected tasks must belong to the authenticated user
- selected tasks must have previous-week booked effort
- at least one task must be selected
- generated summary must not be empty
- generated summary should be sanitized before rendering


## Display Rules

The saved summary should appear as the first substantive content block after the page header.

Recommended block layout:

- title: `Weekly AI Summary`
- week range
- summary paragraph
- optional metadata line:
  - `Generated on 31 May 2026 from 4 selected tasks`

The `AI Work Summary` button should only show when:

- OpenAI is configured
- no saved summary exists for that previous week
- there is at least one candidate task in `worked_last_week_tasks`


## Edge Cases

### 1. User booked hours but left comments weak or generic

Still generate, but rely more on:

- task titles
- task descriptions
- effort totals

### 2. User selected only one task

Allowed. The summary should still work.

### 3. User was on leave for most of the week

Summary should mention reduced availability only if leave materially shaped the week.

### 4. User has a saved summary and later logs more hours against the previous week

Phase 1 behavior:

- keep the saved summary unchanged
- do not auto-regenerate
- button remains hidden because a summary already exists

This is acceptable for Phase 1 and keeps behavior deterministic.


## Recommended Implementation Order

1. Add `weekly_ai_summaries` table and model
2. Extend `monday_report(...)` payload with existing summary and candidate-task metadata
3. Add top summary panel to `monday_report.html`
4. Add `AI Work Summary` button and selection modal
5. Add POST route for generation
6. Add OpenAI helper for weekly summary generation
7. Save summary and input snapshot
8. Add basic error handling and success messaging


## Future Phase 2 Possibilities

- regenerate summary
- allow manual editing after generation
- manager-generated summaries for direct reports
- monthly AI summary from weekly summaries
- include KPI or goals context
- summary approval workflow
- export to appraisal/review documents


## Final Recommendation

Build this as a persisted weekly artifact, not a transient modal result.

The right product shape is:

- generate once from selected worked tasks
- save it for that week
- show it first on Monday Report
- keep the generation path simple and constrained in Phase 1

That keeps the user experience clean, makes the output reusable, and aligns well with the current Monday Report structure.
