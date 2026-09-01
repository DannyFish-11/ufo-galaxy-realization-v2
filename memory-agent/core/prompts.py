"""L2 记忆抽取/整合所用的 LLM 提示词。"""

MEMORY_EXTRACTION_SYSTEM = """\
你是记忆抽取器。从给定文本中抽取值得长期记住的原子事实(用户偏好、身份信息、\
关键事件、承诺等)。输出严格的 JSON 数组,每个元素是一条自包含的中文陈述句字符串。\
没有值得记忆的内容时输出 []。不要输出 JSON 以外的任何字符。"""

MEMORY_CONSOLIDATION_SYSTEM = """\
你是记忆整合器。给定若干条语义相近的记忆,把它们合并为一条不丢失信息、无冗余的\
自包含陈述。只输出合并后的那一条陈述,不要输出其他内容。"""


def memory_block(hits) -> str:
    if not hits:
        return "(无相关记忆)"
    lines = [f"- {h.content}" for h in hits]
    return "\n".join(lines)
