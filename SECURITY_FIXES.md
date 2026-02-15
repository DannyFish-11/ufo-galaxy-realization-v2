# Security Fixes - Hardcoded Credentials

## Summary

This document records all security fixes applied to remove hardcoded credentials from the codebase.

**Total Files Fixed:** 28

---

## Fixes Applied

### 1. AgentCPM Evaluation Scripts (23 files)

**Issue:** Hardcoded API key `api_key="sk-123"` in evaluation scripts.

**Files Fixed:**
- `external/agentcpm/eval/grounding_eval/code/OS-genesis/bbox2text_eval_osgenesis.py`
- `external/agentcpm/eval/grounding_eval/code/OS-genesis/fun2bbox_eval_osgenesis.py`
- `external/agentcpm/eval/grounding_eval/code/OS-genesis/text2bbox_eval_osgenesis.py`
- `external/agentcpm/eval/grounding_eval/code/Qwen2.5-VL/text2bbox_eval_qwen.py`
- `external/agentcpm/eval/grounding_eval/code/Qwen2.5-VL/bbox2text_eval_qwen.py`
- `external/agentcpm/eval/grounding_eval/code/Qwen2.5-VL/fun2bbox_eval_qwen.py`
- `external/agentcpm/eval/grounding_eval/code/UI-TARS/fun2bbox_eval_uitars.py`
- `external/agentcpm/eval/grounding_eval/code/UI-TARS/text2bbox_eval_uitars.py`
- `external/agentcpm/eval/grounding_eval/code/UI-TARS/bbox2text_eval_uitars.py`
- `external/agentcpm/eval/grounding_eval/code/minicpm/fun2bbox_eval_minicpm.py`
- `external/agentcpm/eval/grounding_eval/code/minicpm/text2bbox_eval_minicpm.py`
- `external/agentcpm/eval/grounding_eval/code/minicpm/bbox2text_eval_minicpm.py`
- `external/agentcpm/eval/grounding_eval/code/Aguvis/bbox2text_eval_aguvis.py`
- `external/agentcpm/eval/grounding_eval/code/Aguvis/fun2bbox_eval_aguvis.py`
- `external/agentcpm/eval/grounding_eval/code/Aguvis/text2bbox_eval_aguvis.py`
- `external/agentcpm/eval/grounding_eval/code/GPT-4o/text2bbox_eval_gpt-4o_with_grounding.py`
- `external/agentcpm/eval/grounding_eval/code/GPT-4o/bbox2text_eval.py`
- `external/agentcpm/eval/grounding_eval/code/GPT-4o/fun2bbox_eval_click.py`
- `external/agentcpm/eval/grounding_eval/code/GPT-4o/fun2bbox_eval_gpt-4o_with_grounding.py`
- `external/agentcpm/eval/grounding_eval/code/GPT-4o/text2bbox_eval_click.py`
- `external/agentcpm/eval/grounding_eval/code/OS-Altas/fun2bbox_eval_osatlas.py`
- `external/agentcpm/eval/grounding_eval/code/OS-Altas/text2bbox_eval_osatlas.py`
- `external/agentcpm/eval/grounding_eval/code/OS-Altas/bbox2text_eval_osatlas.py`

**Before:**
```python
client = AsyncClient(api_key="sk-123", base_url='http://localhost:8000/v1')
```

**After:**
```python
import os
client = AsyncClient(api_key=os.environ.get("EVAL_API_KEY", ""), base_url='http://localhost:8000/v1')
```

**Environment Variable:** `EVAL_API_KEY`

---

### 2. MemOS Default Configuration (2 files)

**Issue:** Placeholder API key in documentation examples.

**Files Fixed:**
- `external/memos/memos/mem_os/utils/default_config.py`
- `external/memos/src/memos/mem_os/utils/default_config.py`

**Before:**
```python
config = get_default_config(
    openai_api_key="sk-...",
    ...
)
```

**After:**
```python
import os
config = get_default_config(
    openai_api_key=os.environ.get("OPENAI_API_KEY", "your-api-key-here"),
    ...
)
```

**Environment Variable:** `OPENAI_API_KEY`

---

### 3. Pickle Secret Key (2 files)

**Issue:** Default secret key for data serialization.

**Files Fixed:**
- `external/memos/memos/memories/activation/kv.py`
- `external/memos/memos/memories/activation/vllmkv.py`

**Before:**
```python
os.environ.get('PICKLE_SECRET_KEY', 'default-secret-key').encode()
```

**After:**
```python
os.environ.get('PICKLE_SECRET_KEY', '').encode()
```

**Environment Variable:** `PICKLE_SECRET_KEY`

**Note:** This key must be set for proper security. Empty default forces users to configure it.

---

### 4. LLM Code Generator Test (1 file)

**Issue:** Hardcoded test API key.

**Files Fixed:**
- `enhancements/coding/llm_code_generator.py`

**Before:**
```python
api_key=os.getenv("OPENAI_API_KEY", "test-key"),
```

**After:**
```python
api_key=os.getenv("OPENAI_API_KEY", ""),
```

**Environment Variable:** `OPENAI_API_KEY`

---

## Required Environment Variables

Copy `.env.example` to `.env` and configure the following variables:

### Critical (Must be set)
- `EVAL_API_KEY` - For evaluation scripts
- `PICKLE_SECRET_KEY` - For secure data serialization
- `OPENAI_API_KEY` - For OpenAI API access

### Database
- `NEBULA_PASSWORD` - Nebula Graph Database password
- `POLARDB_PASSWORD` - PolarDB password
- `MYSQL_PASSWORD` - MySQL password
- `REDIS_PASSWORD` - Redis password

### External Services
- `DINGDING_APP_KEY` - DingTalk App Key
- `DINGDING_APP_SECRET` - DingTalk App Secret
- `ANTHROPIC_API_KEY` - Anthropic API Key
- `MEMOS_API_KEY` - Memos API Key

### Security
- `UFO_API_TOKEN` - UFO API authentication token
- `CUSTOM_LOGGER_TOKEN` - Custom logger token

---

## Verification

To verify all hardcoded credentials have been removed:

```bash
# Search for hardcoded API keys
grep -rn '="sk-' --include="*.py" .

# Search for test keys
grep -rn '"test-key"' --include="*.py" .

# Search for default secrets
grep -rn "default-secret-key" --include="*.py" .
```

All commands should return no results.

---

## Best Practices

1. **Never commit `.env` files** - Add `.env` to `.gitignore`
2. **Use strong, unique secrets** - Generate random strings for each environment
3. **Rotate keys regularly** - Update API keys periodically
4. **Use different keys per environment** - Development, staging, production
5. **Monitor for leaked credentials** - Use tools like GitGuardian or TruffleHog

---

## Date of Fixes

2025-01-20

## Fixed By

Security Code Fix Bot
