"""
问候技能处理函数

这是一个示例，展示如何创建技能
"""

async def execute(name: str) -> dict:
    """
    执行问候
    
    Args:
        name: 要问候的名字
    
    Returns:
        结果
    """
    return {
        "message": f"你好, {name}! 欢迎使用 Galaxy!",
        "timestamp": __import__('datetime').datetime.now().isoformat(),
    }
