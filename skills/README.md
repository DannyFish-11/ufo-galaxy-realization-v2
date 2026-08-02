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

> ⚠️ **本节原先描述的 `/api/v1/skill/*` REST 端点从未真正存在。**
> 声明它们的 `core/api_loader.py` 定义了一个模块级 `APIRouter()`，但仓库里没有
> 任何 `include_router()` 引用它 —— 路由树里根本没有这些路径，照着这里的 `curl`
> 命令敲只会得到 404。该模块已删除，本节随之更正。
>
> 技能目前通过目录约定被发现（`skills/<name>/SKILL.md`），不经 REST 加载。
> 如果后续要补 REST 面，请在 `core/routes/` 下新建路由并在 `core/api_routes.py`
> 里 `include_router()` —— 仓库有一条守卫测试
> （`tests/test_no_orphan_api_router_in_core.py`）会拦住"定义了路由却没挂载"
> 这种复发。

## 示例

查看 `skills/examples/hello_skill/` 目录中的示例技能。
