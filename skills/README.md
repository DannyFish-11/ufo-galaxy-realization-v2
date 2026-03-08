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

### 通过 API 加载

```bash
# 加载单个技能
curl -X POST http://localhost:8080/api/v1/skill/load \
  -H "Content-Type: application/json" \
  -d '{"path": "/path/to/my-skill"}'

# 加载技能包 (多个技能)
curl -X POST "http://localhost:8080/api/v1/skill/load-package?path=/path/to/skills"
```

### 列出已加载的技能

```bash
curl http://localhost:8080/api/v1/skill/list
```

### 执行技能

```bash
curl -X POST http://localhost:8080/api/v1/skill/my-skill/execute \
  -H "Content-Type: application/json" \
  -d '{"params": {"param1": "value1"}}'
```

### 卸载技能

```bash
curl -X POST http://localhost:8080/api/v1/skill/unload \
  -H "Content-Type: application/json" \
  -d '{"skill_id": "my-skill"}'
```

## 示例

查看 `skills/examples/hello_skill/` 目录中的示例技能。
