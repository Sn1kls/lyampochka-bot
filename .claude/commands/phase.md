---
description: Implement one phase of docs/SPEC.md
argument-hint: <phase number, e.g. 0>
---

Implement Phase $ARGUMENTS from docs/SPEC.md §12.

1. Read docs/PROGRESS.md, then only the SPEC sections this phase needs, and docs/api-notes.md if it exists. Do not read the whole repo.
2. Write a short plan (files, tests, open questions) and continue. If anything from SPEC §2.3 this phase depends on is unresolved, stop and ask the owner instead.
3. Implement test-first for `domain/` and `api/`.
4. Run `make check` (from Phase 1 on) until it is green. Fix causes, not tests.
5. Check the phase's "Done when" criteria from the SPEC one by one.
6. Append a dated entry to docs/PROGRESS.md: what was done, decisions taken, open questions, the next step.
7. Show `git status`, then commit with a Conventional Commit message `feat(phase$ARGUMENTS): ...`. Do not push.
8. Report to the owner in Ukrainian, 10 lines max.
