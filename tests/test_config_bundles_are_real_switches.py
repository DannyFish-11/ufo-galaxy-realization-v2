"""整档开关必须**真的接在配置键上**。

面板设置浮层里那四个开关(全模态 / 跨设备 / 声音 / 自主)不是四个配置键,是四**档**:
一档管一个 category 里的几十个键,开合由这一档的**主键**说了算。

这套东西之前是假的:四档连同 keyCount 全写死在面板的 seedDemo() 里,点一下只翻
一个本地变量、不发任何请求。开关看着能动,后端什么都不知道 —— 正是这个仓库反复
要躲的那类「看起来接上了,其实没有」。

现在定义在 core/routes/config_schema_registry.py 的 ``CONFIG_BUNDLES``(唯一定义处),
由 ``GET /api/config/bundles`` 现算、``POST`` 写回。这个文件守四件事:

1. 每一档的主键**真的存在**于 CONFIG_SCHEMA —— 否则那是个永远点不动的开关;
2. 每一档的 category **真的有键** —— 否则「管 0 个键」;
3. 数字是**数出来的**,不是写死的;
4. **三档的那一档不许被压成布尔** —— GALAXY_AUTONOMY 是 safe/guided/autonomous,
   压成开关会把中间那档吞掉。这个仓库为同类问题栽过一次。
"""

from __future__ import annotations

import os

import pytest

from core.routes.config import _bundle_state
from core.routes.config_schema_registry import CONFIG_BUNDLES, CONFIG_SCHEMA


class TestEveryBundleIsWiredToSomethingReal:
    @pytest.mark.parametrize("bundle", CONFIG_BUNDLES, ids=lambda b: b["key"])
    def test_primary_key_exists(self, bundle: dict) -> None:
        """主键不在 CONFIG_SCHEMA 里 = 这一档接到了一个不存在的东西上。"""
        assert bundle["primary"] in CONFIG_SCHEMA, (
            f"档位「{bundle['name']}」的主键 {bundle['primary']} 不在 CONFIG_SCHEMA 里 —— "
            "面板上会出现一个永远关着、点了也没反应的开关"
        )

    @pytest.mark.parametrize("bundle", CONFIG_BUNDLES, ids=lambda b: b["key"])
    def test_the_category_actually_has_keys(self, bundle: dict) -> None:
        """一档管 0 个键的话,「整档开关」这个说法就不成立。"""
        n = sum(1 for m in CONFIG_SCHEMA.values() if m.get("category") == bundle["category"])
        assert n > 0, f"档位「{bundle['name']}」的 category {bundle['category']!r} 下一个键都没有"

    @pytest.mark.parametrize("bundle", CONFIG_BUNDLES, ids=lambda b: b["key"])
    def test_the_primary_belongs_to_the_category_it_governs(self, bundle: dict) -> None:
        """主键得在它自己管的那一类里,否则「这一档」到底是哪一档就说不清了。"""
        meta = CONFIG_SCHEMA[bundle["primary"]]
        assert meta["category"] == bundle["category"], (
            f"档位「{bundle['name']}」管 {bundle['category']}," f"主键 {bundle['primary']} 却属于 {meta['category']}"
        )

    def test_bundle_keys_are_unique(self) -> None:
        keys = [b["key"] for b in CONFIG_BUNDLES]
        assert len(keys) == len(set(keys)), f"档位 key 有重复: {keys}"


