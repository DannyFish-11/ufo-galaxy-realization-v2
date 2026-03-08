---
name: weather
description: "Get current weather and forecasts via wttr.in"
version: "1.0.0"
author: "Galaxy"
tags: ["weather", "api", "forecast"]
homepage: "https://wttr.in"
---

# Weather Skill

Get current weather conditions and forecasts.

## When to Use

✅ **USE this skill when:**
- "What's the weather?"
- "Will it rain today?"
- "Temperature in [city]"
- "Weather forecast for the week"

## When NOT to Use

❌ **DON'T use this skill when:**
- Historical weather data
- Climate analysis
- Severe weather alerts

## Commands

### Current Weather

```bash
# One-line summary
curl "wttr.in/{city}?format=3"

# Detailed conditions
curl "wttr.in/{city}?0"
```

### Forecasts

```bash
# 3-day forecast
curl "wtt.in/{city}"

# JSON output
curl "wttr.in/{city}?format=j1"
```

## Examples

**"What's the weather in London?"**

```bash
curl -s "wttr.in/London?format=%l:+%c+%t+(feels+like+%f)"
```

**"Will it rain in Tokyo?"**

```bash
curl -s "wttr.in/Tokyo?format=%l:+%c+%p"
```
