---
name: init
description: Repository Initialization Assistant. Scans project structure, identifies stack, and creates clean AGENTS.md guidelines.
---

# Johnston Initialization Skill

You are assisting with initializing `AGENTS.md` guidelines for this repository.

## Steps to Perform
1. **Analyze Project Structure**:
   - Inspect top-level files (`pyproject.toml`, `package.json`, `Cargo.toml`, `go.mod`, etc.).
   - List key directories, entry points, and existing docs.

2. **Detect Tech Stack & Tooling**:
   - Package manager, test runner, linters, formatters, build commands.

3. **Generate AGENTS.md**:
   - Write structured project instructions covering:
     - Project Overview
     - Tech Stack & Commands
     - Code Style & Conventions
     - Testing Guidelines