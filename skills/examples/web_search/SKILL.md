---
name: web_search
description: "Search the web using DuckDuckGo"
version: "1.0.0"
author: "Galaxy"
tags: ["search", "web", "duckduckgo"]
---

# Web Search Skill

Search the web using DuckDuckGo API.

## When to Use

✅ **USE this skill when:**
- "Search for..."
- "Find information about..."
- "Look up..."

## Commands

```bash
# Search (returns JSON)
curl -s "https://api.duckduckgo.com/?q={query}&format=json&no_html=1"

# Instant answer
curl -s "https://api.duckduckgo.com/?q={query}&format=json&no_html=1" | jq '.AbstractText'
```

## Examples

**"Search for Python tutorials"**

```bash
curl -s "https://api.duckduckgo.com/?q=Python+tutorials&format=json&no_html=1"
```
