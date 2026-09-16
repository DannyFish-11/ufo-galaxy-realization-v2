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

    def test_the_one_authority_still_reads_runtime(self) -> None:
        """``model_fit`` 自己必须问驻留量 —— 上面那条扫不到它（它用的是 budget_mb）。"""
        src = (_ROOT / "core/routes/models.py").read_text(encoding="utf-8")
        body = src[src.index("def model_fit(") :]
        body = body[: body.index("\ndef ")]
        body = re.sub(r'"""(?:.|\n)*?"""', " ", body)
        assert "runtime_mb()" in body, "显存准入的唯一落点不再问驻留量了"
        assert not re.search(r"\bsize_mb(_val)?\b", body), "显存准入又读回权重了 —— 这正是这道门要拦的那一跤"
