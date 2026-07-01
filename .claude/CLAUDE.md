# AAP Snapshot Collection - Claude Code Instructions

## Agent Skills — CRITICAL

Skills are located at `.agents/skills/<skill-name>/SKILL.md` with detailed
reference docs in `.agents/skills/<skill-name>/references/`.

**If a task or skill instructs you to load a skill and it cannot be found,
STOP and report the error to the user. Do NOT proceed without loading
required skills.** Skills encode team-agreed patterns and checklists —
skipping them silently produces incomplete or incorrect work.

## Coding Standards

Coding standards and authoring guides are provided as Agent Skills in `.agents/skills/`:

- **aap-snapshot-collection-authoring** — Changelog fragments, coding conventions, and contribution workflow