class TestTheNumbersAreCounted:
    """数字必须是数出来的。写死的数字第一天是对的,第二天就开始骗人。"""

    @pytest.mark.parametrize("bundle", CONFIG_BUNDLES, ids=lambda b: b["key"])
    def test_key_count_matches_the_schema(self, bundle: dict) -> None:
        state = _bundle_state(bundle)
        expected = sum(1 for m in CONFIG_SCHEMA.values() if m.get("category") == bundle["category"])
        assert state["key_count"] == expected

    def test_overrides_counts_only_keys_that_differ_from_default(self, monkeypatch) -> None:
        """``overrides`` 是「有几个键被手动改得偏离了默认」。

        它是这套设计能不能成立的关键:有键被手改过时档位要显示成「有 N 项手改过」
        而不是干净的「开」—— 否则档位说开、底下某个键说关,同一个事实两处各存一份,
        而且没人看得见。
        """
        bundle = CONFIG_BUNDLES[0]
        category = bundle["category"]
        victim = next(
            k for k, m in CONFIG_SCHEMA.items() if m.get("category") == category and m["default"] not in ("", None)
        )

        monkeypatch.delenv(victim, raising=False)
        base = _bundle_state(bundle)["overrides"]

        # 设成与默认**相同**的值 —— 不算偏离
        monkeypatch.setenv(victim, str(CONFIG_SCHEMA[victim]["default"]))
        assert _bundle_state(bundle)["overrides"] == base, "值与默认相同却被算成了偏离"

        # 设成不同的值 —— 算偏离
        monkeypatch.setenv(victim, str(CONFIG_SCHEMA[victim]["default"]) + "__changed")
        assert _bundle_state(bundle)["overrides"] == base + 1, "手改过的键没有被算进偏离"


class TestAThreeWaySwitchIsNotFlattenedIntoABoolean:
    """三档不许被压成两态。

    ``GALAXY_AUTONOMY`` 是 safe / guided / autonomous。压成推拉开关会把中间那档
    吞掉,而 guided(读放行、写审批)恰恰是默认值 —— 也就是说压扁之后,用户最常处
    的那一档在界面上根本表达不出来。
    """

    def test_autonomy_is_still_a_select(self) -> None:
        meta = CONFIG_SCHEMA["GALAXY_AUTONOMY"]
        assert meta["type"] == "select", "GALAXY_AUTONOMY 不再是 select 了?那面板那侧的三档渲染要跟着改"
        assert len(meta.get("options", [])) >= 3

    def test_the_bundle_carries_the_options_through(self) -> None:
        """后端必须把档位选项原样透出,面板才画得出三档。"""
        bundle = next(b for b in CONFIG_BUNDLES if b["primary"] == "GALAXY_AUTONOMY")
        state = _bundle_state(bundle)
        assert state["type"] == "select"
        assert state.get("options"), "select 型档位没有透出 options —— 面板只能猜,或者压成布尔"

    def test_no_bundle_state_reports_a_bare_on_off_field(self) -> None:
        """状态里不许出现 ``on`` 这种布尔字段。

        它一出现,三档就必然在某处被压成两态 —— 面板旧版正是这么写的(``on: boolean``)。
        值一律用主键的原始字符串透出,由渲染那侧按 type 决定画什么控件。
        """
        for bundle in CONFIG_BUNDLES:
            state = _bundle_state(bundle)
            assert "on" not in state, f"档位 {bundle['key']} 的状态里出现了布尔 on —— 三档会被压扁"
            assert isinstance(state["value"], str)


class TestAMissingPrimaryIsLoudNotSilent:
    def test_an_unwired_bundle_says_so(self) -> None:
        """主键不存在时必须**说出来**。

        静默跳过的话,面板上是一个永远关着、点了也没反应的开关 —— 比报错更难查。
        """
        fake = {
            "key": "ghost",
            "name": "不存在的档",
            "note": "",
            "category": "perception",
            "primary": "GALAXY_THIS_KEY_DOES_NOT_EXIST",
        }
        state = _bundle_state(fake)
        assert state["unwired"] is True
        assert "GALAXY_THIS_KEY_DOES_NOT_EXIST" in state["reason"]


class TestTheDefinitionLivesInExactlyOnePlace:
    def test_the_panel_does_not_keep_its_own_copy(self) -> None:
        """面板不许自己再存一份「哪一档管哪些键」。

        同一个事实两处各存,迟早一处说开、另一处说关,而且没人看得见。面板只渲染
        ``GET /api/config/bundles`` 现算出来的结果。

        **必须比对去掉注释后的代码。** 第一版直接在整份文件里搜主键名,结果被
        types.ts 里那段「GALAXY_AUTONOMY 是三档,压成布尔会吞掉中间那档」的说明
        注释绊倒 —— 那种写法测的是「文件里有没有提到这个名字」,而要测的是
        「还有没有代码在用它」。这个仓库的另一条判据为同样的事栽过一次。
        """
        import re
        from pathlib import Path

        panel_src = Path(__file__).resolve().parent.parent / "electron/renderer/panel/src"
        block_comment = re.compile(r"/\*.*?\*/", re.S)
        line_comment = re.compile(r"^\s*//.*$", re.M)

        skip = {
            "settings_inventory.ts",  # 待建设置面的规格,不是渲染路径
            "main.ts",  # seedDemo 在这里,文件内已注明是演示数据
        }
        for path in panel_src.rglob("*.ts"):
            if path.name in skip:
                continue
            code = line_comment.sub("", block_comment.sub("", path.read_text(encoding="utf-8")))
            for bundle in CONFIG_BUNDLES:
                assert bundle["primary"] not in code, (
                    f"{path.name} 的**代码**里写死了主键 {bundle['primary']} —— "
                    "开合的判据只能在后端 CONFIG_BUNDLES 一处"
                )


