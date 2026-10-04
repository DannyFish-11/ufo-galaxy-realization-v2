#!/usr/bin/env python3
"""由 ``core/routes/panel_switch_policy.py`` 生成 ``docs/PANEL_SWITCHES.md``。

    python scripts/gen_panel_switches_doc.py --write   # 重新生成
    python scripts/gen_panel_switches_doc.py --check   # 与现有文件对账（测试用）

清单是数据，文档是它的投影 —— 手写的开关清单一定会过期。叙述性的部分（面板上的控制点、还可以再合并的建议）
放在本脚本里，和数据一起被 ``--check`` 盯着。
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import OrderedDict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

DOC = REPO / "docs" / "PANEL_SWITCHES.md"

_GROUP_ORDER = (
    "声音",
    "感知与在场",
    "记忆与隐私",
    "桌面操作与自治",
    "模型与花费",
    "多设备与网络",
    "安全姿态",
    "启动与诊断",
)

_MERGE_SUGGESTIONS = """\
**合并的判据只有一条：（主键关、这个键开）这个组合有没有意义。** 没有意义的才并进按钮（见「并进整档按钮的」一节）。
下面这些**看着像、没有并** —— 并了会替用户悄悄改一个有隐私、花费或对外暴露含义的选择，需要你定：

| 看着像一个的 | 没并的原因 |
|---|---|
| 「全模态」与「系统声送进模型」`GALAXY_SYSTEM_AUDIO_TO_PERCEPTION` | 「只要回声消除、不想让模型听见自己在放什么」是 `system_audio_capture_service.feed_perception_enabled` 的文档里特意拆开的隐私选择 |
| 「听」`GALAXY_VOICE`、「朗读」`GALAXY_SPEAK`、「本机外放」`GALAXY_LOCAL_AUDIO` | 三个方向：只要听写不要朗读、朗读给别的设备而电脑不外放，都是有意义的组合 |
| 「原生听」`GALAXY_NATIVE_AUDIO_CHAT` 并进本机模型档位 | 那是「每轮都把录音原样发给模型」的花费决定（音频 token 贵），不是「模型会不会听」；会不会听由档位说了算 |
| 「跨设备」并进主脑 / 联邦 / WebRTC 数据通道 / Funnel / 远程桌面 | 它们是默认关的 opt-in，有花费或对外暴露面；按钮「开」不能替用户打开 |
| 「全模态」并进主动感知 `GALAXY_ACTIVE_PERCEPTION` / 屏幕触发 `GALAXY_PROACTIVE_SCREEN` | 同上，默认关、开了会多花算力；它们更像「自主」档（safe / guided / autonomous）的内容，要不要把 autonomous 定义成「主动感知也开」是产品决定 |
| 安全姿态做成一个「宽松 / 默认 / 严格」档位 | 现在有 11 个互相独立的开关，其中 6 个是「开了更严」的选项；每个开关的「严」到底牵动什么要逐个确认 |
| `GALAXY_EXPERIENCE_STRATEGY` 并进 `GALAXY_EXPERIENCE_GUIDANCE` | 后者是 off / shadow / on 三档，前者是它的历史总闸；面板上只登记了前者，要先把三档登记进面板 |
"""


def _on_off(value: object) -> str:
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return "开"
    if text in ("0", "false", "no", "off", ""):
        return "关"
    return text


def _cell(text: str) -> str:
    return str(text).replace("|", "\\|").replace("\n", " ")


def build() -> str:
    logging.disable(logging.CRITICAL)
    from core.routes.config_bundles import CONFIG_BUNDLES
    from core.routes.config_schema_registry import CONFIG_SCHEMA
    from core.routes.config_bundles import member_keys
    from core.routes.panel_switch_policy import BUILTIN, MEMBER, OPS, PANEL, SWITCH_POLICY

    by_disp = {d: [k for k, p in SWITCH_POLICY.items() if p.disposition == d] for d in (PANEL, BUILTIN, OPS, MEMBER)}
    total_keys = len(CONFIG_SCHEMA)
    total_switches = len(SWITCH_POLICY)

    out = []
    w = out.append
    w("# 面板开关清单")
    w("")
    w(
        "> 本文件由 `python scripts/gen_panel_switches_doc.py --write` 从 `core/routes/panel_switch_policy.py` 生成，**不要手改**；"
    )
    w("> `tests/test_every_switch_has_a_disposition.py` 会核对它与清单一致。")
    w("")
    w("## 结论")
    w("")
    w(
        f"设置页「全部设置」共登记 {total_keys} 个键，其中布尔开关 **{total_switches}** 个。逐个对着生产代码核过之后，它们分成四种去处："
    )
    w("")
    w("| 去处 | 个数 | 含义 |")
    w("|---|---|---|")
    w(
        f"| **留在面板** | {len(by_disp[PANEL])} | 用户真有取舍：隐私（录音存不存）、花费（多模型协作）、硬件与网络（下不下 310MB 模型）、安全姿态（要不要强制令牌） |"
    )
    w(
        f"| **内置**（面板不列） | {len(by_disp[BUILTIN])} | 不该有人去关的内部机制：熔断器、派发幂等、回声消除的子参数、自回声闸门……默认开，关掉只会变差或出事 |"
    )
    w(
        f"| **开发 / 运维**（面板不列） | {len(by_disp[OPS])} | 开发、运维、打包、测试用的逃生口。其中「本机回环也封禁」打开后，桌面会把自己锁在自己的后端门外 |"
    )
    w(
        f"| **并进整档按钮**（面板不列） | {len(by_disp[MEMBER])} | 和某个整档按钮同一件事的另一面：翻按钮时一起写，不再各占一行（见下面「并进整档按钮的」） |"
    )
    w("")
    w(
        "面板不列 ≠ 没接上：这些键仍在 `CONFIG_SCHEMA` 里，`POST /api/config` 照收、`.env` 照写、环境变量照读，只是 `GET /api/config/all` 不列。"
    )
    w("")
    w("## 面板上的控制点")
    w("")
    w("设置浮层里有三类控件，不止「全部设置」：")
    w("")
    w("| 控件 | 在哪 | 管什么 |")
    w("|---|---|---|")
    for b in CONFIG_BUNDLES:
        kind = "三档牌" if b["key"] == "autonomy" else "推拉开关（一个开关管一整片）"
        extra = f"，连带 {len(member_keys(b))} 个子开关" if member_keys(b) else ""
        w(f"| 整档「{b['name']}」 | 浮层 | {kind}，主键 `{b['primary']}`{extra} |")
    w("| 本机模型档位 A / B / C / D | 浮层 | 四选一，写 `GALAXY_MODEL_TIER` |")
    w("| 感知隐私暂停 | 浮层 | `POST /api/perception/desktop/privacy/pause` 与 `…/resume`，不是配置键 |")
    w(f"| 全部设置 | 浮层「全部设置」按钮 | 下面按分组列出的 {len(by_disp[PANEL])} 个开关 + 其余数值/文本/选择项 |")
    w("")

    def _section(title: str, disp: str, with_default: bool = True) -> None:
        w(f"## {title}")
        w("")
        groups: "OrderedDict[str, list]" = OrderedDict((g, []) for g in _GROUP_ORDER)
        for key, pol in SWITCH_POLICY.items():
            if pol.disposition == disp:
                groups.setdefault(pol.group, []).append(key)
        for group, keys in groups.items():
            if not keys:
                continue
            w(f"### {group}（{len(keys)}）")
            w("")
            w("| 键 | 默认 | 为什么 |")
            w("|---|---|---|")
            for key in sorted(keys):
                pol = SWITCH_POLICY[key]
                w(f"| `{key}` | {_on_off(CONFIG_SCHEMA[key]['default'])} | {_cell(pol.reason)} |")
            w("")

    _section("留在面板上的开关", PANEL)
    _section("内置：不再列在面板上，默认开", BUILTIN)
    _section("开发 / 运维：不再列在面板上", OPS)

    w("## 并进整档按钮的")
    w("")
    w(
        "翻按钮时，主键和下面这些子开关**一次写完**（同一次落盘）：主键写 `false` → 子开关全写 `false`；"
        "主键写 `true` → 子开关回到登记表默认值（默认关的 opt-in 不会被按钮替人打开）。"
        "判据与「没并」的反例见 `core/routes/config_bundles.py` 模块说明。"
    )
    w("")
    w("| 按钮 | 主键 | 并进来的子开关 | 为什么 |")
    w("|---|---|---|---|")
    for b in CONFIG_BUNDLES:
        for key in member_keys(b):
            w(
                f"| 「{b['name']}」 | `{b['primary']}` | `{key}`（默认{_on_off(CONFIG_SCHEMA[key]['default'])}） | {_cell(SWITCH_POLICY[key].reason)} |"
            )
    w("")

    w("## 还可以再合并的（需要你定）")
    w("")
    w(_MERGE_SUGGESTIONS)
    w("## 清点时顺带查出的真问题")
    w("")
    w("""\
