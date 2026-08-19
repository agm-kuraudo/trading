---
inclusion: auto
---

# File Write Strategy

## Large File Writes

When creating or updating files that are likely to be large (200+ lines), such as design documents, requirements documents, or implementation files:

1. **Write in chunks** - Break the content into multiple sequential write operations (Set-Content for first chunk, Add-Content for subsequent chunks). Each chunk should be no more than ~80 lines.
2. **Never write entire large files in a single tool call** - This causes connection timeouts and aborted operations.
3. **If a write fails or is aborted** - Retry with smaller chunks rather than attempting the same large write again.

## Why

PowerShell here-strings with large content and sub-agent responses with large file writes consistently hit transport-layer timeouts. This is a platform limitation, not a file locking issue.

## Applies To

- Spec documents (requirements.md, design.md, tasks.md)
- Implementation files over 200 lines
- Any file where the full content exceeds ~80 lines in a single write operation
