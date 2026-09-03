"""ABCD 档位必须在面板上**选得到**,而且「装不下」必须看得见。

档位(A 轻量本地 / B 全模态单模型 / C 双模型·35B 推理位 / D 双模型·9B 推理位)
的唯一定义处是 ``core/model_catalog.py`` 的 ``_TIERS``。这个文件守三件事:

1. **「这一档装不装得下」的判断在后端做。** ``gpu_fit`` 是逐模型的,面板要显示的
   却是「这一档能不能选」,中间隔着一步聚合。那一步放到前端的话,判据就跟着渲染
   代码走了 —— 换个界面就得重写一遍,两处迟早给出不同答案。
2. **``unknown`` 不许被当成 ``ok``。** 硬件没探到就是没探到;当成能跑的话,面板会
   把「不知道」画成「能跑」,而人正是照着那个画面选档的。
3. **面板不许自己存一份档位表。** 同 CONFIG_BUNDLES 那条:目录里加一档、改一个
   型号,面板要立刻跟着变,而不是等人回来改前端。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core.model_catalog import all_tiers
from core.routes.models import _tier_fit

REPO_ROOT = Path(__file__).resolve().parent.parent
PANEL_SRC = REPO_ROOT / "electron" / "renderer" / "panel" / "src"
PANEL_DIST = REPO_ROOT / "electron" / "renderer" / "panel" / "dist"


def _snap(**tiers: list[str]) -> dict:
    """一份最小的目录快照:``{档: 这一档真正会加载的 tag}``。"""
    return {"tiers": [{"key": k, "active_tags": v} for k, v in tiers.items()]}


class TestTheTierLevelJudgementLivesInTheBackend:
    def test_the_worst_active_model_decides(self):
        """一档里有一个装不下,这一档就装不下 —— 取最坏的那个,不是平均、不是第一个。"""
        out = _tier_fit(_snap(X=["a", "b"]), {"a": "ok", "b": "no_gpu"})
        assert out["X"]["fit"] == "no_gpu"
        assert out["X"]["blocked_by"] == ["b"]
        assert out["X"]["reason"], "说了装不下却不说为什么 —— 用户下一步不知道该干嘛"

    def test_insufficient_vram_and_no_gpu_are_not_the_same_thing(self):
        """两种装不下的下一步完全不同:一个换显卡,一个换量化/换档。

        压成一个「装不下」的话,界面就只能说「不行」而说不出「为什么不行」。
        """
        vram = _tier_fit(_snap(X=["a"]), {"a": "insufficient_vram"})["X"]
        none = _tier_fit(_snap(X=["a"]), {"a": "no_gpu"})["X"]
        assert vram["fit"] != none["fit"]
        assert vram["reason"] != none["reason"]

    def test_no_gpu_outranks_insufficient_vram(self):
        """没显卡比装不下更严重 —— 一档里两种都有时,报更严重的那个。"""
        out = _tier_fit(_snap(X=["a", "b"]), {"a": "insufficient_vram", "b": "no_gpu"})
        assert out["X"]["fit"] == "no_gpu"

    def test_candidates_that_are_not_selected_do_not_block_the_tier(self):
        """一档四选一,其中一个装不下不代表这一档不能用。

        判据只看 ``active_tags``(这一档**真正会加载**的那几个)。拿候选表整个来判
        的话,C 档的感知位有四个候选、只装一个,却会因为最重的那个装不下而被判成
        整档不可用 —— 而它明明能跑。
        """
        out = _tier_fit(_snap(X=["light"]), {"light": "ok", "heavy": "no_gpu"})
        assert out["X"]["fit"] == "ok"
        assert out["X"]["blocked_by"] == []

    def test_a_tag_with_no_fit_record_counts_as_ok(self):
        """云端模型不吃本机显存,没有 fit 记录不该把整档判成装不下。"""
        assert _tier_fit(_snap(X=["cloud-model"]), {})["X"]["fit"] == "ok"

    def test_every_real_tier_gets_a_verdict(self):
        """目录里的每一档都必须有结论 —— 漏掉的那一档在面板上就是 unknown。"""
        snap = {"tiers": [{"key": t.key, "active_tags": []} for t in all_tiers()]}
        out = _tier_fit(snap, {})
        assert set(out) == {t.key for t in all_tiers()}


class TestUnknownIsNotOk:
    """探测失败时每一档都是 unknown,不是 ok。

    这条守的是「降级必须留痕」:硬件探测炸了(nvidia-smi 不在、权限不足、超时),
    目录照样要返回 —— 但不能顺手把「没判断」写成「能跑」。面板对 unknown 有单独
    一种画法(虚线边),对 ok 是正常样子;两者混在一起的话,一台探测一直失败的机器
    会一路显示「四档都能跑」。
    """

    @pytest.mark.asyncio
    async def test_probe_failure_yields_unknown_for_every_tier(self, monkeypatch):
        import core.routes.models as mod

        def boom():
            raise RuntimeError("探测炸了")

        monkeypatch.setattr(mod, "get_hardware_profiler", boom, raising=False)
        monkeypatch.setattr(
            "core.hardware_compute_profiler.get_hardware_profiler",
            boom,
            raising=False,
        )
        snap = await mod.get_catalog()
        assert snap["gpu_fit"] == {}
        assert snap["tier_fit"], "探测失败时连 tier_fit 这个键都没有 —— 面板只能自己猜"
        for key, state in snap["tier_fit"].items():
            assert state["fit"] == "unknown", f"{key} 档在探测失败时被判成了 {state['fit']}"
            assert state["reason"], f"{key} 档说 unknown 却不说为什么"


def _code_only(path: Path) -> str:
    """去掉注释的 TS 源码。

    **必须比对去掉注释后的代码。** 这个文件里的说明注释会大量提到档位名和端点
    路径,直接在整份文件里搜的话,测的是「文件里有没有提到这个名字」,而要测的是
    「还有没有代码在用它」。这个仓库为同样的写法栽过两次。
    """
    src = path.read_text(encoding="utf-8")
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"^\s*//.*$", "", src, flags=re.M)


class TestThePanelDoesNotKeepItsOwnCopyOfTheTierTable:
    def test_no_tier_label_is_hardcoded_in_the_panel(self):
        """档位的名字/描述只能来自 ``/api/v1/models/catalog``。

        面板里写死一份的话,目录改了型号、加了一档,面板还在显示旧的那份 ——
        而且不报错。这正是「看起来接上了,其实没有」。
        """
        labels = [t.label for t in all_tiers() if getattr(t, "label", "")]
        assert labels, "目录里一个带标签的档都没有?这条测试就成了空转"
        offenders = {}
        for path in PANEL_SRC.rglob("*.ts"):
            code = _code_only(path)
            hit = [ln for ln in labels if ln in code]
            if hit:
                offenders[path.name] = hit
        assert not offenders, f"面板代码里写死了档位标签: {offenders} —— 档位表只能在后端一处"

    def test_the_model_tags_are_not_hardcoded_either(self):
        tags = {m for t in all_tiers() for m in getattr(t, "active_tags", []) or []}
        offenders = {}
        for path in PANEL_SRC.rglob("*.ts"):
            code = _code_only(path)
            hit = [t for t in tags if t and t in code]
            if hit:
                offenders[path.name] = hit
        assert not offenders, f"面板代码里写死了型号名: {offenders}"


class TestTheBuiltPanelActuallyCallsTheTierEndpoints:
    """产物里必须真的有那两个端点。

    源码接上了、产物没重新构建,是这条路上最容易发生也最难看出来的一种断线:
    dist/ 是提交进仓库的、Electron 直接加载它,而它可以整整落后好几轮改动 ——
    界面照常打开,只是那一行什么都不做。
    """

    @pytest.fixture(scope="class")
    def bundle(self) -> str:
        js = sorted(PANEL_DIST.glob("assets/*.js"))
        if not js:
            pytest.fail(
                "dist/assets 下一个 js 都没有。dist/ 必须提交进仓库 —— "
                "修法: cd electron/renderer/panel && npm ci && npm run build"
            )
        return "\n".join(p.read_text(encoding="utf-8") for p in js)

    @pytest.mark.parametrize("endpoint", ["/api/v1/models/catalog", "/api/v1/models/tier"])
    def test_the_endpoint_is_in_the_built_bundle(self, bundle: str, endpoint: str):
        assert endpoint in bundle, (
            f"构建产物里没有 {endpoint} —— 源码接上了但 dist/ 没跟着重建," "界面上那一行会照常画出来、什么都不做"
        )

    def test_the_tier_row_is_in_the_built_bundle(self, bundle: str):
        assert "tier-stages" in bundle, "构建产物里没有档位那一排牌子"
        assert "本机模型" in bundle, "构建产物里没有档位那一行的抬头"
