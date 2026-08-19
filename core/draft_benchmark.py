"""core/draft_benchmark.py — 投机解码的真机 A/B(唯一有资格说"值不值得"的那一步)
=================================================================================

``core.speculative_draft`` 把这件事切成三维:**声明**(存不存在)× **绑定能力**
(接不接得上)× **真机实测**(值不值得)。本模块是第三维的执行体。

为什么必须实测,而且必须扫块大小
--------------------------------
投机解码不是无条件加速。公开数据里同一件事既有 **+2.69×** 也有 **净 −44.6%**
(RTX 3090 + Q4_K_XL 走 llama.cpp),而且在**同一台机器上**,
``--spec-draft-n-max`` 取默认 15 是净亏、取 4 才 +27%。

也就是说:

* "开不开"没有正确的默认值 —— 只有这台机器的测量结果;
* "开多大块"同理,而且**默认值恰恰是常见的错误答案**。

所以这里不是"跑一次看看快不快",是**基线 + 扫一组块大小**,取最好的那个;
最好的那个还不如基线,就如实判 ``slower``。

三件不冒充彼此的失败
--------------------
====================  ======================================================
``unsupported``       这台机器的加载器接不上(绑定不透出参数 / 没装)。
                      不是"慢",是**没测成**;换个构建或改走 llama-server 才谈得上。
``error``             测的过程中炸了。也不是"慢"。
``slower``            **测成了,结论是别开。** 这是真实且常见的结果。
====================  ======================================================

把它们合成一个"没开成",用户会一直以为"回头再试试就好了",而其中一种情况的
正确处置是**永远别开**。

绝不自作主张写状态
------------------
本模块只**产出**一份 :class:`~core.speculative_draft.DraftMeasurement`,写不写盘由
调用方(``scripts/probe_models.py``)决定。测量是只读的观测,落盘是对运行时行为的
改变 —— 那一步该由人显式发起。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core.speculative_draft import DraftMeasurement, draft_spec_of, llama_binding_draft_support

logger = logging.getLogger("Galaxy.DraftBenchmark")

#: 要扫的块大小。**必须包含 15**(上游默认,也是公开实测里净亏的那个)和几个更小的 ——
#: 只测默认值会得出"投机解码没用"的错误结论,而只测小值会不知道默认值坑在哪。
DEFAULT_N_MAX_SWEEP: Tuple[int, ...] = (4, 8, 15)

#: 基准提示词。刻意选**会生成一段连续散文**的题目:投机解码的收益高度依赖
#: "下一段 token 好不好猜",而代码/列表这类高度结构化的输出会系统性地高估收益。
#: 用一个中性题目量出来的数,才是日常对话能指望的那个数。
BENCH_PROMPT: str = "用一段话解释：为什么把一件事拆开来做，往往比一次做完更快？"

#: 每次跑生成多少 token。太短的话加载/预填的抖动会淹没差异。
BENCH_MAX_TOKENS: int = 256

#: 每个配置跑几遍取最好 —— 单次采样的抖动能有百分之十几,而我们要判的阈值是 5%。
BENCH_REPEATS: int = 2

#: 量一次生成的超时(秒)。256 token 在慢机器上也就几十秒,给足余量。
_BENCH_TIMEOUT_S: float = 180.0


@dataclass(frozen=True)
class BenchRun:
    """一个配置跑一次的结果。``n_max=0`` 表示基线(草稿位关闭)。"""

    n_max: int
    tokens: int = 0
    seconds: float = 0.0
    error: str = ""

    @property
    def tok_s(self) -> float:
        return (self.tokens / self.seconds) if (self.seconds > 0 and self.tokens > 0) else 0.0

    @property
    def ok(self) -> bool:
        return not self.error and self.tok_s > 0


#: 跑一次生成的执行体。``n_max=0`` = 草稿位关闭(基线)。
#:
#: 返回 ``(tokens, seconds)``。抛异常即视为这次配置失败,不影响其余配置。
#: 做成可注入的,是为了让整条判定逻辑能在**不加载任何模型**的情况下被测到 ——
#: 与 ``core.model_probe`` 用 ``client=`` 注入是同一招。
Runner = Callable[[str, int], Tuple[int, float]]


def _default_runner(tag: str, n_max: int) -> Tuple[int, float]:
    """默认执行体 —— 走 ``llama-cpp-python`` 进程内加载。**它大概率用不了。**

    这不是悲观,是仓库里已经量过的事实:``core.local_model_backends.
    moe_offload_supported`` 的文档记着 —— llama-cpp-python 0.3.34 的
    ``Llama.__init__`` **既没有** ``n_cpu_moe`` **也没有** ``override_tensor``,
    底层结构体里有、高层封装不暴露。草稿位的 ``--spec-type`` / ``-md`` 是同一类
    **CLI/server 旗标**,没有理由指望它们的待遇更好。

    所以这里先问签名,接不上就**抛**,由上层如实判 ``unsupported``。

    为什么接不上之后就到此为止,不再"尽力试试"
    ------------------------------------------
    两条都不能做:

    * **不把旗标塞进 kwargs 碰运气** —— 会被静默忽略,表现是"开了但没变快",
      查起来要从头怀疑一遍。这正是专家卸载那个洞的形状。
    * **不照着一个想象中的 API 写实现** —— 绑定今天没有这条路,照着猜的签名写
      一段永远跑不到的代码,和照着记忆填显存数字是同一件事。

    真正可用的那条路是 llama.cpp 的 **server** 二进制(``llama-server``)——
    与专家卸载的补救办法是同一条(见 ``moe_offload_supported`` 的文档:
    换成 server + 经 ``GALAXY_LOCAL_OPENAI_URL`` 接入)。那条路用
    :func:`measure_endpoint` 量,见它的文档。
    """
    support, _found = llama_binding_draft_support()
    raise RuntimeError(
        f"llama-cpp-python 不透出草稿位参数(结论={support})。"
        "--spec-type / -md 是 llama.cpp CLI/server 的旗标,进程内绑定接不上 —— "
        "与 --n-cpu-moe 是同一个洞(见 local_model_backends.moe_offload_supported)。"
        "补救办法也相同:把推理位改成起 llama-server,经 GALAXY_LOCAL_OPENAI_URL 接入,"
        "再用 measure_endpoint 两趟对比。"
    )


def measure_endpoint(
    base_url: str,
    model: str,
    *,
    client: Any = None,
    max_tokens: int = BENCH_MAX_TOKENS,
) -> BenchRun:
    """量**当前正在跑的**那个 OpenAI 兼容服务有多快,一次,如实报。

    这是今天真正可用的那条路。llama-server 的草稿位旗标是**启动参数**,不是
    每请求参数 —— 所以没法在一个进程里 A/B。实际做法是人跑两趟:

    1. 不带旗标起 server → ``--draft-label baseline`` 量一次;
    2. 带 ``--spec-type ... --spec-draft-n-max 4`` 重起 → ``--draft-label 4`` 再量一次。

    两趟都量过之后由 :func:`verdict_from_labels` 给结论。**把"人得重起一次服务"
    这件事说出来**,比在代码里假装能自动切换要好 —— 后者只能靠猜服务怎么起的,
    猜错了量到的是同一个配置跑了两遍。

    ``n_max`` 记在标签里而不是从服务问出来:服务不报它自己是怎么起的。这一位
    因此是**人声明的**,报告里会照实标明这一点。
    """
    started = time.monotonic()
    try:
        http = client
        if http is None:
            import httpx  # noqa: PLC0415

            http = httpx.Client(timeout=_BENCH_TIMEOUT_S)
        resp = http.post(
            f"{str(base_url).rstrip('/')}/chat/completions",
            json={
                "model": model,
                "messages": [{"role": "user", "content": BENCH_PROMPT}],
                "max_tokens": int(max_tokens),
                "stream": False,
            },
        )
        seconds = time.monotonic() - started
        if getattr(resp, "status_code", 0) != 200:
            return BenchRun(n_max=-1, error=f"服务返回 {getattr(resp, 'status_code', '?')}")
        data = resp.json()
    except Exception as exc:  # noqa: BLE001 — 量不到就是量不到
        return BenchRun(n_max=-1, error=str(exc)[:200])

    # 优先用服务自己报的 completion_tokens —— 那是权威口径,比本地估准。
    usage = (data or {}).get("usage") or {}
    tokens = int(usage.get("completion_tokens") or 0)
    if tokens <= 0:
        choices = (data or {}).get("choices") or [{}]
        text = str(((choices[0] or {}).get("message") or {}).get("content") or "")
        tokens = _count_tokens(model, text)
    return BenchRun(n_max=0, tokens=tokens, seconds=seconds)


def _count_tokens(tag: str, text: str) -> int:
    try:
        from core.local_model_backends import count_tokens_with_loaded_model  # noqa: PLC0415

        n = int(count_tokens_with_loaded_model(tag, text) or 0)
        if n > 0:
            return n
    except Exception as exc:  # noqa: BLE001 — 数不出来不该让整次基准失败
        logger.debug("token 计数走后端失败,按字符粗估: %s", exc)
    # 粗估口径两侧一致,只影响绝对值不影响比值。
    return max(1, len(text) // 2)


def _run_once(runner: Runner, tag: str, n_max: int) -> BenchRun:
    try:
        tokens, seconds = runner(tag, n_max)
        return BenchRun(n_max=n_max, tokens=int(tokens), seconds=float(seconds))
    except Exception as exc:  # noqa: BLE001 — 单个配置失败不影响其余
        return BenchRun(n_max=n_max, error=str(exc)[:200])


def _best_of(runner: Runner, tag: str, n_max: int, repeats: int) -> BenchRun:
    """同一配置跑几遍取**最快**的一次。

    取最快而不是取平均:我们要回答的是"这个配置能有多快",而慢的那几次多半是
    别的东西在抢卡。取平均会让一次后台编译把结论压翻。
    """
    runs = [_run_once(runner, tag, n_max) for _ in range(max(1, repeats))]
    ok = [r for r in runs if r.ok]
    if not ok:
        return runs[-1]
    return max(ok, key=lambda r: r.tok_s)


def benchmark_draft(
    tag: str,
    *,
    runner: Optional[Runner] = None,
    n_max_sweep: Sequence[int] = DEFAULT_N_MAX_SWEEP,
    repeats: int = BENCH_REPEATS,
) -> Tuple[DraftMeasurement, List[BenchRun]]:
    """对一个型号跑基线 + 扫块大小,给出结论。

    Returns:
        ``(结论, 每个配置的原始结果)``。原始结果一并返回是有用的 —— 用户要看的
        往往不是"开还是不开",而是"15 到底差多少",那正是块大小该扫的理由。

    不写盘。见模块头"绝不自作主张写状态"。
    """
    spec = draft_spec_of(tag)
    if not spec.is_possible:
        return (
            DraftMeasurement(
                tag=tag,
                verdict="unsupported",
                detail=f"目录里这个型号的草稿位是 {spec.mechanism}（没有可用机制/候选），无从测起",
            ),
            [],
        )

    run = runner or _default_runner
    base = _best_of(run, tag, 0, repeats)
    if not base.ok:
        # 基线都跑不起来 —— 分不清是"接不上"还是"炸了",看错误本身。
        verdict = "unsupported" if "不透出" in base.error or "接不上" in base.error else "error"
        return (
            DraftMeasurement(tag=tag, verdict=verdict, n_max=0, detail=base.error or "基线未产出 token"),
            [base],
        )

    runs = [base]
    best: Optional[BenchRun] = None
    for n in n_max_sweep:
        if int(n) <= 0:
            continue
        r = _best_of(run, tag, int(n), repeats)
        runs.append(r)
        if r.ok and (best is None or r.tok_s > best.tok_s):
            best = r

    return _verdict_from_runs(tag, base, runs[1:]), runs


def _verdict_from_runs(tag: str, base: BenchRun, candidates: Sequence[BenchRun]) -> DraftMeasurement:
    """基线 + 一组带草稿的结果 → 结论。**判定只此一处。**

    抽出来是因为有两条路会走到它:进程内扫块大小(:func:`benchmark_draft`)和
    人跑两趟量服务(:func:`verdict_from_labels`)。同一条判定写两份,迟早会在
    "多少算更快"上分叉。
    """
    spec = draft_spec_of(tag)
    usable = [r for r in candidates if r.ok]
    if not usable:
        errs = [r.error for r in candidates if r.error]
        verdict = "unsupported" if any("不透出" in e or "接不上" in e for e in errs) else "error"
        return DraftMeasurement(
            tag=tag,
            verdict=verdict,
            baseline_tok_s=base.tok_s,
            detail=(errs[0] if errs else "带草稿的那几次都没产出 token"),
        )

    best = max(usable, key=lambda r: r.tok_s)
    speedup = best.tok_s / base.tok_s if base.tok_s > 0 else 0.0
    return DraftMeasurement(
        tag=tag,
        # 阈值判定归 DraftMeasurement.should_enable —— 这里只如实说方向。
        # 把 MIN_SPEEDUP 也搬进来的话,同一条线就有了两个定义。
        verdict="faster" if speedup > 1.0 else "slower",
        baseline_tok_s=base.tok_s,
        draft_tok_s=best.tok_s,
        speedup=speedup,
        n_max=best.n_max,
        drafter_repo=(spec.candidate_repos[0] if spec.candidate_repos else spec.mechanism),
        # 自带 MTP 头的没有独立权重 → 0 是**确定的 0**(见 draft_footprint_mb)。
        # 外挂式的这里量不到,留 0 由 draft_footprint_mb 判成"判不了"。
        drafter_runtime_mb=0,
        measured_at=time.time(),
        detail=f"基线 {base.tok_s:.1f} tok/s;最好 n_max={best.n_max} → {best.tok_s:.1f} tok/s",
    )


def verdict_from_labels(tag: str, labelled: Dict[str, BenchRun]) -> DraftMeasurement:
    """把人跑两趟量到的结果合成一个结论。

    ``labelled`` 的键:``"baseline"`` 和若干个 ``n_max`` 的十进制字符串。
    这些标签是**人声明的**(服务不报它自己是怎么起的),报告里会照实标明。

    没有 baseline 就判 ``untested`` —— 只量了开着的那一趟,得不出任何结论,
    而"比什么都没有强"在这里是错的:没有基线时,一个漂亮的 tok/s 完全可能比
    关掉还慢。
    """
    base = labelled.get("baseline")
    if base is None or not base.ok:
        return DraftMeasurement(tag=tag, verdict="untested", detail="缺基线那一趟(--draft-label baseline)")
    cands: List[BenchRun] = []
    for label, run in labelled.items():
        if label == "baseline":
            continue
        try:
            n = int(label)
        except (TypeError, ValueError):
            continue
        cands.append(BenchRun(n_max=n, tokens=run.tokens, seconds=run.seconds, error=run.error))
    if not cands:
        return DraftMeasurement(
            tag=tag,
            verdict="untested",
            baseline_tok_s=base.tok_s,
            detail="只量了基线,还没量开着草稿位的那一趟",
        )
    return _verdict_from_runs(tag, base, cands)


def format_bench_report(m: DraftMeasurement, runs: Sequence[BenchRun]) -> str:
    """把一次基准渲染成人能读的一段。"""
    lines: List[str] = []
    lines.append(f"型号: {m.tag}    结论: {m.verdict}")
    if runs:
        lines.append(f"  {'配置':<16}{'tok/s':>10}   备注")
        for r in runs:
            label = "基线(关)" if r.n_max == 0 else f"n_max={r.n_max}"
            note = r.error or ""
            lines.append(f"  {label:<16}{r.tok_s:>10.1f}   {note}")
    if m.verdict in ("faster", "slower"):
        lines.append(f"  最好 {m.speedup:.2f}×（阈值 1.05×）→ {'建议开' if m.should_enable else '建议不开'}")
    if m.detail:
        lines.append(f"  {m.detail}")
    if m.verdict == "unsupported":
        lines.append("  ↑ 这不是「慢」，是【没测成】——换个透出参数的构建，或把推理位改走 llama-server 子进程。")
    return "\n".join(lines)


__all__ = [
    "DEFAULT_N_MAX_SWEEP",
    "BENCH_PROMPT",
    "BENCH_MAX_TOKENS",
    "BENCH_REPEATS",
    "BenchRun",
    "Runner",
    "benchmark_draft",
    "measure_endpoint",
    "verdict_from_labels",
    "format_bench_report",
]
