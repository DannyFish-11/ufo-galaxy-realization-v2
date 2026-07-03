#!/usr/bin/env python3
"""tools/protocol/check_aip_msgtype_drift.py
==============================================
AIP v3 消息类型跨仓漂移检查器 —— 把"单一真相源"从口号变成可强制的门禁。

背景
----
三仓(v2 中枢 / ufo-galaxy-android / galaxy-wearos)的消息类型契约此前靠【手工
镜像】维护:

  - v2  `galaxy_gateway/protocol/aip_v3.py` 的 `MessageType`(Python)—— 声明的
        **单一真相源(SSOT)**,server 权威。
  - android `shared-protocol/.../MsgType.kt`(Kotlin)—— 手工对着 v2 抄。
  - wearos  `app/.../data/MsgType.kt`(Kotlin)—— 又对着 android 抄一份(冗余)。

手工镜像必然漂移。实测已发现 6 处"同概念、不同 wire 值"的真漂移
(客户端 `relay`↔v2 `relay_request`、客户端 `lock`↔v2 `coord_lock` …),
客户端发这些类型时 server 端 `MessageType("relay")` 会 ValueError / 拒绝。

本工具
------
把 v2 的 MessageType 当作唯一标准,解析各客户端 Kotlin MsgType 的 wire 值,
分四类报告,并在存在"未登记的漂移"时以非 0 退出(供 CI 当门禁):

  1. MATCHED       —— wire 值与 v2 完全一致(健康)。
  2. ALIAS_DRIFT   —— 同一概念、客户端用了和 v2 不同的 wire 值。这是真 bug:
                      客户端发出去 server 不认。列出 客户端值 → v2 应有值。
  3. V2_MISSING    —— 客户端定义了某 wire 值,v2 既无同值、也不在"客户端专有
                      扩展白名单"里 —— 要么 v2 该补、要么客户端该删。
  4. CLIENT_EXT    —— 客户端专有扩展(client→面板/client 内部,server 无需识别),
                      在白名单里,属正常。

用法
----
    python tools/protocol/check_aip_msgtype_drift.py \
        [--android <path-to-android-repo>] [--wearos <path-to-wearos-repo>]

默认按 sibling checkout(../ufo-galaxy-android、../galaxy-wearos)查找。
客户端仓不存在时对应部分跳过(不报错),便于在只有 v2 的 CI 环境里也能跑
(此时只校验 v2 SSOT 自身可解析)。
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from typing import Dict, List, Set, Tuple

# ---------------------------------------------------------------------------
# 已登记的"同概念别名"映射:客户端历史 wire 值 → v2 SSOT canonical wire 值。
# 这些是【已知需要客户端对齐到 v2】的漂移。登记在此,报告里归为 ALIAS_DRIFT,
# 修复方向明确(改客户端 Kotlin 的 wire 值,或由 v2 compat 层显式接受)。
# ---------------------------------------------------------------------------
KNOWN_ALIAS_TO_V2: Dict[str, str] = {
    "relay": "relay_request",
    "forward": "relay_forward",
    "reply": "relay_reply",
    "lock": "coord_lock",
    "unlock": "coord_unlock",
    "broadcast": "coord_broadcast",
}

# ---------------------------------------------------------------------------
# 客户端专有扩展白名单:这些 wire 值 v2 的 MessageType 里【有意】没有,因为它们
# 是客户端本地事件(client→面板 / client 内部 UI),server 不需要识别。属正常,
# 不算漂移。新增客户端专有类型时在此登记,让检查器不误报。
# ---------------------------------------------------------------------------
CLIENT_ONLY_EXTENSIONS: Set[str] = {
    "auth",            # 客户端→网关鉴权握手(v2 走 AuthMessage,不经 MessageType)
    "voice_query",     # WearOS/手机语音输入(client 侧)
    "phase_report",    # 客户端三态相位上报(client→面板)
    "event",           # 客户端通用 UI 事件
    "liquid_event",    # 灵动岛/液态玻璃动效事件(client 内部)
    "decision_request",  # HITL 人类决策请求(wearos 本地渲染用)
}


def parse_v2_messagetype(aip_v3_path: str) -> Set[str]:
    """从 galaxy_gateway/protocol/aip_v3.py 抽 class MessageType 的全部 wire 值。"""
    with open(aip_v3_path, encoding="utf-8") as f:
        src = f.read()
    m = re.search(r"class\s+MessageType\s*\([^)]*\)\s*:(.*?)(?:\nclass\s|\Z)", src, re.DOTALL)
    if not m:
        raise SystemExit(f"ERROR: 在 {aip_v3_path} 里找不到 class MessageType")
    body = m.group(1)
    return set(re.findall(r'^\s+[A-Z_0-9]+\s*=\s*"([a-z_0-9]+)"', body, re.MULTILINE))


def parse_kotlin_msgtype(kt_path: str) -> Set[str]:
    """从 Kotlin `enum class MsgType(val value: String)` 抽 NAME("wire") 的 wire 值。"""
    with open(kt_path, encoding="utf-8") as f:
        src = f.read()
    return set(re.findall(r'^\s+[A-Z_0-9]+\("([a-z_0-9]+)"\)', src, re.MULTILINE))


def classify(client_values: Set[str], v2_values: Set[str]) -> Dict[str, List]:
    """把客户端 wire 值按对 v2 SSOT 的关系分四类。

    别名判定【先于】v2 成员判定:这些短别名现在已作为【入向兼容别名】登记进
    v2 的 MessageType(server 认得、不再 UNKNOWN_MESSAGE_TYPE),所以它们既在
    v2_values 里、又在 KNOWN_ALIAS_TO_V2 里。我们要的是把它们持续显示为
    "已接受但非 canonical"(accepted_alias),提示客户端后续可迁移到长名,
    而不是被 matched 吞掉看不见。只有既非 canonical、又非已登记别名、又不在
    客户端专有白名单里的 wire 值,才是真正会被 server 拒的 unknown(strict 失败)。
    """
    matched: List[str] = []
    accepted_alias: List[Tuple[str, str]] = []
    unknown: List[str] = []
    client_ext: List[str] = []
    for wire in sorted(client_values):
        if wire in KNOWN_ALIAS_TO_V2:
            accepted_alias.append((wire, KNOWN_ALIAS_TO_V2[wire]))
        elif wire in v2_values:
            matched.append(wire)
        elif wire in CLIENT_ONLY_EXTENSIONS:
            client_ext.append(wire)
        else:
            unknown.append(wire)
    return {
        "matched": matched,
        "accepted_alias": accepted_alias,
        "unknown": unknown,
        "client_ext": client_ext,
    }


def _first_existing(*paths: str) -> str:
    for p in paths:
        if p and os.path.isfile(p):
            return p
    return ""


def main() -> int:
    here = os.path.dirname(os.path.abspath(__file__))
    v2_root = os.path.dirname(os.path.dirname(here))
    siblings = os.path.dirname(v2_root)

    ap = argparse.ArgumentParser()
    ap.add_argument("--android", default=os.path.join(siblings, "ufo-galaxy-android"))
    ap.add_argument("--wearos", default=os.path.join(siblings, "galaxy-wearos"))
    ap.add_argument("--strict", action="store_true",
                    help="存在 server 会拒的 UNKNOWN wire 值时以非 0 退出(CI 门禁用)")
    args = ap.parse_args()

    v2_aip = os.path.join(v2_root, "galaxy_gateway", "protocol", "aip_v3.py")
    v2_values = parse_v2_messagetype(v2_aip)
    print(f"v2 SSOT (aip_v3.py MessageType): {len(v2_values)} 个 wire 值\n")

    clients = {
        "android": _first_existing(
            os.path.join(args.android, "shared-protocol", "src", "main", "java",
                         "com", "ufo", "galaxy", "shared", "protocol", "MsgType.kt"),
        ),
        "wearos": _first_existing(
            os.path.join(args.wearos, "app", "src", "main", "java",
                         "com", "galaxy", "wear", "data", "MsgType.kt"),
        ),
    }

    any_unknown = False
    for name, path in clients.items():
        if not path:
            print(f"[{name}] 未找到 MsgType.kt(仓库未 checkout),跳过。")
            continue
        vals = parse_kotlin_msgtype(path)
        r = classify(vals, v2_values)
        print(f"── [{name}] {path}")
        print(f"   共 {len(vals)} 个 wire 值 | canonical 一致 {len(r['matched'])} | "
              f"已接受兼容别名 {len(r['accepted_alias'])} | 客户端专有扩展 {len(r['client_ext'])} | "
              f"未知(server 会拒){len(r['unknown'])}")
        if r["accepted_alias"]:
            print("   · ACCEPTED_ALIAS(v2 已登记为入向兼容别名,server 认得;建议客户端后续迁到 canonical 长名):")
            for c, v in r["accepted_alias"]:
                print(f"       {c!r}  ≈  canonical {v!r}")
        if r["unknown"]:
            any_unknown = True
            print("   ⚠ UNKNOWN(v2 既无此值、也非已登记别名/扩展 —— server 端会 UNKNOWN_MESSAGE_TYPE 拒收):")
            for w in r["unknown"]:
                print(f"       {w!r}  —— 需在 v2 MessageType 补登(canonical 或兼容别名),或客户端删除")
        if r["client_ext"]:
            print(f"   · CLIENT_EXT(客户端专有扩展,正常): {', '.join(repr(w) for w in r['client_ext'])}")
        print()

    if any_unknown:
        print("结论:存在 server 会拒收的未登记 wire 值(见上 ⚠)。修复:在 v2 MessageType "
              "补登为 canonical 或入向兼容别名,或从客户端移除。")
        if args.strict:
            return 1
    else:
        print("结论:所有客户端 wire 值均被 v2 SSOT 接受(canonical 一致 / 已登记兼容别名 / 白名单扩展);"
              "无 server 会拒的未知类型。✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
