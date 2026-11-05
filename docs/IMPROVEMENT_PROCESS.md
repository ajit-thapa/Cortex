# Continuous improvement process

Weekly loop: **monitor → plan → implement**. Owner approves; bot proposes and builds.

## Roles and limits
- Owner: sets priorities in `docs/BACKLOG.md`, reviews and merges PRs, deploys via HACS.
- Bot (scheduled task): never merges, never pushes to `main`, never deploys. Works on `auto/*` branches and opens PRs.
- Runtime data (HA logs, live Cortex behaviour) is not reachable from the bot. Runtime findings come from the owner, via issues or notes in `docs/BACKLOG.md`.

## 1. Monitor
- Run `pytest -q`. Any failure is a P1 item.
- Check the latest `Validate` workflow run on `main` (tests, HACS, hassfest). Failing = P1.
- List open GitHub issues. Add each as a backlog item with a link.
- Check `git log` since the last run for unreviewed commits that touch `custom_components/`.

## 2. Plan
- Update `docs/BACKLOG.md`: add new findings, drop resolved items, re-rank.
- Each item has: id, priority (P1–P3), status (`proposed` | `ready` | `in-progress` | `done`), short scope, acceptance check.
- Only items with status `ready` may be implemented. The bot may propose; the owner promotes to `ready`.

## 3. Implement
- At most one `ready` item per run, highest priority first.
- Branch `auto/<id>-<yyyymmdd>` from `main`.
- Test first (`tests/`), smallest change that meets the acceptance check.
- Keep `CLAUDE.md` rules: TypeScript/TSX only in frontend, no CSS classes, `T.*` theme tokens, single-file backend, `Record<string, unknown>` for upserts. This is a Home Assistant integration: follow the existing `custom_components/cortex/` layout.
- Bump `manifest.json` version and `FRONTEND_VERSION` in `__init__.py` together for any user-visible change. Keep them equal.
- Run `pytest -q` until green. Push the branch. Open a PR against `main` with: item id, what changed, test result, how to verify on a real system.
- Mark the item `in-progress` in the PR. Owner moves it to `done` after merge.

## Stop conditions
- Tests red and not fixable in one pass: leave the branch, note the blocker on the item, stop.
- Change would touch the house rule, export guards, or EV charging logic: propose only, do not implement. These need a human check on the real system.
