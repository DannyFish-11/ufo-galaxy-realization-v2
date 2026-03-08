---
name: github
description: "GitHub operations via gh CLI: issues, PRs, CI runs"
version: "1.0.0"
author: "Galaxy"
tags: ["github", "git", "cli"]
metadata:
  requires:
    bins: ["gh"]
---

# GitHub Skill

Use the `gh` CLI to interact with GitHub.

## When to Use

✅ **USE this skill when:**
- Checking PR status
- Creating issues
- Viewing CI status

## Setup

```bash
gh auth login
```

## Commands

### Pull Requests

```bash
# List PRs
gh pr list --repo {repo}

# View PR
gh pr view {pr_number} --repo {repo}

# Create PR
gh pr create --title "{title}" --body "{body}"
```

### Issues

```bash
# List issues
gh issue list --repo {repo}

# Create issue
gh issue create --title "{title}" --body "{body}"
```

### CI/CD

```bash
# Check CI status
gh pr checks {pr_number}

# View workflow runs
gh run list --repo {repo}
```
