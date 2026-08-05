# DeepSeek API 配置 (Node 50)
# 密钥通过环境变量 DEEPSEEK_API_KEY 提供

import os

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
# 使用支持多模态的 DeepSeek-Vision 模型进行桌面理解
DEEPSEEK_MODEL_VISION = "deepseek-vl-v1.5"
# 使用 DeepSeek-Coder 或 DeepSeek-Chat 进行逻辑推理
DEEPSEEK_MODEL_LOGIC = "deepseek-chat"
