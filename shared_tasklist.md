# Shared Task List — Concept Note

## 1. Purpose

Shared Task List is a lightweight coordination feature for group-driven action items.

It solves a common situation:
- A team meeting happens, for example a PMG group meeting.
- The group identifies 10-20 follow-up actions.
- These actions need to be captured quickly.
- Different people may own different actions.
- Everyone in the group should be able to see the full list and track progress.

The feature introduces a new entity called a **Shared Task List**. A Shared Task List acts as a visible container for a related set of tasks. Tasks inside the list behave like normal ProtrackLite tasks or backlog items, but carry additional shared visibility and shared-task identity.

---

## 2. Core Principle

A Shared Task List is created only through the **Smart Add** flow.

This means:
- Users do not manually create each shared task one by one.
- They define a list name, short description, the people with whom the list is shared, and paste the raw task text.
- AI interprets the pasted content and generates structured tasks.

Each generated task then behaves like a regular task in the system, with these differences:
- It belongs to a Shared Task List.
- It is visible to the people included in that list.
- It carries a visual shared-task indicator.
- Time logs for that task must show the identity of the person who logged effort.

---

## 3. Example Use Case

Example: PMG weekly meeting

- A PMG meeting ends with 20 action items.
- One person opens Shared Task List and clicks `Add New`.
- They create a list such as `PMG Apr Review`.
- They add a short description such as `Action items from PMG review meeting`.
- They select the meeting participants or relevant action owners.
- They paste the raw notes or bullet list of action items.
- AI converts the notes into structured tasks.
- The generated tasks are stored under that shared list.
- Later, an admin, manager, or participant can open the list and assign task owners individually.
- Start date, end date, and other planning fields can either be AI-generated or edited later.

This becomes the app representation of a group action-tracker.

---

## 4. New Navigation / UI Area

A new top-level section will be introduced in the app:

- `Shared Tasks`

This section will list previously created Shared Task Lists by name.

Expected behavior:
- Each list name is clickable.
- A menu option `Add New` is available in the Shared Tasks section.
- Clicking `Add New` opens a creation window / modal / page.

The Shared Tasks section is list-oriented, not task-oriented.
The first level shows the shared lists.
The second level shows the tasks inside a selected list.

---

## 5. Shared Task List Creation Flow

Shared Task List is added only through **Smart Add**.

### 5.1 Entry Action
- User opens `Shared Tasks`
- User clicks `Add New`

### 5.2 Create Shared Task List Window

The create window should capture:

- `List Name`
  - Required
  - Maximum 16 characters
  - Should be short and easy to recognize in navigation

- `Short Description`
  - Optional but recommended
  - Brief context of the meeting, discussion, or workstream

- `Shared With`
  - Required
  - Multi-select list of people
  - These users define the visibility group for the shared list and its tasks

- `Task Input`
  - Required
  - Freeform pasted text
  - Can be meeting notes, bullet points, email content, or plain action lines

- `Create With AI`
  - Triggers AI extraction and structured task generation

---

## 6. AI Task Generation Rules

The AI should generate the task list from the pasted content.

AI should:
- Split raw input into individual tasks
- Create a clean task title for each item
- Generate a useful task description where needed
- Infer `start_date` if mentioned or clearly implied
- Infer `end_date` if mentioned or clearly implied
- Infer effort or other planning hints if supported by existing Smart Add behavior
- Detect whether the item is better represented as:
  - a planned task, or
  - a backlog-style task without schedule

AI output should still allow human review before final save if the Smart Add workflow already supports review.

### 6.1 AI Assignment Behavior

By default, AI should not force an owner unless ownership is clearly stated in the source text.

Possible rules:
- If text clearly says `Ravi to prepare deck`, owner may be inferred as Ravi
- If no clear owner is detected, the task remains unassigned or assigned to the creator temporarily, depending on system constraints
- Ownership must remain editable after creation

### 6.2 AI Planning Behavior

AI may prefill:
- start date
- end date
- estimated hours
- task type / activity type
- backlog vs scheduled status

These fields remain editable later.

---

## 7. Shared Task List Detail View

When the user clicks a Shared Task List name, the system opens the detail view for that list.

The detail view should show:
- List name
- Short description
- People with whom the list is shared
- Created by
- Created on
- Full list of generated tasks

Each task in the list should support the following controls:
- View task details
- Edit task
- Change owner
- Set or edit start date
- Set or edit end date
- Update status
- Log effort

This view is the coordination surface for the group.

---

## 8. Ownership Model

Each task under a Shared Task List can have an individual owner.

Expected behavior:
- Owner can be selected from users in the organization
- In most cases owner should preferably be one of the people included in `Shared With`
- Admins may retain the ability to assign broader ownership if needed

Ownership is task-level, not list-level.

That means:
- One shared list can contain tasks owned by different people
- Some tasks may remain unassigned initially
- Ownership can be decided later after the AI-generated list is reviewed

---

## 9. Visibility Rules

Visibility is the key difference between a normal task and a shared task.

### 9.1 Shared List Visibility

