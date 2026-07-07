# ConvergenceKanban Team Workflow

This guide is for humans using a ConvergenceKanban deployment for day-to-day
task and bug tracking. AI agents should fetch the live agent guide from
`/api/agent-guide`.

## Main Surfaces

| Surface | Use it for |
|---------|------------|
| `/` | Project, workstream, task, blocker, review, and activity tracking |
| `/bugs` | QA and agent bug triage, fix metadata, and verification status |
| `/analytics` | Burndown, bug trend, workload, blocker aging, and Gantt views |
| `/api/agent-guide` | Live REST workflow guide for coding agents |
| Feishu Bitable | Optional human-friendly mirror for teams already working in Feishu |

## Daily Task Flow

1. Create work under the right project and workstream.
2. Use task statuses consistently:
   - `todo` — not started
   - `doing` — actively owned
   - `in_review` — agent or teammate says the work is ready for human review
   - `done` — human-approved completion
   - `blocked` — cannot progress; add a blocker or comment
   - `abandoned` — intentionally stopped
3. Prefer comments on tasks for progress and handoff notes.
4. Use subtasks for concrete child work that should stay attached to a parent
   task instead of creating sibling tasks with ambiguous names.

## Bug Flow

The bug pipeline is:

`open -> investigating -> fixing -> fix_complete -> to_verify -> resolved -> closed`

- `fix_complete` means the fix landed in an MR/commit and is ready for
  daily QA spot-check.
- `to_verify` means the fix is included in a weekly/monthly release build and
  is ready for formal release verification.
- `resolved` means QA verified the fix.
- `closed` means the item is finished and no longer needs tracking.

When moving a bug to `fix_complete`, `to_verify`, or `resolved`, always fill:

| Field | Purpose |
|-------|---------|
| `fix_method` | What changed and why: MR, commits, files, root cause |
| `fix_version` | Where QA can verify it: branch, commit, build, release |
| `fix_date` | Date the fix landed or entered the release build |

Link bugs to the tasks or workstreams that own the fix. This keeps QA status,
agent work, and team planning connected.

## Feishu Sync Expectations

Feishu Bitable is a mirror, not a replacement for the kanban API. The kanban
database remains the source of truth.

- Normal sync is periodic, so changes can lag briefly.
- If Feishu and kanban edit the same field at the same time, the conflict
  appears in Sync Conflicts.
- Open Sync Conflicts from the header button to review unresolved conflicts
  and the current sync health summary.
- The sync health panel shows the state file update time, unresolved conflict
  count, and synced record coverage for projects, tasks, QA bugs, and RD bugs.

## Working With AI Agents

Register each agent as a bot user before it works on the board. Use the
`{firstname}-{tool}` naming pattern, for example `alice-codex` or
`bob-claude`.

Agents should:

- fetch `/api/agent-guide?format=quickstart` at session start;
- use `X-Kanban-User` on every mutation;
- claim existing tasks before creating new ones;
- move finished task work to `in_review`, not `done`;
- create bugs with `source: "agent"`;
- move fixed bugs to `fix_complete` with fix metadata;
- let humans or QA promote release-build fixes to `to_verify` and then
  `resolved`.
