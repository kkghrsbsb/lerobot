# AGENTS.md

## Documentation Rules
- `docs/src/README.md` is only the mdBook homepage for the current documentation context, not an agent instruction file.
- Keep agent operating rules in AGENTS.md or CLAUDE.md, not in `docs/src/README.md`.
- When changing Markdown files under `docs/src/`, update `docs/src/SUMMARY.md` in the same task.
- When updating `docs/src/SUMMARY.md`, keep category headings such as `- [方案]()` unchanged and add documents as nested child links below them.
- Example: add `  - [用户认证方案](./plan/2026-04-24-user-auth-plan.md)` below `- [方案]()` instead of replacing the category link.
- Use file names with an exact date prefix: `YYYY-MM-DD-kebab-case-topic.md`.

## Documentation Paths
# Overrides the default paths used by /mdplan, /mdreview, /mdexplain, /mdlearn, /mdadr skills.
- Plan documents go in `docs/src/plan/`
- Review documents go in `docs/src/review/`
- Change summary documents go in `docs/src/explain/`
- Learning guides go in `docs/src/learn/`
- Architecture decision records go in `docs/src/adr/`
- Archived documents go in `docs/src/archive/`
- Always update `docs/src/SUMMARY.md` after creating any document under `docs/src/`
- Personal notes go in `docs/src/notes/`
