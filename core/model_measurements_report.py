"""core/model_measurements_report.py — 这台机器上，各个型号到底量到了什么

## 这份东西为什么存在

关于一个型号，仓库里此刻同时存着**四种来路完全不同**的数：

======================  ====================================  ==================
数                      来路                                  没有时是什么意思
======================  ====================================  ==================
``size_mb``             目录里写死的声明（"按某一档量化记"）  没人填过
``effective_weight_mb`` **磁盘上那个 GGUF 的真实大小**        还没下载
``runtime_mb``          量过一次、写进源码的驻留量            没量过 → 退回权重
``kv_mb_per_1k``        **这台机器自己量的** KV 单价          没加载过 → 不知道
======================  ====================================  ==================

四种数散在四个模块里，**没有任何一处把它们并排放过**。于是「这台机器上这个型号
到底什么情况」这个问题，谁都答不上来 —— 而它恰恰是排查「模型带不动」时第一个
要问的。

## 一条硬规矩：**空 ≠ 未知**

每一行都必须说得出**这个数是哪来的**。一个没量过的 KV 单价写成 0，和量出来
真的是 0，在屏幕上必须长得不一样 —— 前者是"不知道"，后者是"知道它不要钱"。
所以这里不返回裸数字，返回的每一项都带着 ``source``。

这也是为什么算数的活在这儿、不在托盘里：托盘只负责把这些行显示出来。
两边各算一遍，迟早给出不同答案 —— 这个仓库为"同一个事实两处各存"栽过不止一次。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("Galaxy.ModelMeasurements")

__all__ = ["ModelRow", "measurement_rows", "render_report", "report_filename"]

#: 一个数没有时统一写这个词。**不是空字符串** —— 空的那一格会被读成"零"。
UNKNOWN = "未量过"

#: 磁盘那一栏没有时写这个词，**不写 UNKNOWN**。
#:
#: 「没量过」和「这台机器上根本没有这个文件」是两件不一样的事，而且后者是**可操作的**：
#: 看到「还没下载」的人知道下一步是去下载；看到「未量过」的人只会以为是哪个探测没跑。
#: 一个词把两种情况都盖住，就等于把那条能动手的信息咽掉了。
NOT_DOWNLOADED = "还没下载"


@dataclass
class ModelRow:
    """一个型号在这台机器上的全部账。每一栏都配一句"这数哪来的"。"""

    tag: str
    requires_gpu: bool
    #: 目录声明的权重（MB）。0 = 目录里没填过。
    declared_weight_mb: int = 0
    #: 磁盘上那个 GGUF 的真实大小（MB）。``None`` = 还没下载到本机。
    weight_on_disk_mb: Optional[int] = None
    #: 驻留量（MB）与它的来路。
    runtime_mb: int = 0
    runtime_source: str = UNKNOWN
    #: KV 单价（MB/1K）与它的来路："实测" / "目录声明" / "未知"。
    kv_per_1k_mb: int = 0
    kv_source: str = "未知"
    #: 这台机器上此刻的准入结论（要硬件画像才有；拿不到就是 None）。
    fit: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    def weight_diverged(self) -> bool:
        """磁盘上那份跟目录声明差得远不远 —— **差值本身就是"你换过量化"这条信息。**

        阈值 5% 与 :func:`core.model_catalog.effective_weight_mb` 一致：GGUF 头部
        与对齐填充带来百分之几的出入，报出来就成噪音。
        """
        if self.weight_on_disk_mb is None or self.declared_weight_mb <= 0:
            return False
        delta = abs(self.weight_on_disk_mb - self.declared_weight_mb)
        return delta / self.declared_weight_mb > 0.05


def _fmt_mb(value: Optional[int]) -> str:
    """MB → 人看的字符串。``None`` / 0 一律说成"没有"，**不写成 0**。"""
    if value is None:
        return UNKNOWN
    if value <= 0:
        return UNKNOWN
    if value >= 1024:
        return f"{value / 1024:.1f} GB"
    return f"{value} MB"


def measurement_rows(budget_mb: Optional[int] = None, has_gpu: Optional[bool] = None) -> List[ModelRow]:
    """把目录里每个本地型号的账拉齐。

    Args:
        budget_mb / has_gpu: 硬件画像。``None`` 则不给准入结论（``fit`` 留 ``None``）——
            **不是给一个"ok"**：没探到硬件和探到"装得下"是两件事。

    这个函数**不探硬件**。探测要 shell 出 nvidia-smi，冷调用可达数秒；让调用方
    决定要不要付这个代价，比在这里偷偷付掉好。
    """
    from core.model_catalog import all_models, effective_weight_mb

    rows: List[ModelRow] = []
    for spec in all_models():
        if getattr(spec, "source", "") != "local":
            continue  # 云端模型不吃本机显存，没有这本账
        tag = spec.tag
        row = ModelRow(
            tag=tag,
            requires_gpu=bool(getattr(spec, "requires_gpu", False)),
            declared_weight_mb=int(spec.size_mb()),
        )

        # 磁盘上那一份。
        #
        # **必须先问文件在不在**，不能直接拿 effective_weight_mb() 的返回值当"磁盘上的"：
        # 那个函数查不到文件时会**退回目录声明**（这是它该有的行为）。照着写的话，
        # 一台一个模型都没下载的机器，这份报告会把目录里的数原样抄成"磁盘上那一份" ——
        # 而这份报告存在的全部意义就是把这两者分开。自己犯一遍要治的病，尤其要记下来。
        try:
            from core.local_model_backends import resolve_gguf_path

            if resolve_gguf_path(tag):
                row.weight_on_disk_mb = int(effective_weight_mb(tag))
        except Exception as exc:  # noqa: BLE001
            logger.debug("读不到 %s 的磁盘权重: %s", tag, exc)

        # 驻留量:目录量过就是量过的,没量过 runtime_mb() 会退回权重 —— 那一档必须说清楚。
        row.runtime_mb = int(spec.runtime_mb())
        declared_runtime = int(getattr(spec, "runtime_mb_val", 0) or 0)
        row.runtime_source = "目录量过" if declared_runtime > 0 else "未量过 · 退回权重"

        # KV 单价:实测优先。
        try:
            from core.context_measurements import effective_kv_mb_per_1k, measured_source

            row.kv_per_1k_mb = int(effective_kv_mb_per_1k(tag))
            row.kv_source = measured_source(tag)
        except Exception as exc:  # noqa: BLE001
            logger.debug("读不到 %s 的 KV 单价: %s", tag, exc)

        if budget_mb is not None and has_gpu is not None:
            try:
                from core.routes.models import fit_detail

                row.fit = str(fit_detail(spec, has_gpu, int(budget_mb))["fit"])
            except Exception as exc:  # noqa: BLE001
                logger.debug("拿不到 %s 的准入结论: %s", tag, exc)

        if row.weight_diverged():
            row.notes.append(
                f"磁盘上是 {_fmt_mb(row.weight_on_disk_mb)}，目录记的是 "
                f"{_fmt_mb(row.declared_weight_mb)} —— 你换过量化"
            )
        if row.requires_gpu and row.kv_per_1k_mb <= 0:
            row.notes.append("KV 单价还没量到：加载一次就能量出来，在那之前准入不敢把它算进去")
        rows.append(row)
    return rows


def render_report(rows: List[ModelRow], budget_mb: Optional[int] = None) -> str:
    """把这些行渲染成一份能直接看、也能直接贴给人看的纯文本。

    刻意做成文本而不是 JSON：这份东西的读者是**对着托盘找问题的人**，
    不是另一个程序。
    """
    when = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")
    out: List[str] = [
        "本机模型实测账 / Model measurements on this machine",
        f"生成时间 {when}",
        "",
        f"显存预算：{_fmt_mb(budget_mb) if budget_mb else UNKNOWN}",
        "",
        "说明：每一栏都写着这个数是哪来的。「未量过」不等于 0 —— 前者是不知道，"
        "后者是知道它不要钱；「还没下载」也不是「未量过」—— 那一条是能动手的。",
        "",
    ]
    for row in rows:
        out.append(f"── {row.tag}{'（需显卡）' if row.requires_gpu else ''}")
        out.append(f"     目录声明权重   {_fmt_mb(row.declared_weight_mb)}")
        on_disk = _fmt_mb(row.weight_on_disk_mb) if row.weight_on_disk_mb else NOT_DOWNLOADED
        out.append(f"     磁盘上那一份   {on_disk}")
        out.append(f"     显存驻留       {_fmt_mb(row.runtime_mb)}  （{row.runtime_source}）")
        kv = f"{row.kv_per_1k_mb} MB/1K" if row.kv_per_1k_mb > 0 else UNKNOWN
        out.append(f"     KV 单价        {kv}  （{row.kv_source}）")
        if row.fit is not None:
            out.append(f"     这台机器上     {row.fit}")
        for note in row.notes:
            out.append(f"     ⚠ {note}")
        out.append("")
    if not rows:
        out.append("（目录里一个本地型号都没有 —— 这本身就不正常，不是「还没跑过」）")
    return "\n".join(out)


def report_filename() -> str:
    """导出的文件名。带时间戳 —— 换过量化、换过机器之后的两份要能摆在一起比。"""
    return datetime.now().strftime("model-measurements-%Y%m%d-%H%M%S.txt")


def snapshot(budget_mb: Optional[int] = None, has_gpu: Optional[bool] = None) -> Dict[str, Any]:
    """给程序看的那一份（面板 / 接口用）。与文本那份**同一个数据源**。"""
    rows = measurement_rows(budget_mb, has_gpu)
    return {
        "budget_mb": budget_mb,
        "rows": [
            {
                "tag": r.tag,
                "requires_gpu": r.requires_gpu,
                "declared_weight_mb": r.declared_weight_mb,
                "weight_on_disk_mb": r.weight_on_disk_mb,
                "runtime_mb": r.runtime_mb,
                "runtime_source": r.runtime_source,
                "kv_per_1k_mb": r.kv_per_1k_mb,
                "kv_source": r.kv_source,
                "fit": r.fit,
                "notes": list(r.notes),
            }
            for r in rows
        ],
    }
