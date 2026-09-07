---
name: create-role
description: Create and configure specialized Johnston roles and subagents. Use when user says /create-role, wants to create a new role or subagent, customize allowed tools, or set up task-specific agent personas.
hidden: true
---

# Role Creator

Guide the user through creating and configuring custom unified agent roles and subagents in Johnston.

## 1. Storage Locations

Roles are Markdown files with YAML frontmatter stored in:
- **Project roles**: `.johnston/roles/<key>.md` (precedence over global)
- **Global roles**: `~/.johnston/roles/<key>.md` (available in all projects)

## 2. Configuration Schema

```markdown
---
name: Code Reviewer
description: Reviews code changes for security, style, and correctness
scope: subagent
model: anthropic/claude-3-7-sonnet
read_only: true
allowed_tools: [read, search, shell, web_fetch]
---

<scope>
Senior code reviewer. Read-only analysis of changes. Do not perform edits or create files.
</scope>

<rules>
1. Cite file paths and line numbers for every observation.
2. Focus on security vulnerabilities, edge cases, and maintainability.
3. Classify findings by severity: Critical, Warning, Suggestion.
</rules>
```

> **IMPORTANT**: The prompt body MUST start with `<scope>`, `<rules>`, or `<anti_patterns>`. If free-form text precedes them, the entire prompt body is XML-escaped to `&lt;scope&gt;`.

### Frontmatter Fields

| Field | Required | Description |
|---|---|---|
| `key` | No | Unique role identifier (defaults to filename without `.md`). |
| `name` | No | Display name (defaults to capitalized filename key). |
| `description` | Recommended | Summary of role purpose (used in subagent listings and tool prompts). |
| `scope` | No | `any` (default), `subagent`, `main`, `interactive`, or `headless`. |
| `model` | No | Pinned model strictly in `provider/model` format (e.g. `anthropic/claude-3-7-sonnet`, `deepseek/deepseek-chat`, `openai/gpt-4o`). **Note: separate `provider` field is not accepted.** |
| `read_only` | No | `true` or `false` (default). When `true`, mutating tools (`create`, `edit`) are stripped and OS-level sandbox is enabled. |
| `allowed_tools` | No | Whitelist of tools or glob patterns (`[read, search, shell]` or `read, search, shell`). Omit to allow all. **Note: YAML bullet lists (`- tool`) are NOT supported; use bracketed or comma-separated lists.** |
| `disallowed_tools` | No | Blacklist of tools or glob patterns (`[create, edit]` or `create, edit`). |

## 3. Available Builtin Tools

Johnston provides 11 builtin tools:
- `read`: Read files, images, archives (.zip/.tar/.whl/.jar).
- `search`: Grep content, find filenames, or extract code outlines (AST / Tree-sitter).
- `create`: Create new files.
- `edit`: Surgical string replacements in existing files.
- `shell`: Run commands in persistent session (with idle timeouts).
- `manage_shell`: Inspect, poll, or terminate background processes.
- `invoke_subagent`: Launch autonomous child agents in background.
- `manage_subagent`: List or terminate running subagents.
- `ask_user`: Interactive multiple-choice prompts for user feedback.
- `update_plan`: Maintain persistent task list / progress tracking.
- `web_fetch`: Retrieve URL contents as markdown or HTML.

*Note: Non-interactive contexts (subagents and headless runs) automatically disable `invoke_subagent`, `manage_subagent`, `manage_shell`, `ask_user`, and `shell(wait_seconds=...)`.*

## 4. Role Templates

### Code Reviewer (Read-Only Subagent)
```markdown
---
name: Reviewer
description: Rigorous code reviewer for PRs and git diffs
scope: subagent
read_only: true
allowed_tools: [read, search, shell]
---

<scope>
Senior code reviewer. Inspect git diffs and modified code. Do not perform file edits.
</scope>

<rules>
1. Examine diffs or files using `search` and `read`.
2. Check for logic errors, security flaws, performance bottlenecks, and style deviations.
3. Provide actionable suggestions citing exact line numbers.
</rules>
```

