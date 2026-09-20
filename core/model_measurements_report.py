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

#: 该问的那条路**没答上来**时写这个词。
#:
#: 它跟 :data:`NOT_DOWNLOADED` 的区别是这份报告里最要紧的一条：
#: 「还没下载」是一个**断言**（我问过了，那儿没有），「问不到」是**没有断言**
#: （该问的人没应答）。把后者写成前者，就是拿一个没根据的事实去回答人 ——
#: 而这正是我在这份报告上犯的第二跤，见 :func:`_weight_on_this_machine`。
UNREACHABLE = "问不到"


@dataclass
class ModelRow:
    """一个型号在这台机器上的全部账。每一栏都配一句"这数哪来的"。"""

    tag: str
    requires_gpu: bool
    #: 目录声明的权重（MB）。0 = 目录里没填过。
    declared_weight_mb: int = 0
    #: 这台机器上那一份权重的真实大小（MB）。``None`` = 没拿到数。
    #:
    #: **拿不到有两种，必须靠 ``weight_source`` 分开**：该问的那条路答了"没有"
    #: （还没下载），还是那条路根本没应答（问不到）。见 :func:`_weight_on_this_machine`。
    weight_on_disk_mb: Optional[int] = None
    #: 上面那个数是从哪条路问到的 / 为什么没问到。
    weight_source: str = UNKNOWN
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


def _ollama_installed() -> Optional[Dict[str, int]]:
    """问 Ollama 自己：这台机器上装着哪些模型、各多大（MB）。

    返回 ``None`` 表示**这条路没问到**（没起来 / 超时 / 格式不认识），
    **不表示"一个都没装"**。调用方必须把这两者分开 —— 混在一起就会对着一台
    模型齐全的机器说"还没下载"。

    地址走 :func:`core.ollama_endpoint.resolve_ollama_base_url`，不另立一份。
    """
    try:
        import json as _json
        import urllib.request

        from core.ollama_endpoint import resolve_ollama_base_url

        url = f"{resolve_ollama_base_url()}/api/tags"
        with urllib.request.urlopen(url, timeout=2.0) as resp:  # noqa: S310
            if getattr(resp, "status", 200) != 200:
                return None
            payload = _json.loads(resp.read().decode("utf-8", "replace"))
    except Exception as exc:  # noqa: BLE001
        logger.debug("问不到 Ollama 装了什么: %s", exc)
        return None
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        return None  # 格式不认识也是"没问到",不是"没装"
    out: Dict[str, int] = {}
    for m in models:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "")
        size = m.get("size")
        if name and isinstance(size, (int, float)) and size > 0:
            out[name] = int(size) // (1024 * 1024)
    return out


def _ollama_match(tag: str, installed: Dict[str, int]) -> Optional[int]:
    """Ollama 那张表里哪一条是这个目录 tag —— **精确，或者带后缀的同一个**。

    ``gemma4:12b`` 认 ``gemma4:12b`` 和 ``gemma4:12b-instruct``，
    **不认** ``gemma4:e2b``。

    这里刻意**不复用** :meth:`core.multi_llm_router.MultiLLMRouter._provider_serving`
    的匹配：那一套按根名（``tag.split(":")[0]``）松匹配，对"该向哪台服务报哪个 id"
    是对的，对**尺寸**是灾难性的 —— ``gemma4:12b`` 的根名是 ``gemma4``，会匹配上
    ``gemma4:e2b``，于是一个 12B 被答成 1.8 GB。目录里 :func:`exact_model` 存在的
    理由一模一样：**猜错的数字比没有数字更危险。**
    """
    if tag in installed:
        return installed[tag]
    for name, size in installed.items():
        if name.startswith(f"{tag}-"):
            return size
    return None


