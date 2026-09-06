"""settings_inventory.ts 的文档不许再说「设置面还没建」。

## 修的是什么

`electron/renderer/panel/src/settings_inventory.ts` 的顶部文档块曾经写着:

    ## 但是要说清楚:**现在没有任何界面在渲染这份清单**
    新面板的设置浮层只有四个整档开关;那个「全部设置」按钮**还没有接任何东西**。
    这 303 个键当前在界面上一个都调不了。

写下这段话的时候是对的。设置面建成之后(`ui/settings.ts` + `dock.ts` 的按钮 +
`main.ts` 拉 `/api/config/all`),没人回来改这段话,于是它变成了假的 ——
而且是**理直气壮**的假:它不报错、不失败、看起来还很负责任。

本仓最常被咬的那个毛病是「看起来接上了,其实没有」。这一条是它的镜像:
**其实接上了,文档说没接**。后果一样坏 —— 读到的人要么以为面板没做完,要么
真的再去建第二个设置面,于是「一个键属于哪一类」这件事有了两处权威。

## 这道门盯的是什么

只要**还有界面在 import 这份清单**,清单的文档里就不许再出现「还没有界面」
这一类说法。两边同时成立才算过期,所以这门不会在设置面真的被拆掉时误报 ——
那时候没有 import,老话反而又成真了。
"""

import re
from pathlib import Path

import pytest

_PANEL_SRC = Path(__file__).resolve().parents[1] / "electron/renderer/panel/src"
_INVENTORY = _PANEL_SRC / "settings_inventory.ts"

# 「这份清单没有界面在用」这类说法的原话与近义写法。
_STALE_CLAIMS = (
    "没有任何界面在渲染",
    "还没有接任何东西",
    "一个都调不了",
    "还没有界面",
    "那个还没建的设置面",
)


def _asserted_text(doc: str) -> str:
    """去掉「」里的引用,只留下这份文档**自己主张**的话。

    这一步不是可有可无的:改对之后的文档要交代「此前这里写的是什么」,那句交代
    必然逐字带上旧说法。按原文扫会把引用当成主张,于是文档越是老实记录自己错过,
    越是过不了这道门 —— 人被逼着删掉那段记录,信息就这么没了。

    本会话已经被同一个形状咬过一次:api-surface 扫描器读的是文件原文,把注释里
    提到的端点当成真的端点。那次的结论是**修扫描器,不是改措辞**,这里照办。

    只剥 「」。这是本仓里稳定表示「这是引用」的那对括号。有人硬要把真主张塞进
    「」里绕过去当然做得到 —— 但这道门防的是话放久了变馊,不是防人存心骗它。
    """
    return re.sub(r"「[^」]*」", "", doc)


def _importers() -> list[Path]:
    """哪些面板源码真的从这份清单里取东西。"""
    found = []
    for path in _PANEL_SRC.rglob("*.ts"):
        if path == _INVENTORY:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*import\s.*from\s+['\"][^'\"]*settings_inventory['\"]", text, re.M):
            found.append(path)
    return found


def test_the_inventory_is_actually_imported_by_some_ui() -> None:
    """先确认前提:确实有界面在用它。前提垮了,下面那条断言就该换个说法。"""
    importers = _importers()
    assert importers, (
        "没有任何 .ts 从 settings_inventory 里 import —— 那么设置面可能真的被拆了。"
        "这时候要改的不是这道门,是回去看那 335 个键现在还能不能配。"
    )


def test_the_doc_does_not_claim_the_settings_page_is_unbuilt() -> None:
    """有人在用它,文档就不许说「还没建」。"""
    if not _importers():
        pytest.skip("没有界面 import 它,老话反而成真了 —— 见上一条")

    doc = _asserted_text(_INVENTORY.read_text(encoding="utf-8"))
    offenders = [claim for claim in _STALE_CLAIMS if claim in doc]
    assert not offenders, (
        f"settings_inventory.ts 的文档里还留着这些已经不成立的说法:{offenders}。"
        f"实际上 {[p.name for p in _importers()]} 正在 import 它,"
        "「全部设置」那一页每一个键都能改。把话改对,别把界面拆掉来迁就文档。"
    )


def test_the_whole_chain_from_button_to_backend_is_present() -> None:
    """文档说「按钮 → 设置面 → /api/config/all」这条链在,那就逐段验一下它真在。

    只验存在,不验行为 —— 行为归 tests/test_panel_surfaces_are_really_wired.py。
    这里要挡的是「文档描述了一条链,链其实断了」。
    """
    dock = (_PANEL_SRC / "ui/dock.ts").read_text(encoding="utf-8")
    settings = (_PANEL_SRC / "ui/settings.ts").read_text(encoding="utf-8")
    main = (_PANEL_SRC / "main.ts").read_text(encoding="utf-8")

    assert "全部设置" in dock, "dock.ts 里没有「全部设置」这个入口了"
    assert (
        "CATEGORIES" in settings and "KEY_ORDER_HINT" in settings
    ), "ui/settings.ts 不再从清单里取分类与顺序 —— 那这份清单就没人在用了"
    assert "fetchAllConfig" in main, "main.ts 不再拉 /api/config/all —— 设置面就没有料可渲染"


def test_the_counts_the_doc_states_are_the_counts_the_file_has() -> None:
    """文档里写的两个数目必须是这个文件自己数得出来的。

    数字比散文更容易烂:改清单的人加了一个键,不会想到回去改开头那句「303 个」。
    这两个数都能从同一个文件里数出来,所以让它自己对账,不留给人记。

    后端那个「335 个键」不在这里对账 —— 它随功能增减,文档里也已经写明是快照;
    真正管它的是 tests/test_config_schema_ui_parity.py。
    """
    src = _INVENTORY.read_text(encoding="utf-8")

    hint_block = re.search(r"KEY_ORDER_HINT[^=]*=\s*\{(.*?)\n\};", src, re.S)
    assert hint_block, "找不到 KEY_ORDER_HINT 的字面量 —— 结构变了,这道门要跟着改"
    hint_keys = set(re.findall(r"'([A-Z0-9_]+)'", hint_block.group(1)))

    prov_block = re.search(r"PROVIDER_KEYS[^=]*=\s*\[(.*?)\];", src, re.S)
    assert prov_block, "找不到 PROVIDER_KEYS 的字面量 —— 结构变了,这道门要跟着改"
    prov_keys = set(re.findall(r"'([A-Z0-9_]+)'", prov_block.group(1)))

    assert (
        f"({len(hint_keys)} 个键,9 类)" in src
    ), f"KEY_ORDER_HINT 现在有 {len(hint_keys)} 个键,文档开头写的不是这个数。"
    assert (
        f"`PROVIDER_KEYS` 是 {len(prov_keys)} 个" in src
    ), f"PROVIDER_KEYS 现在有 {len(prov_keys)} 个,文档开头写的不是这个数。"
