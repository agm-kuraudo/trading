---
inclusion: auto
---

# Ticket Lifecycle

## Status Transitions

### In Progress

The ticket stays In Progress while code is being written and tests are passing.

### Mostly Done

Move to **Mostly Done** when:
- All implementation tasks are complete and verified
- Code is committed and pushed
- PR is created (or code is ready to merge)
- Waiting on PR merge, deployment, or external dependency

### Done

Move to **Done** ONLY when the user explicitly confirms:
- "merge it" / "merged" / "mark it done" / "close it"

## Critical Rules

1. **Completing spec tasks does NOT mean Done.** Tasks complete = push + PR + Mostly Done.
2. **NEVER transition to Done automatically.** Always wait for user confirmation.
3. The only valid automatic transition is: In Progress -> Mostly Done (after PR created).
4. Done is ALWAYS a user-initiated transition.

## After Implementation Tasks Complete

When the final spec task/checkpoint passes, the next steps are:
1. Commit (if not already done)
2. Push the branch
3. Create a PR
4. Add completion comment to Jira
5. Transition to **Mostly Done** (NOT Done)
6. Tell the user the PR is ready for merge

## After PR Merge / Ticket Closed

When the user confirms the PR is merged or the ticket is done:
1. Transition Jira ticket to **Done**
2. Switch to master/main: `git checkout master`
3. Pull latest: `git pull`
4. Prune remote tracking branches: `git fetch --prune`
5. Delete the local feature branch: `git branch -d {branch-name}`
6. Confirm cleanup is complete
