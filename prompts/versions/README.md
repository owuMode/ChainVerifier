# Prompt Versioning

## Convention

- A prompt lives at `prompts/<folder>/<name>.md`. This is the
  **active** version.
- Older versions may be kept as `prompts/<folder>/<name>@<version>.md`
  (e.g. `planner@v1.md`).
- `PromptManager.get("agent/planner")` loads the unversioned
  `planner.md`.
- `PromptManager.get("agent/planner", version="v1")` loads
  `planner@v1.md`.
- `PromptManager.list_versions("agent/planner")` returns
  `["latest", "v1", "v2", …]`.

## Rules

1. Never overwrite a shipped prompt without preserving the prior
   version if the change is behavioural. Add `<name>@<old-version>.md`.
2. A prompt change is a behavioural change. It deserves a commit,
   a changelog entry, and (when relevant) a test.
3. Prompts are code. They live in source control, they are reviewed,
   they are versioned.
4. `PromptManager` caches prompts in memory. Prompt files are read
   once per process lifetime.

## What not to do

- Do not embed prompts as Python string literals in modules that use
  them. Always load through `PromptManager`.
- Do not edit a prompt file inside a running process and expect the
  change to take effect without a restart.
- Do not rename a shipped versioned file. Add a new one instead.