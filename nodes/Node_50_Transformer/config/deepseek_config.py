# DeepSeek API 配置 (Node 50)
# 密钥由用户提供：sk-f5c7177f35ee6cceab5d97d6ffae26d0

DEEPSEEK_API_KEY = "sk-f5c7177f35ee6cceab5d97d6ffae26d0" # PixVerse/DeepSeek Key
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
# 使用支持多模态的 DeepSeek-Vision 模型进行桌面理解
DEEPSEEK_MODEL_VISION = "deepseek-vl-v1.5"
# 使用 DeepSeek-Coder 或 DeepSeek-Chat 进行逻辑推理
DEEPSEEK_MODEL_LOGIC = "deepseek-chat"

# 这是一个示例函数，演示如何使用 DeepSeek API
def analyze_desktop_image(image_path: str, prompt: str) -> str:
    """
    模拟调用 DeepSeek-Vision 分析桌面截图。
    在实际 Node 50 代码中，需要使用 requests 或 openai 库进行 API 调用。
    """
    print(f"[Node 50/DeepSeek] Analyzing image: {image_path} with prompt: '{prompt}'")
    
    # 模拟 API 调用和返回结果
    if "浏览器" in prompt:
        return json.dumps({
            "action": "click",
            "target": "browser_icon",
            "coordinates": [100, 500] # 模拟返回的坐标
        })
    elif "极客松" in prompt:
        return json.dumps({
            "action": "type",
            "target": "search_bar",
            "text": "极客松 UFO³ Galaxy"
        })
    
    return json.dumps({"action": "none", "reason": "Could not identify target."})

import json