### Debugger (Interactive & Subagent Worker)
```markdown
---
name: Debugger
description: Diagnostic specialist for reproducing bugs, analyzing traces, and writing minimal fixes
scope: any
read_only: false
allowed_tools: [read, search, edit, create, shell]
---

<scope>
Root-cause analysis and bug fixing. Produce minimal surgical edits.
</scope>

<rules>
1. Formulate testable hypotheses based on logs or error traces.
2. Verify hypotheses using `read`, `search`, or targeted test runs via `shell`.
3. Apply minimal surgical fixes.
4. Verify resolution with test runs before completing.
</rules>
```

### Security Auditor
```markdown
---
name: Security Auditor
description: Audits dependencies, endpoints, secrets, and auth flows for vulnerabilities
scope: subagent
read_only: true
allowed_tools: [read, search, shell, web_fetch]
---

<scope>
Application security auditor. Identify vulnerabilities and risk patterns without code mutations.
</scope>

<rules>
1. Audit for injection vulnerabilities (SQL, command, template injection).
2. Detect hardcoded secrets, insecure deserialization, or exposed endpoints.
3. Check dependency hygiene and report CVEs.
</rules>
```

## 5. Execution Semantics & Tool Isolation

- **Worktree Isolation**:
  - Subagents running with **write roles** (`read_only: false`) automatically execute inside an isolated Git worktree on an independent branch (`subagent/<title>-<id>`), automatically committing on completion. **Requires workspace to be inside a Git repository**; in non-Git workspaces, executes directly in place.
  - Subagents running with **read-only roles** (`read_only: true`) execute directly within the current workspace without worktree creation, with OS-level sandbox enforced.
- **Non-Interactive Exclusions**:
  - `invoke_subagent`, `manage_subagent`, `manage_shell`, `ask_user`, and `shell(wait_seconds=...)` are automatically disabled in subagent roles to prevent recursive agent loops.

## 6. Creation & Verification Steps

1. **Pre-flight & Requirements**:
   - Determine role key, scope (`subagent` vs `any`), tools, and `read_only` mode.
   - **Provider validation**: If pinning a `model: provider/model`, verify that the provider is supported and connected by running `johnston provider list --json` via `shell`. If missing API credentials, warn the user to set `<PROVIDER>_API_KEY`.
2. **File Authoring**:
   - Use `create` to write `.johnston/roles/<key>.md` (project) or `~/.johnston/roles/<key>.md` (global).
3. **Inspect Role Registration**:
   - Run `johnston roles --json` via `shell`.
   - Verify the role appears with correct name, allowed/disallowed tools, model, and read_only status.
4. **Test Role**:
   - For subagent roles: launch a test task with `invoke_subagent(title="Test <key> execution", prompt="...", type="<key>")`.
   - For interactive roles: cycle with `Tab` in the TUI, or launch with CLI flag `johnston -r <key>` (note: there is no `/role` slash command).

## 7. Good vs Bad Practices

### Good Practices
- **Least Privilege Principle**: Set `read_only: true` for analytical, auditing, and review roles. The runtime strips mutating tools (`create`, `edit`), guaranteeing safety.
- **Isolate Shell for Pure Readers**: If a role is strictly read-only, omit `shell` from `allowed_tools` (`allowed_tools: [read, search]`). Otherwise, the agent can still execute mutating CLI commands like `rm`, `del`, or `sed -i` through shell.
- **Accurate Scope**: Set `scope: subagent` for single-purpose subagents so they do not clutter interactive `Tab` cycling in the TUI.
- **Explain the "Why"**: Structure prompts with `<scope>`, `<rules>`, and rationales instead of dogmatic `NEVER`/`ALWAYS` shouting. LLMs adhere better when the reason is clear.
- **Cost/Latency Optimization**: Pin lightweight models (`model: provider/fast-model`) for mechanical subagent tasks (linting, test execution, typo checking).

### Bad Practices
- **Bloated System Prompts**: Avoid stuffing hundreds of lines of reference manuals into the role prompt body. Put extended documentation in skills with progressive disclosure instead.
- **Vague Descriptions**: Generic descriptions like `description: Helps with python` cause misrouting and over-triggering. Specify exact domains, tools, and trigger triggers.
- **Assuming Worktree Mutations are in Main**: Remember that write-enabled subagents execute in an isolated Git worktree branch (`subagent/...`). Changes must be merged back into the working tree.

