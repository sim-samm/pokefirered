# Agent notes

## Git (repel_calc / agent work)

- **`master`** is what users download from; keep it current.
- Integrate on **`cursor/dev-2d7c`**. After a PR merges: `git checkout cursor/dev-2d7c && git pull origin master` (reset dev to remote `master`, then cherry-pick or commit new work).
- Open PRs **`cursor/dev-2d7c` → `master`** (or short-lived `cursor/<topic>-2d7c` branches) with titles that name the work (e.g. `Pythonista: UTF-8 JSON load`).
- One push per finished change set; avoid extra topic branches unless merging in parallel.

## Pythonista / iOS tap UIs

When creating or debugging Pythonista `ui` scripts (including `tools/repel_calc/repel_gui.py`), read and follow:

**`.cursor/skills/pythonista-ui/SKILL.md`**

That skill encodes crash-prone layout/present rules, search-first phone patterns, and how to keep shared logic importable without `ui` on desktop.
