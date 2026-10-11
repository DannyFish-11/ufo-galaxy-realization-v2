"""面板版式的几处具体毛病，钉住不再回来（都是所有者对着真界面指出来的）。

* 对话：人说的是一块白底，**模型说的也是一块底（紫）**，左右对称 —— 此前模型的话是光秃秃的字。
  新来的一句才播进场（整组重绘时旧的不能重放，否则每来一个字全屏闪一次）。
* 左栏卡片：没抽出来时，卡片下半截本来就被盖住、被框沿切掉，露出来的只是半根孤零零的紫柱 —— 平时不画，
  抽出那张时才画，而且每一天都有一截底，依次长出来。
* 右下档位牌：「装不下」不再用黄色（整面只有一支色相，黄色的 B 是唯一跳出来的东西），改成沉下去的深度。
* 左下「接上了什么」与底下那根线：与上面卡片同一条左右边。
* 设置页：档位多的行（本地主脑模型有 7 个型号）一行放不下，名字曾被挤成竖着的窄条 —— 改成叠放。

这些都是 CSS / DOM 形状，没有办法用后端测试看出来；这里钉的是**源码里这几处的形状**，真正的像素在
PR 里用真浏览器截图对过。
"""

from __future__ import annotations

import re
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "electron/renderer/panel/src"
_CSS = _SRC / "styles/hud.css"


def _code(path: Path) -> str:
    """去掉注释再看（散文不是代码 —— 这仓库已经被它绊倒过三次）。"""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".css":
        return re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", text)


def _rule(css: str, selector: str) -> str:
    """这个选择器的全部声明（它可能出现在几条规则里，也可能在逗号分隔的一组里），拼成一段；找不到就是空串。"""
    bodies = [
        body
        for sel_list, body in re.findall(r"([^{}]+)\{([^}]*)\}", css)
        if selector in [x.strip() for x in sel_list.split(",")]
    ]
    return " ".join(bodies)


# ── 对话：人是白块，模型是紫块 ───────────────────────────────────────────────


def test_the_purple_block_is_see_through_and_shaped_like_the_white_one():
    """所有者:紫的字块要更透、形状优化。紫只兑进透明里(不兑进白里),两边同一个圆角与尾巴。"""
    css = _code(_CSS)
    agent = _rule(css, ".turn[data-role='agent']")
    assert "transparent" in agent and "var(--veil" not in agent, "紫底又兑进白里了 —— 那是一块板,不是一层纱"
    assert "18px 18px 18px 6px" in agent
    assert "18px 18px 6px 18px" in _rule(css, ".turn[data-role='user']")
    assert "margin-top" in _rule(css, ".turn[data-role='agent'] + .turn[data-role='agent']"), "连着的几句合成一组"


def test_the_models_words_sit_on_a_purple_block_that_mirrors_the_persons_white_one():
    css = _code(_CSS)
    user = _rule(css, ".turn[data-role='user']")
    agent = _rule(css, ".turn[data-role='agent']")
    assert "align-self: flex-end" in user, "人说的在右"
    assert agent, "模型说的话没有自己的底了"
    assert "align-self: flex-start" in agent, "模型说的在左，与人说的左右对称"
    assert "var(--a-mid)" in agent and "background" in agent, "底是从面板那一支紫（--a-mid）调出来的"
    assert "border-radius" in agent and "padding" in agent


def test_only_a_newly_added_turn_plays_its_entrance():
    ts = _code(_SRC / "ui/thread.ts")
    # 整组重绘：旧的也重放就会每来一个字全屏闪一次 —— 只给比上次多出来的打标记
    assert "dataset['new']" in ts and "i >= drawn" in ts
    assert "let drawn = -1" in ts, "第一次（载入历史）不是「新来的」，不播"
    css = _code(_CSS)
    assert "animation: turn-in" in _rule(css, ".turn[data-new='true']")


def test_the_glow_while_the_model_is_still_talking_uses_the_shared_pulse_period():
    """周期必须是 tokens.css 里登记过、躲开 0.17–0.25 Hz 的那一条（--c-pulse），不自己再写一个秒数。"""
    css = _code(_CSS)
    rule = _rule(css, ".turn[data-role='agent'][data-streaming='true']")
    assert "var(--c-pulse)" in rule, rule
    assert not re.search(r"animation:[^;]*\d+(\.\d+)?s\b", rule), "不要写死秒数"
    ts = _code(_SRC / "ui/thread.ts")
    assert "dataset['streaming']" in ts


# ── 左栏卡片：没抽出来时不画那根孤零零的柱 ────────────────────────────────────


