# Galaxy 技能系统

## 概述

Galaxy 支持动态加载技能。用户可以自己创建技能，然后通过 API 加载到系统中。

## 创建技能

### 1. 创建技能目录

```
my-skill/
├── skill.json      # 技能定义 (必需)
└── handler.py      # 处理函数 (必需)
```

### 2. 编写 skill.json

```json
{
    "id": "my-skill",
    "name": "我的技能",
    "description": "技能描述",
    "version": "1.0.0",
    "author": "作者",
    "tags": ["tag1", "tag2"],
    "parameters": [
        {
            "name": "param1",
            "type": "string",
            "description": "参数描述",
            "required": true
        }
    ],
    "handler_file": "handler.py",
    "handler_function": "execute"
}
```

### 3. 编写 handler.py

```python
async def execute(param1: str) -> dict:
    """
    技能处理函数
    
    Args:
        param1: 参数
    
    Returns:
        结果
    """
    return {
        "result": f"处理完成: {param1}"
    }
```

## 加载技能

> ⚠️ **端点前缀是 `/api/v1/protocols/`，不是 `/api/v1/skill/`。**
> 本节原先写的 `/api/v1/skill/*` 从未存在过 —— 声明它们的 `core/api_loader.py`
> 是一份未挂载的重复实现（定义了 `APIRouter()`，但全仓没有任何 `include_router()`
> 引用它），照着敲只会 404。该模块已删除；真正提供这些端点的是
> `core/routes/protocols.py`（由 `core/api_routes.py` 挂载），两者底层调用的都是
> 同一个 `core.skill_loader`。

### 通过 API 加载

```bash
# 加载技能
curl -X POST http://localhost:8080/api/v1/protocols/skills/load \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/my-skill"}'
```

### 列出已加载的技能

```bash
curl http://localhost:8080/api/v1/protocols/skills

# 只读概览（含统计）
curl http://localhost:8080/api/v1/system/skills
```

### 执行技能

```bash
curl -X POST http://localhost:8080/api/v1/protocols/skills/my-skill/execute \
  -H "Content-Type: application/json" \
  -d '{"params": {"param1": "value1"}}'
```

### 重载 / 卸载技能

```bash
curl -X POST   http://localhost:8080/api/v1/protocols/skills/my-skill/reload
curl -X DELETE http://localhost:8080/api/v1/protocols/skills/my-skill
```

> 以上路径与参数请以 `core/routes/protocols.py` 为准 —— 仓库有一条守卫测试
> （`tests/test_no_orphan_api_router_in_core.py`）保证 `core/` 下不再出现
> "定义了路由却没挂载"的第二份实现。

## 示例

查看 `skills/examples/hello_skill/` 目录中的示例技能。