def test_every_bundle_state_survives_a_clean_environment(monkeypatch) -> None:
    """所有档位键都不在环境里时,现算也不该炸 —— 那就是第一次启动的样子。"""
    for bundle in CONFIG_BUNDLES:
        monkeypatch.delenv(bundle["primary"], raising=False)
    for bundle in CONFIG_BUNDLES:
        state = _bundle_state(bundle)
        assert state["unwired"] is False
        assert state["value"] == CONFIG_SCHEMA[bundle["primary"]]["default"]
        assert os.environ.get(bundle["primary"]) is None


class TestTheModelTierKeyMatchesTheRealCatalog:
    """``GALAXY_MODEL_TIER`` 的选项必须覆盖目录里真实存在的每一档。

    这条守两件事,都出过:

    1. **描述少说了两档。** 原先写的是「填 A/B 可钉死用哪一档」,而
       core/model_catalog.py 的 _TIERS 里有 A/B/C/D 四档 —— 说明少两档,人就只会
       在两档里挑,而 C 恰恰是当前默认在用的那一档。
    2. **类型是 string 而不是 select。** 设置页据 type 决定控件形态,string 会渲染
       成自由文本框;档位表只认 A/B/C/D,填错的后果是 load_tier() 静默回落到默认档
       —— 用户以为自己钉住了某一档,其实没有。
    """

    def test_it_is_a_select_not_a_free_text_box(self) -> None:
        meta = CONFIG_SCHEMA["GALAXY_MODEL_TIER"]
        assert meta["type"] == "select", "档位是枚举,不能让人自由输入"
        assert "options" in meta, "select 没有 options —— 设置页只能猜"

    def test_every_real_tier_is_offered(self) -> None:
        from core.model_catalog import all_tiers

        offered = set(CONFIG_SCHEMA["GALAXY_MODEL_TIER"]["options"])
        real = {t.key for t in all_tiers()}
        missing = sorted(real - offered)
        assert not missing, (
            f"目录里有这些档,而配置项里选不到: {missing} —— " "人只会在选得到的档里挑,选不到的那档等于不存在"
        )

    def test_no_phantom_tier_is_offered(self) -> None:
        """反向:选项里不许出现目录里没有的档 —— 选了会静默回落。"""
        from core.model_catalog import all_tiers

        offered = {o for o in CONFIG_SCHEMA["GALAXY_MODEL_TIER"]["options"] if o}
        real = {t.key for t in all_tiers()}
        phantom = sorted(offered - real)
        assert not phantom, f"配置项里有目录中不存在的档: {phantom}"

    def test_the_empty_choice_is_offered(self) -> None:
        """「不钉,按能力自动判」是默认值,它必须在选项里表达得出来。"""
        meta = CONFIG_SCHEMA["GALAXY_MODEL_TIER"]
        assert "" in meta["options"], "「不钉死」这个选择在界面上表达不出来"
        assert meta["default"] == "", "默认应当是不钉死"

    def test_the_description_names_every_tier(self) -> None:
        """描述里得把每一档都点到名 —— 少说一档,人就不知道有它。"""
        from core.model_catalog import all_tiers

        desc = CONFIG_SCHEMA["GALAXY_MODEL_TIER"]["description"]
        missing = [t.key for t in all_tiers() if f"{t.key}=" not in desc]
        assert not missing, f"描述里没有点到这些档: {missing}"
