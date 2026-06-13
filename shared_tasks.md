# Shared Tasks

## Objective

Add delegated shared tasks to ProTrack so a task can be assigned to another person while the original creator keeps control of the task definition. The assigned person can work on the task, log hours, and discuss clarifications with the creator.

This feature is meant for task delegation and collaboration, not multi-owner task editing.

## Core Principle

A shared task has two important people:

- `Creator`: the person who created or delegated the task
- `Assignee`: the person expected to execute the task

The creator owns the task definition and final closure. The assignee owns execution updates, effort logging, and discussion.

## Recommended First Version

Build shared tasks as a single-task delegation feature first.

Do not start with a full shared task list or generic collaboration workspace. Those can be added later after the delegated task behavior is stable.

## Permissions

| Action | Creator / Manager | Assignee |
| --- | --- | --- |
| View task | Yes | Yes |
| Edit title | Yes | No |
| Edit description | Yes | No |
| Edit project | Yes | No |
| Edit start date / due date | Yes | No |
| Edit estimate | Yes | No |
| Change assignee | Yes | No |
| Log hours | Yes | Yes |
| Add comments | Yes | Yes |
| Mark work done | Yes | Yes |
| Accept and close task | Yes | No |
| Request rework | Yes | No |
| Mark stalled | Yes | Yes, with reason |

Managers and admins should have creator-level access for tasks within their allowed organization/team scope.

## Status Flow

Use a workflow that separates execution from creator approval:

1. `Assigned`
2. `In Progress`
3. `Work Done`
4. `Accepted`
5. `Closed`

For problems or clarification:

1. `Assigned`
2. `In Progress`
3. `Stalled`
4. `In Progress`
5. `Work Done`
6. `Accepted`
7. `Closed`

For rejected work:

1. `Work Done`
2. `Rework Needed`
3. `In Progress`
4. `Work Done`

The assignee can mark work as done, but the creator should accept and close the task.

## Discussion

Shared tasks should have a task-level discussion thread separate from time-log comments.

Discussion comments are used for:

- clarifications
- blockers
- review notes
- creator feedback
- assignee questions
- rework explanation

Time-log comments should continue to describe the work performed during booked hours.

## Timeline

Each shared task should show a combined timeline:

- comments
- time logs
- status changes
- assignee changes
- stalled reasons
- work-done submissions
- creator acceptance or rework requests

This gives both people a single place to understand task history.

## Notifications

Basic notifications should be added for:

- task assigned to a person
- assignee adds a comment
- creator adds a comment
- assignee marks work done
- creator requests rework
- task is marked stalled
- task is accepted or closed

Notifications can start inside ProTrack. Email or external messaging can be added later.

## Stalled Task Handling

The assignee should be allowed to mark the task as stalled with a required reason.

The creator or manager can then:

- clarify the task
- change due date
- reassign the task
- request continuation
- close the task if no longer required

## Change Requests

The assignee should not directly change core planning fields in the first version. Instead, provide lightweight request actions:

- request due date change
- request estimate change
- request scope clarification
- request reassignment

Each request should create a discussion/timeline entry.

## Reporting

Logged hours must count under the person who actually logged the effort.

Reports should support:

- tasks created by me but assigned to others
- tasks assigned to me by others
- shared tasks waiting for my acceptance
- shared tasks where I am blocked
- shared task effort by assignee

## UI Indicators

Shared tasks should have a clear visual marker wherever tasks appear.

The marker should indicate:

- this task was delegated/shared
- who created it
- who is assigned to execute it
- whether it is waiting for assignee action or creator action

## Later Enhancements

After the first version is stable, consider:

- shared task lists for meeting action trackers
- multiple contributors on a single task
- attachments in comments
- mentions
- external notifications
- approval SLAs
- comment reactions or acknowledgement
- recurring delegated tasks
- configurable shared-task workflows

## Decision

Build shared tasks as delegated tasks with discussion. The creator keeps edit and closure control. The assignee can log hours, comment, mark work done, and raise blockers or change requests.
