"""显存准入的**调用点**必须问驻留量，不是权重。

## 这道门为什么要单独存在

仓库里已经有一条 ``test_vram_admission_reads_runtime_not_weights.py``（9 条），
讲的正是这件事。但那 9 条全部只测 :class:`ModelSpec` 那一层的 API ——
``runtime_mb()`` 返回对不对、两栏有没有塌成一个数。**没有一条查得到消费方。**

于是发生了这样一件事：

* ``ModelSpec`` 拆成两栏、文档里写明「显存准入只问这一处」  ✅
* ``core/model_selection.py`` 照着改了，注释里还复述了一遍那个失败  ✅
* ``core/routes/models.py`` —— **一直拿 ``spec.size_mb_val`` 去比显存预算**  ❌

模型层修好了、消费方没跟上。这是本仓库最典型的那种半截修法：看起来接上了，
其实没有。而且它不报错、不变红，只在真机上表现为「模型带不动」。

## 拿权重当显存，**两个方向都会错**

| | 权重 | 驻留 | 8 GB 卡上 |
| --- | --- | --- | --- |
| MiniCPM-o 4.5 | 6 GB | **11 GB** | 按权重判「放得下」→ 加载到一半 OOM |
| Qwen3.6 35B-A3B | 18 GB | **7.3 GB** | 按权重判「装不下」→ 白挡一档能跑的 |

前者是把不能跑的说成能跑，后者是把能跑的说成不能跑。**都是在骗人，只是方向相反。**

## 这道门的两半

1. **行为**：拿真目录去问真函数。任何人把它换回权重，MiniCPM-o 那一条立刻变红。
2. **源码**：扫所有消费方，不许再出现「拿 size_mb 去比显存预算」的写法 ——
   行为那一半只守得住现在这一个调用点，守不住下一个新写的。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.model_catalog import get_model
from core.routes.models import model_fit

_ROOT = Path(__file__).resolve().parents[1]

#: 一块 8 GB 卡。挑这个数是因为上面那张表里的两种错都在它身上发生。
_EIGHT_GB = 8192


class TestTheAdmissionAsksForResidency:
    def test_a_model_that_swells_past_its_weights_is_refused(self) -> None:
        """MiniCPM-o 4.5：权重 6 GB，跑起来 11 GB。

        **这一条是这道门的判别点。** 把 ``runtime_mb()`` 换回 ``size_mb``，
        它立刻变红 —— 而在此之前，这个调用点从来没有被任何判据碰过。
        """
        spec = get_model("openbmb/minicpm-o4.5")
        assert spec is not None, "目录里没有这个型号了，这条要重写"
        assert spec.runtime_mb() > spec.size_mb(), "两栏又变成同一个数了 —— 那这条测试也就白测了"
        assert model_fit(spec, True, _EIGHT_GB) == "insufficient_vram", (
            f"权重 {spec.size_mb()} MB、驻留 {spec.runtime_mb()} MB，"
            f"在 {_EIGHT_GB} MB 的卡上被判成装得下 —— 加载到一半必 OOM，"
            "而且报错在加载途中不在准入处，现场看到的是「模型带不动」。"
        )

    def test_a_model_that_offloads_below_its_weights_is_admitted(self) -> None:
        """35B-A3B：权重 18 GB，专家卸载后驻留 7.3 GB。

        这是**反方向**的那一种错：拿权重判，一档本来跑得动的会被白白挡掉。
        """
        spec = get_model("qwen3.6:35b-a3b")
        assert spec is not None, "目录里没有这个型号了，这条要重写"
        assert spec.runtime_mb() < spec.size_mb(), "专家卸载那一栏没了，这条要重写"
        assert model_fit(spec, True, _EIGHT_GB) == "ok", (
            f"权重 {spec.size_mb()} MB 但驻留只有 {spec.runtime_mb()} MB，"
            f"在 {_EIGHT_GB} MB 的卡上被判成装不下 —— 白挡了一档跑得动的。"
        )

    @pytest.mark.parametrize(
        ("has_gpu", "budget", "want"),
        [
            (False, _EIGHT_GB, "no_gpu"),  # 需显卡但没有:CPU 硬爬,如实告警
            (True, 4096, "insufficient_vram"),  # 有卡但太小
            (True, 16384, "ok"),  # 够大
        ],
    )
    def test_the_three_verdicts_are_all_reachable(self, has_gpu: bool, budget: int, want: str) -> None:
        """三种结论都得走得到。**少一种就是把三档压成了两档。**"""
        spec = get_model("openbmb/minicpm-o4.5")
        assert spec is not None
        assert model_fit(spec, has_gpu, budget) == want

    def test_a_model_that_needs_no_gpu_is_never_refused(self) -> None:
        """不需显卡的型号不吃显存 —— 无卡机器上也该是 ok，不是 no_gpu。"""
        spec = get_model("gemma4:e2b")
        assert spec is not None, "目录里没有这个型号了，这条要重写"
        assert not spec.requires_gpu
        assert model_fit(spec, False, 0) == "ok"


class TestNoConsumerGoesBackToWeights:
    """源码这一半：守住**下一个**新写的消费方。

    行为那一半只钉得住 ``model_fit`` 这一个调用点。哪天有人在别处再写一遍
    「拿模型大小去比显存」，行为那一半一个字都不会红。
    """

    #: 允许出现「size_mb 与某个预算比大小」的地方，以及为什么。
    _ALLOWED = {
        # 目录自己要解释两栏的差别，注释和 docstring 里必然提到两个名字。
        "core/model_catalog.py": "两栏的定义处，它就是在讲这两个数的区别",
        # 这一份讲的是磁盘/下载量，不是显存。
        "core/huggingface_model_manager.py": "下载与磁盘占用，和显存无关",
    }

    def test_nobody_compares_weights_against_a_vram_budget(self) -> None:
        offenders: dict[str, str] = {}
        for path in (_ROOT / "core").rglob("*.py"):
            rel = path.relative_to(_ROOT).as_posix()
            if rel in self._ALLOWED:
                continue
            text = path.read_text(encoding="utf-8")
            # 去掉注释与 docstring 再看 —— 判据钉的是代码，不是文档里提过这几个词。
            # 本仓库为「钉在注释上」栽过不止一次。
            text = re.sub(r'"""(?:.|\n)*?"""', " ", text)
            text = re.sub(r"(?<![:'\"])#[^\n]*", " ", text)
            for i, line in enumerate(text.split("\n"), 1):
                # 同一行里既拿 size_mb 当左值、又跟一个显存预算比大小。
                if re.search(r"\bsize_mb(_val)?\b\s*[<>]=?", line) and re.search(
                    r"max_model_size_mb|free_vram|vram_mb|budget_mb", line
                ):
                    offenders[f"{rel}:{i}"] = line.strip()
        assert not offenders, (
            f"这些地方又拿权重去比显存预算了：{offenders}。\n"
            "权重和驻留两个方向都会差很远（MiniCPM-o 6→11 GB，35B-A3B 18→7.3 GB）——"
            "拿权重判，一边会把 OOM 的说成能跑，另一边会把跑得动的白白挡掉。"
            "显存相关的判断一律问 ModelSpec.runtime_mb()。"
        )

    @staticmethod
    def _body(name: str) -> str:
        src = (_ROOT / "core/routes/models.py").read_text(encoding="utf-8")
        body = src[src.index(f"def {name}(") :]
        body = body[: body.index("\ndef ")]
        return re.sub(r'"""(?:.|\n)*?"""', " ", body)

    def test_the_one_authority_still_reads_runtime(self) -> None:
        """做那次比较的那个函数必须问驻留量 —— 上面那条扫不到它（它用的是 budget_mb）。

        判据钉的是**做比较的那一个**，不是某个固定的函数名。落点从 ``model_fit``
        挪到 ``fit_detail`` 时这条红过一次 —— 那是对的：权威搬了家，判据就该跟着搬，
        而不是留在原地继续绿。
        """
        bodies = {n: self._body(n) for n in ("model_fit", "fit_detail")}
        comparing = [n for n, b in bodies.items() if re.search(r"> *budget_mb", b)]
        assert comparing, f"没有任何一个函数再拿显存预算做比较了：{list(bodies)}"
        for name in comparing:
            assert "runtime_mb()" in bodies[name], f"{name} 做显存准入却不问驻留量了"
        # 两个都不许读权重 —— 包括那个只做转发的。
        for name, body in bodies.items():
            assert not re.search(r"\bsize_mb(_val)?\b", body), f"{name} 又读回权重了 —— 这正是这道门要拦的那一跤"

    def test_the_kv_cache_is_counted_when_its_price_is_known(self) -> None:
        """权重放得下 ≠ 跑得起来：llama.cpp 加载时把整个 KV cache 一次性分配掉。

        单价**未知时不加**，这跟调度器是同一条规矩（不知道分母就不敢动真实需求）；
        但**知道了就必须加**，否则那次测量等于白量。
        """
        body = self._body("fit_detail")
        assert "effective_kv_mb_per_1k" in body, "准入不再问 KV 单价 —— 那台机器量到的那个数就白量了"
        assert "MIN_CTX" in body, "KV 那一项不再按最短上下文算 —— 那它按的是什么？"
        assert re.search(r"if per_1k > 0", body), "单价未知时也去加 KV —— 拿一个编出来的数收紧准入，和拿它放开一样坏"

    def test_an_ok_that_rests_on_an_unknown_says_so(self) -> None:
        """**一个「取决于没人量过的数」的 ok，不能和「算全了还是 ok」长得一样。**

        KV 单价未知时准入不加那一项（这是对的，见上一条）。可这样就会出现一种
        过关过得很像样、其实没人验过的情形：默认主脑 ``gemma4:12b`` 驻留 8000 MB，
        在一块 8 GB 卡上判 ``ok``，**余量只有 192 MB** —— 只要有人量到它的 KV 单价
        超过 96 MB/1K，同一条判断立刻翻面。

        不把这个前提说出来，读的人会安心去用，然后在**加载途中**撞 OOM —— 而报错
        不在准入处，现场看到的只是「模型带不动」。这个仓库为这条路径栽过一次了。
        """
        from core.routes.models import fit_detail as _fd

        spec = get_model("gemma4:12b")
        assert spec is not None
        d = _fd(spec, True, _EIGHT_GB)
        assert d["fit"] == "ok"
        assert d["provisional"] is True, "KV 没量过就过的关，却没说这个 ok 是有前提的"
        assert d["headroom_mb"] == _EIGHT_GB - spec.runtime_mb()
        assert d["kv_break_even_per_1k"] > 0, "没说单价到多少会翻面 —— 那这个警告没法行动"
        # 翻面点必须是**真的**翻面点,不是随手一个正数。
        from core.model_catalog import MIN_CTX

        assert d["kv_break_even_per_1k"] == d["headroom_mb"] * 1024 // MIN_CTX

    def test_an_ok_with_kv_counted_is_not_provisional(self, monkeypatch) -> None:
        """判别点的另一半：KV 真算进去了的 ok，**不许**还挂着那个前提。

        少了这一条，上面那条只要把 ``provisional`` 恒设为 True 就能绿 —— 于是每一行
        都挂着警告，等于没有警告。
        """
        import core.context_measurements as cm

        monkeypatch.setattr(cm, "effective_kv_mb_per_1k", lambda _t: 20)
        monkeypatch.setattr(cm, "measured_source", lambda _t: "实测")
        from core.routes.models import fit_detail as _fd

        spec = get_model("gemma4:12b")
        d = _fd(spec, True, 16384)
        assert d["fit"] == "ok"
        assert d["kv_mb"] > 0, "单价量到了却没算进去"
        assert d["provisional"] is False, "KV 已经算进去了，还说这个 ok 是有前提的"
        # **余量必须把 KV 减掉。** 目录里此刻没有一个型号量过 KV 单价，于是
        # ``kv_mb`` 处处是 0 —— 只看目录的话，余量减不减 KV 一个字都不会变，
        # 这一栏就成了空判据。只有在这儿（单价是造出来的）才分得出来。
        assert d["headroom_mb"] == 16384 - spec.runtime_mb() - d["kv_mb"], (
            f"余量 {d['headroom_mb']} 没把 KV 那 {d['kv_mb']} MB 减掉 —— "
            "面板会照着它说「还剩这么多」，而那块显存已经被 KV 占了。"
        )

    def test_a_refusal_is_never_provisional(self) -> None:
        """判不下的时候没有"前提"可言 —— 它已经是结论了。"""
        from core.routes.models import fit_detail as _fd

        d = _fd(get_model("openbmb/minicpm-o4.5"), True, _EIGHT_GB)
        assert d["fit"] == "insufficient_vram"
        assert d["provisional"] is False
        assert d["headroom_mb"] < 0, "装不下，余量却不是负的 —— 那「差多少」这一栏是错的"

    def test_a_model_that_needs_no_card_does_not_report_a_vram_headroom(self) -> None:
        """不吃显存的型号，整份预算原封不动。

        写成 ``budget - resident`` 的话，那个数看着像「占掉之后还剩这些」，
        而它根本没占 —— 面板照着显示，就等于说这一档占着卡。
        """
        from core.routes.models import fit_detail as _fd

        d = _fd(get_model("gemma4:e2b"), True, _EIGHT_GB)
        assert d["headroom_mb"] == _EIGHT_GB, "不吃显存的型号却报了个被占掉的余量"
        # 没有卡的时候更没有"还剩多少"这回事。
        no_card = _fd(get_model("openbmb/minicpm-o4.5"), False, _EIGHT_GB)
        assert no_card["fit"] == "no_gpu"
        assert no_card["headroom_mb"] == 0, "这台机器上没有这块显存，却报了个余量"

    def test_the_numbers_behind_the_verdict_come_out_too(self) -> None:
        """面板写「显存装不下」时，人接着问的是「差多少」。

        这几个数必须由准入这一处一起给出 —— 让面板自己再算一遍，就是同一个事实两处各存。
        """
        from core.routes.models import fit_detail as _fd

        spec = get_model("gemma4:12b")
        assert spec is not None
        d = _fd(spec, True, _EIGHT_GB)
        for key in ("fit", "tag", "resident_mb", "kv_mb", "kv_per_1k_mb", "kv_source", "budget_mb"):
            assert key in d, f"准入结果里少了 {key} —— 面板就得自己去算"
        assert d["resident_mb"] == spec.runtime_mb()
        assert d["budget_mb"] == _EIGHT_GB