A Shared Task List is visible to:
- the creator
- all users selected in `Shared With`
- admins, if admin visibility rules apply globally

### 9.2 Shared Task Visibility

A task inside a Shared Task List is visible to:
- all users included in the parent list's `Shared With`
- the assigned owner of the task
- the person currently working on it, if different from the assigned owner
- admins

This rule is important because ownership can change over time, and collaboration may happen across the group.

### 9.3 Relationship With Normal Task Privacy

Shared task visibility should override the standard idea of purely personal visibility.

So:
- A shared task should not become hidden from the shared group just because the owner changes
- A shared task is still a normal task operationally, but with group visibility enforced by the shared-list membership model

---

## 10. Shared Task Identity

Once created, a shared task behaves like any other task in the system:
- it can be scheduled
- it can remain in backlog
- it can be started
- it can be stalled
- it can be closed
- it can receive time logs
- it can appear in task lists and reports where relevant

However, it must carry a small visual marker indicating that it is a shared task.

### 10.1 Shared Icon

Wherever tasks are displayed, a shared task should show a small icon or marker.

The icon should communicate:
- this task belongs to a shared list
- the task is group-visible

This icon should appear at least in:
- Shared Task List detail view
- task cards
- task detail page
- dashboards or list views where the task is shown

---

## 11. Time Logging Behavior

Time logging on a shared task follows normal task behavior with one additional requirement:

- the effort log must show **who** logged the hours

This is required because multiple people may contribute effort to the same shared task.

### 11.1 Time Log Display Rule

Wherever hour logs are displayed for a shared task, each log row should show:
- person name, or
- email id

Recommended display:
- date
- hours
- person name / email
- notes

This should apply in:
- task detail timeline
- task log drawer / expand views
- reports or summaries where time-log detail is shown

### 11.2 Multi-Person Contribution

A shared task may have:
- one owner
- multiple contributors

Therefore:
- ownership and effort contributor are separate concepts
- reports should not assume only the owner worked on the task

---

## 12. Functional Expectations

### 12.1 User Can
- create a Shared Task List only through Smart Add
- define list name, short description, shared users, and raw task input
- let AI generate the tasks
- open an existing shared list and see all tasks
- assign a different owner to each task
- edit task planning data such as start date and end date
- treat generated tasks like normal tasks or backlog items
- recognize shared tasks using a small icon
- see who logged time on a shared task

### 12.2 System Must
- maintain parent-child relation between shared list and tasks
- maintain shared visibility across all list members
- preserve normal task lifecycle behavior
- support AI extraction from raw pasted text
- allow later editing of AI-generated outputs
- show contributor identity in time logs for shared tasks

---

## 13. Suggested Data Model Additions

This section is conceptual and may be refined during implementation.

### 13.1 Shared Task Lists

```
shared_task_lists
  id                INT PK
  org_id            INT FK organizations.id
  name              VARCHAR(16)
  short_description VARCHAR(255) NULL
  created_by        INT FK users.id
  created_at        DATETIME
  updated_at        DATETIME
```

### 13.2 Shared Task List Members

```
shared_task_list_members
  id                INT PK
  shared_list_id    INT FK shared_task_lists.id
  user_id           INT FK users.id
  added_at          DATETIME
  UNIQUE(shared_list_id, user_id)
```

### 13.3 Task Linkage

Add to `tasks`:

```
shared_list_id      INT NULL FK shared_task_lists.id
is_shared_task      BOOLEAN DEFAULT FALSE
```

This makes each task still behave as a normal task, while preserving shared-task identity.

---

## 14. UX Notes

### 14.1 Why Separate Shared Lists From Normal Tasks

This feature should not overload the normal task-creation screen.

Reason:
- Shared-task capture is meeting-driven and bulk-oriented
- Normal task creation is single-task oriented
- Shared visibility and shared ownership need a separate mental model

### 14.2 Why Smart Add Only

Smart Add is the right creation mode because:
- group action items often arrive as rough text
- users usually copy from notes, chats, or email
- manually creating 20 tasks is slow and error-prone
- AI can structure the tasks much faster

---

## 15. Open Product Decisions

These points should be finalized during design:

1. Should task owner be mandatory at creation time, or allowed to remain blank?
2. Should AI assign owners automatically when names are recognized, or only suggest them?
3. Can a task be reassigned to someone outside the shared group?
4. If a new person is assigned later, should they automatically be added to shared visibility?
5. Should Shared Tasks get their own filters and reports?
6. Should a Shared Task List be closable / archivable as a list once all items are completed?
7. Should users be allowed to manually add one more task into an existing shared list after AI creation?

---

## 16. Summary

Shared Task List is a collaboration-focused extension of the existing task model.

It is best suited for:
- meeting action items
- review follow-ups
- management group actions
- multi-person coordination work

The design principle is simple:
- capture once using Smart Add
- share visibility with the relevant group
- allow task-level ownership
- preserve normal task behavior
- clearly mark the task as shared
- show contributor identity in all time-log displays

This keeps ProtrackLite lightweight while making it more effective for team-driven execution.