def test_the_activity_bars_are_only_drawn_when_the_card_is_pulled_out_and_every_day_has_a_stub():
    css = _code(_CSS)
    assert "visibility: hidden" in _rule(css, ".card:not([data-drawn='true']) .card-plot")
    assert "min-height" in _rule(css, ".card-plot i"), "没聊的那几天也留一小截底，整排才读得成一张图"
    assert "bar-rise" in _rule(css, ".card[data-drawn='true'] .card-plot i")
    deck = _code(_SRC / "ui/deck.ts")
    assert "setProperty('--i'" in deck, "依次长出来要靠每根柱子的序号"


# ── 档位牌：不用黄色 ─────────────────────────────────────────────────────────


def test_every_tier_chip_looks_the_same_whether_or_not_it_fits():
    """所有者两次指出 B 与其它档不一致(先是黄字黄圈,后来是沉下去)—— 档位牌一律同一个样子。"""
    css = _code(_CSS)
    assert "data-fit" not in css, "档位牌又按装不装得下画成不一样的了"
    assert "var(--a-mid)" in _rule(css, ".tier-stages .stage[data-picked='true']")


def test_the_note_says_so_when_the_current_tier_does_not_fit_since_colour_no_longer_does():
    dock = _code(_SRC / "ui/dock.ts")
    assert "这台机器装不下" in dock and "没评估过" in dock


# ── 左栏：与卡片同一条左右边 ─────────────────────────────────────────────────


def _px(decl: str, prop: str) -> int:
    m = re.search(prop + r":\s*\d+(?:px)?\s+(\d+)px", decl)
    assert m, (prop, decl)
    return int(m.group(1))


def test_the_status_list_and_the_line_under_it_share_the_edges_of_the_card_above():
    css = _code(_CSS)
    frame_pad = _px(_rule(css, ".frame"), "padding")  # 「10px 6px」→ 左右 6
    assert _px(_rule(css, ".wired"), "padding") == frame_pad, "「接上了什么」要与卡片同一条左右边"
    assert _px(_rule(css, ".line-zone"), "padding") == frame_pad, "底下那根线也是"
    assert "padding-left" not in _rule(css, ".wired-head"), "标题再缩 2px 就比点和卡片都靠左"
    assert "padding: 3px 0" in _rule(css, ".wired-row"), "每行左右不再各缩 2px，点才落在卡片左缘上"


def test_the_last_dot_in_the_status_list_looks_like_its_neighbours():
    css = _code(_CSS)
    body = _rule(css, ".wired-row[data-state='unknown'] .wired-dot")
    assert body and body == _rule(css, ".wired-row[data-state='off'] .wired-dot"), "最后那颗又和相邻的点不一样了"
    m = re.search(r"background:\s*rgba\(255, 255, 255, ([\d.]+)\)", body)
    assert m and float(m.group(1)) >= 0.35, "暗点要看得见 —— 0.18 的白在浅底上一列里像缺了三颗"


def test_the_status_list_uses_the_short_names_and_says_none_when_nothing_is_connected():
    """所有者:后端改成「本体」;第 2–4 行改成模型 / 服务 / 设备;容器运行时改成「容器」;
    设备只写实时的台数;本体没连上时六行全部写「无」。"""
    ts = _code(_SRC / "ui/wired.ts")
    assert "const NAMES = ['本体', '模型', '服务', '设备', '感知', '容器'] as const" in ts
    for old in ("'后端'", "'本机模型'", "'模型服务'", "'其他设备'", "'容器运行时'"):
        assert f"name: {old}" not in ts, f"{old} 这个旧名字又回来了"
    block = ts[ts.index("if (!input.connected)") :]
    block = block[: block.index("return rows;")]
    assert "for (const name of NAMES)" in block and "detail: '无'" in block, "没连上时六行要全部写「无」"
    assert "detail: `${online + 1} 台`" in ts, "设备那一行只写实时的台数(这台电脑也算一台)"


# ── 设置页：档位多的行叠放 ───────────────────────────────────────────────────


def test_a_row_with_many_choices_stacks_instead_of_squeezing_its_name_into_a_sliver():
    css = _code(_CSS)
    assert "grid-template-columns: minmax(0, 1fr)" in _rule(css, ".sf-row[data-stack='true']")
    assert "flex-wrap: wrap" in _rule(css, ".sf-stages"), "档位自己换行"
    ts = _code(_SRC / "ui/settings.ts")
    assert "dataset['stack']" in ts and "children.length > 4" in ts
