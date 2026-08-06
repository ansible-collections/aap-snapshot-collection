# Skills Eval Suite

Tests whether the agent skills improve outcomes when reviewing or authoring
code in aap-snapshot-collection.

Uses the shared [skill-evals](https://github.com/ansible/ai-helpers/tree/main/experimental/skills/skill-evals)
framework from [ansible/ai-helpers](https://github.com/ansible/ai-helpers).

## Prerequisites

Install the skill-evals scripts using [npx skills](https://github.com/ansible/ai-helpers/blob/main/docs/npx-skills.md):

```bash
npx skills add ansible/ai-helpers
```

Select `skill-evals` from the experimental category when prompted.

## Usage

```bash
# Run all evals (with and without skills, grades, and benchmarks)
python3 ~/.claude/skills/skill-evals/scripts/run_evals_claude.py \
  --evals-file .agents/skills/evals/evals.json \
  --skills-dir .agents/skills

# Single eval
python3 ~/.claude/skills/skill-evals/scripts/run_evals_claude.py \
  --evals-file .agents/skills/evals/evals.json \
  --skills-dir .agents/skills \
  --eval pr-96-db-name-username-differ

# Multiple runs for variance analysis
python3 ~/.claude/skills/skill-evals/scripts/run_evals_claude.py \
  --evals-file .agents/skills/evals/evals.json \
  --skills-dir .agents/skills \
  --runs 3

# Grade a previous run manually
python3 ~/.claude/skills/skill-evals/scripts/grade.py \
  .agents/skills/evals/workspace/iteration-N \
  --evals-file .agents/skills/evals/evals.json
```

## Evals

| ID | Type | Description |
|----|------|--------------|
| pr-96-db-name-username-differ | review | PostgreSQL query missing `login_db` when DB name differs from DB username |
| authoring-fifth-component | authoring | Add a 5th AAP component following the delegator-role pattern |
| review-postgresql-db-export-nolog-gap | review | Reviewer should catch the missing `no_log` on the RPM/containerized dump task in `roles/postgresql/tasks/db_export.yml` |

## Adding a New Eval

1. For review evals: save the diff with `gh pr diff <NUMBER> > diffs/pr-<NUMBER>-<slug>.patch`
2. Add an entry to `evals.json` with assertions to check for
3. For authoring evals: set `"type": "authoring"` and use `"match": "absent"` on assertions
4. Run the eval suite