1. **「保存设置」会把登记表里每个键的默认值整体写进 `.env`**（`core/routes/config.py::_write_env_file_with`）。所以登记表的默认值写错，保存一次就会悄悄改变行为。
   `GALAXY_MEMORY_MEDIA` 登记成「默认开」，而代码里三处读取的默认都是关 —— 保存一次设置，截图和录音就在没人点过的情况下开始落盘。已改成默认关；
   `GALAXY_ENTRYMODE_USE_READINESS`（登记开、代码关）与 `GALAXY_PREFLIGHT_FAIL_FAST`（登记关、代码开，且只影响预检命令行）同样对齐到代码。
2. **设置页只认字面量 `"true"` 为开**：`.env` 里手写的 `=1` / `=on`、或登记表里写成 `1` 的默认值（`GALAXY_CONSENSUS_ROUND`），代码都认作开，面板却显示成关，点一下还会把它「关」成 `false`。  # noqa: E501
   现在 `GET /api/config/all` 把布尔值统一规整成 `true` / `false`，登记表里的默认值也都写成字面量。
3. `GALAXY_COMPUTER_USE_NATIVE_TOOL` 的类型登记成 `bool`（不是 `boolean`），设置页会把它画成一个文本框；已归一。
4. **`GALAXY_CROSS_DEVICE_ENABLED` 登记成「默认开」，而代码与 `.env.example` 都是关（出厂只用本机、opt-in）。** 同样走「保存设置整体写进 `.env`」
   这条路：保存一次，跨设备编排就在没人点过的情况下开了。已改成默认关。
5. `GALAXY_NATIVE_AUDIO` 以前列在面板上，但它是「服务现实」门控：切到 B 档时 `core/native_modal.py` 自动打开、离开时自动关掉。
   面板上的开关会被档位切换悄悄覆盖，是同一个事实两处各存一份；用户的取舍是选哪一档，已改为运维项。
""")
    return "\n".join(out).rstrip("\n") + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write", action="store_true")
    g.add_argument("--check", action="store_true")
    args = ap.parse_args()
    text = build()
    if args.write:
        DOC.write_text(text, encoding="utf-8")
        print(f"wrote {DOC}")
        return 0
    current = DOC.read_text(encoding="utf-8") if DOC.exists() else ""
    if current != text:
        print("docs/PANEL_SWITCHES.md 与 core/routes/panel_switch_policy.py 对不上 —— 重跑 --write", file=sys.stderr)
        return 1
    print("docs/PANEL_SWITCHES.md 与清单一致")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
