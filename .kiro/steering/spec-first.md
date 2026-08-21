---
inclusion: auto
---

# Spec-First Development

## Rule

All development work MUST follow the spec workflow before any implementation begins. This applies to features, bugfixes, and tasks regardless of size.

## Process

1. **Before writing any code**, create a spec via the spec workflow (Requirements -> Design -> Tasks).
2. If the user starts implementation directly (e.g. "pick up SP-123", "lets build X", "implement Y"), **stop and remind them**:
   - "This work needs a spec first. Want to start with requirements or a technical design?"
3. Only proceed to implementation after the spec task list is generated and approved.

## Exceptions

- Trivial config changes or typo fixes (< 5 minutes of work) may skip the spec.
- Spikes and research tasks that produce documentation rather than code may skip formal specs.

## Reminder Trigger

If you detect any of these patterns without an existing spec for the work:
- Transitioning a Jira ticket to In Progress
- Creating a feature branch
- Writing implementation code for a new feature/fix

-> Pause and ask: "Should we create a spec for this first?"
