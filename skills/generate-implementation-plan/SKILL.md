---
name: generate-implementation-plan
description: Convert a PRD into a milestone-based implementation plan with task checkboxes, scoped file edits, tests, and automated acceptance criteria. Use when asked to create or update a PRD-to-plan task file.
compatibility: Designed for Claude Code or similar agents with filesystem access.
metadata:
  author: local
  version: "1.0"
---

# Generate Implementation Plan (Task Format)

## When to use this skill
Use this skill when the user provides (or references) a PRD and asks for an implementation plan, roadmap, or task breakdown in a milestone checklist format.

## Inputs
- A PRD Markdown file (any format, typically in `docs/`).
- A target output path for the plan file (if not provided, choose a sensible path in `docs/`).

## Output
- A single Markdown file that contains:
  - Assumptions and constraints
  - A milestone task list using checkbox format
  - Each milestone includes goal, work scope, tests, and automated acceptance criteria
  - Overall completion criteria

## Required formatting
- Use an H1 title at the top.
- Include a section: `## Assumptions and Constraints`.
- Include a section: `## Milestones (Task List)`.
- Each milestone must be a task item formatted exactly as:
  - `- [ ] Milestone N — <Title>`
- Under each milestone, indent child bullets by two spaces and use `-` for bullets.
- Include four subsections under each milestone (as bullets):
  - `Goal: ...`
  - `Work scope (exact files + types)`
  - `Tests to add`
  - `Automated acceptance criteria`
- Acceptance criteria must be verifiable automatically (examples: `xcodebuild`, `rg`, scripts, snapshot tests).
- End with `## Overall completion criteria` and 2–5 bullets.

## Planning rules
1. Read the PRD thoroughly and extract:
   - Platform constraints
   - Must-have MVP features
   - Non-goals and explicit cuts
   - Storage layout and model requirements
2. Propose 3–6 sizeable milestones. Each milestone should deliver a cohesive slice of functionality.
3. Assign work to modules according to the project structure (e.g., App/Core/UI/Features).
4. For each milestone, list exact file paths to change and exact new types/functions to add.
5. Prefer adding tests in the matching test target (CoreTests, UITests, FeaturesTests, AppTests).
6. Keep the plan generic enough to fit any PRD but specific enough to be actionable.

## Step-by-step procedure
1. Locate and open the PRD file.
2. Summarize key requirements into a short assumptions section.
3. Define milestones in delivery order (foundation → flows → editor → exports → polish).
4. For each milestone:
   - Define a clear goal.
   - Enumerate file changes and new types/functions.
   - Specify tests that align with the new behavior.
   - Define automated acceptance criteria commands.
5. Add overall completion criteria aligned with the PRD’s acceptance checklist.
6. Save the plan to the requested output path.

## Example output skeleton
```
# <Product> Implementation Plan

## Assumptions and Constraints
- ...

## Milestones (Task List)
- [ ] Milestone 1 — <Title>
  - Goal: ...
  - Work scope (exact files + types)
    - <path>
      - <type/method>
  - Tests to add
    - <test file>
      - <test name>
  - Automated acceptance criteria
    - <command> succeeds.

## Overall completion criteria
- ...
```

## Notes
- Keep descriptions concise and implementation-ready.
- Avoid speculative features not in the PRD.
- Prefer ASCII-only content unless the repo already uses Unicode in docs.