def _weight_on_this_machine(tag: str, effective_weight_mb: Any, installed: Optional[Dict[str, int]]) -> Any:
    """这台机器上这份权重多大，以及**这个答案是从哪条路问到的**。

    返回 ``(mb_or_None, source)``。

    按这个 tag **实际由谁加载**分路 —— 这是第二跤的所在。第一版只问
    :func:`~core.local_model_backends.resolve_gguf_path`（直给路径 / HF 登记表 /
    ``models/*.gguf``），可 Gemma 4 全家和 MiniCPM-o 走的都是 **Ollama**，权重压根
    不在 ``models/`` 底下。于是那一版对着一台 Ollama 拉齐了模型的机器，逐行写
    「还没下载」—— 说的和现实相反，而且比它替换掉的「未量过」更坏：
    「未量过」是没有断言，「还没下载」是一个**错的断言**。

    三种没有数的情形必须各说各的：

    * 那条路答了「没有」        → :data:`NOT_DOWNLOADED`（可操作：去下载）
    * 那条路没应答              → :data:`UNREACHABLE`（先把它起起来再问）
    * 压根没有能问的路          → :data:`UNKNOWN`
    """
    from core.model_catalog import backend_for_tag

    backend = backend_for_tag(tag)

    if backend == "ollama":
        if installed is None:
            return None, f"{UNREACHABLE} · Ollama 没应答"
        size = _ollama_match(tag, installed)
        if size is None:
            return None, f"{NOT_DOWNLOADED} · Ollama 里没有这一条"
        return size, "Ollama 里那一份"

    # llama.cpp 这条路:权重是磁盘上的 GGUF 文件。
    #
    # **必须先问文件在不在**,不能直接拿 effective_weight_mb() 的返回值当"磁盘上的":
    # 那个函数查不到文件时会**退回目录声明**(这是它该有的行为)。照着写的话,
    # 一台一个模型都没下载的机器,报告会把目录里的数原样抄成"磁盘上那一份" ——
    # 而这份报告存在的全部意义就是把这两者分开。这是第一跤。
    try:
        from core.local_model_backends import resolve_gguf_path

        if resolve_gguf_path(tag):
            return int(effective_weight_mb(tag)), "磁盘上的 GGUF"
        return None, f"{NOT_DOWNLOADED} · models/ 底下没有"
    except Exception as exc:  # noqa: BLE001
        logger.debug("读不到 %s 的磁盘权重: %s", tag, exc)
        return None, f"{UNREACHABLE} · 找不动文件"


def measurement_rows(budget_mb: Optional[int] = None, has_gpu: Optional[bool] = None) -> List[ModelRow]:
    """把目录里每个本地型号的账拉齐。

    Args:
        budget_mb / has_gpu: 硬件画像。``None`` 则不给准入结论（``fit`` 留 ``None``）——
            **不是给一个"ok"**：没探到硬件和探到"装得下"是两件事。

    这个函数**不探硬件**。探测要 shell 出 nvidia-smi，冷调用可达数秒；让调用方
    决定要不要付这个代价，比在这里偷偷付掉好。

    但它**会打一个本机回环**：``GET /api/tags`` 问 Ollama 装了什么（2 秒上限，
    整张表只问一次）。这条不让调用方选，因为没有它就答不出"这台机器上有没有
    这一份" —— 而那正是这份账的题面。问不到就如实写「问不到」，绝不退回
    「还没下载」：后者是一个断言，没根据就不能说。
    """
    from core.model_catalog import BACKEND_BY_SOURCE, all_models, effective_weight_mb

    # 问一次,给所有行用 —— 每行问一次的话,一张表要打十几个回环。
    installed = _ollama_installed()

    rows: List[ModelRow] = []
    for spec in all_models():
        # 凡是**在本机加载**的都要有这本账。
        #
        # 这里第一版写的是 ``source != "local"``,理由记的是"云端模型不吃本机显存" ——
        # 两头都错：``all_models()`` 里压根没有云端型号，而 ``source`` 说的不是
        # 云/本地，是**由哪个后端加载**。于是 ``llama_cpp`` 那三个被当成云端漏掉了，
        # 其中 ``qwen3.6:35b-a3b`` 正是专家卸载那一例 —— 显存账最该看的那一个，
        # 被一句想当然的注释挡在了账外。权威是 ``BACKEND_BY_SOURCE``:
        # 它有键，就说明这个 source 由某个本机后端加载。
        if str(getattr(spec, "source", "")).strip() not in BACKEND_BY_SOURCE:
            continue
        tag = spec.tag
        row = ModelRow(
            tag=tag,
            requires_gpu=bool(getattr(spec, "requires_gpu", False)),
            declared_weight_mb=int(spec.size_mb()),
        )

        row.weight_on_disk_mb, row.weight_source = _weight_on_this_machine(tag, effective_weight_mb, installed)

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
        "后者是知道它不要钱。「还没下载」和「问不到」也不是一回事：前者是问过了、"
        "那儿没有（去下载就是了），后者是该应答的那一位没应答（先把它起起来）。",
        "",
    ]
    for row in rows:
        out.append(f"── {row.tag}{'（需显卡）' if row.requires_gpu else ''}")
        out.append(f"     目录声明权重   {_fmt_mb(row.declared_weight_mb)}")
        have = _fmt_mb(row.weight_on_disk_mb) if row.weight_on_disk_mb else ""
        out.append(f"     这台机器上那份 {have or row.weight_source}" + (f"  （{row.weight_source}）" if have else ""))
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
                "weight_source": r.weight_source,
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
