## Commit message format
- When the user asks for commit text, generate a Git commit message instead of committing.
- Use Conventional Commits format:
  - feat:
  - fix:
  - refactor:
  - docs:
  - chore:
  - test:
- Preferred subject format:
  - `<type>(<scope>): <summary>`
- The subject must be concise, specific, and written in Chinese.
- Do not use vague subjects such as:
  - `update`
  - `fix bugs`
  - `misc changes`

## Commit body rules
- For non-trivial changes, also generate a commit body.
- The body should be written in Chinese.
- The body should explain:
  - what changed
  - why it changed
  - any important notes about usage, compatibility, hardware behavior, or risks
- Do not invent tests, results, or effects that are not supported by the diff or user instructions.
- If the change is trivial, the body may be omitted.
- Output should be easy for the user to copy directly into a Git GUI or terminal.


