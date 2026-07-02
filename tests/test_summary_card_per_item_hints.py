"""tests/test_summary_card_per_item_hints.py
==============================================
回归防护:启动总结卡"降级"行不得给所有降级项塞同一句话。

现象(用户反馈):启动总结卡"降级"行原本硬编码 —— 不论哪个阶段降级,统一在
末尾拼一句"→ 装后重跑即恢复"。这句话只对 Docker 这类"装个东西重跑就好"的
场景成立;而 AI 大脑降级(模型没拉好/没配云端 Key)真正的修复方式是"去「模型」
tab 配置 API Key 或手动 ollama pull"——跟 Docker 完全不是一回事，共用会
文不对题、误导用户。

修复:core.cli_render.summary_card() 的 degraded 参数从"裸名称列表 + 末尾
一句共用提示"改为"(名称, 专属建议) 列表"，每一项各自展示自己的建议。
unified_launcher._emit() 相应新增 hint 参数，Docker/AI 大脑各自传入正确的
专属建议。
"""

from __future__ import annotations

import io
import contextlib

from core.cli_render import summary_card


def _render(degraded):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        summary_card(
            title="t",
            state_ok=1,
            state_degraded=len(degraded),
            rows=[("面板", "http://localhost:9000")],
            degraded=degraded,
        )
    return buf.getvalue()


def test_each_degraded_item_shows_its_own_hint():
    out = _render([
        ("基础设施 · Docker", "装后重跑即恢复"),
        ("AI 大脑", "请去「模型」tab 配置"),
    ])
    assert "基础设施 · Docker → 装后重跑即恢复" in out
    assert "AI 大脑 → 请去「模型」tab 配置" in out
    # 关键:Docker 的建议不能跑到 AI 大脑名下,反之亦然。
    assert "AI 大脑 → 装后重跑即恢复" not in out
    assert "基础设施 · Docker → 请去「模型」tab 配置" not in out


def test_item_without_hint_shows_bare_name_no_fabricated_advice():
    out = _render([("某降级项", None)])
    assert "某降级项" in out
    assert "→" not in out.split("降级")[1].split("\n")[0] if "降级" in out else True


def test_no_degraded_items_renders_nothing():
    out = _render([])
    assert "降级" not in out
