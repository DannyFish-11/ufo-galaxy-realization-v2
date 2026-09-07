"""整档开关必须**真的接在配置键上**。

面板设置浮层里那四个开关(全模态 / 跨设备 / 声音 / 自主)不是四个配置键,是四**档**:
一档管一个 category 里的几十个键,开合由这一档的**主键**说了算。

这套东西之前是假的:四档连同 keyCount 全写死在面板的 seedDemo() 里,点一下只翻
一个本地变量、不发任何请求。开关看着能动,后端什么都不知道 —— 正是这个仓库反复
要躲的那类「看起来接上了,其实没有」。

现在定义在 core/routes/config_bundles.py 的 ``CONFIG_BUNDLES``(唯一定义处),
由 ``GET /api/config/bundles`` 现算、``POST`` 写回。这个文件守四件事:

1. 每一档的主键**真的存在**于 CONFIG_SCHEMA —— 否则那是个永远点不动的开关;
2. 每一档的 category **真的有键** —— 否则「管 0 个键」;
3. 数字是**数出来的**,不是写死的;
4. **三档的那一档不许被压成布尔** —— GALAXY_AUTONOMY 是 safe/guided/autonomous,
   压成开关会把中间那档吞掉。这个仓库为同类问题栽过一次。
"""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

import pytest

from core.routes.config import _bundle_state
from core.routes.config_bundles import CONFIG_BUNDLES, owned_keys
from core.routes.config_schema_registry import CONFIG_SCHEMA


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
    def test_key_count_is_what_this_bundle_actually_owns(self, bundle: dict) -> None:
        """「管几个键」数的是 ``owns``,不是 ``category``。

        此前数的是 category —— 而「自主」按 owns 只管 5 个键,category == "agent"
        有 59 个。那 54 个差额里包括 ``GALAXY_MODEL_TIER`` 这种跟"要不要问过再做"
        毫无关系的键。
        """
        state = _bundle_state(bundle)
        assert state["key_count"] == len(owned_keys(bundle, CONFIG_SCHEMA.keys()))

    def test_overrides_counts_only_keys_that_differ_from_default(self, monkeypatch) -> None:
        """``overrides`` 是「这一档管的键里,有几个被**绕过面板**改得偏离了默认」。

        它是这套设计能不能成立的关键:有键被手改过时档位要显示成「有 N 项手改过」
        而不是干净的「开」—— 否则档位说开、底下某个键说关,同一个事实两处各存一份,
        而且没人看得见。
        """
        bundle = CONFIG_BUNDLES[0]
        owned = owned_keys(bundle, CONFIG_SCHEMA.keys())
        victim = next(k for k in owned if k != bundle["primary"] and CONFIG_SCHEMA[k]["default"] not in ("", None))

        monkeypatch.delenv(victim, raising=False)
        base = _bundle_state(bundle)["overrides"]

        # 设成与默认**相同**的值 —— 不算偏离
        monkeypatch.setenv(victim, str(CONFIG_SCHEMA[victim]["default"]))
        assert _bundle_state(bundle)["overrides"] == base, "值与默认相同却被算成了偏离"

        # 设成不同的值 —— 算偏离
        monkeypatch.setenv(victim, str(CONFIG_SCHEMA[victim]["default"]) + "__changed")
        assert _bundle_state(bundle)["overrides"] == base + 1, "手改过的键没有被算进偏离"

    def test_using_this_bundles_own_switch_is_not_a_manual_override(self, monkeypatch) -> None:
        """用这一档自己的开关把值调离默认,**不是**"手改过"。

        真跑实测(Chromium 点面板上「自主」那一行):从 guided 点到 autonomous,
        那一行当场变成「有 2 项手改过」—— 用自己的开关改一下,就被自己记了一笔。
        主键就是这个开关,它偏离默认正是这个开关存在的意义。
        """
        bundle = next(b for b in CONFIG_BUNDLES if b["key"] == "autonomy")
        primary = bundle["primary"]
        for k in owned_keys(bundle, CONFIG_SCHEMA.keys()):
            monkeypatch.delenv(k, raising=False)
        base = _bundle_state(bundle)["overrides"]

        monkeypatch.setenv(primary, "autonomous")
        assert _bundle_state(bundle)["value"] == "autonomous", "开关没拨过去"
        assert (
            _bundle_state(bundle)["overrides"] == base
        ), f"用「{bundle['name']}」自己的开关把 {primary} 调离默认,被算成了「手改过」"

    def test_a_key_that_merely_shares_the_category_is_not_counted(self, monkeypatch) -> None:
        """只是碰巧同 ``category``、不在这一档 ``owns`` 里的键,不算这一档的偏离。

        真跑实测:面板第五行 ABCD 写的 ``GALAXY_MODEL_TIER``(category=agent)
        被算进了「自主」的「有 1 项手改过」—— 用户点的是档位钮,面板却说他手改了。
        """
        bundle = next(b for b in CONFIG_BUNDLES if b["key"] == "autonomy")
        owned = set(owned_keys(bundle, CONFIG_SCHEMA.keys()))
        outsider = next(
            k for k, m in CONFIG_SCHEMA.items() if m.get("category") == bundle["category"] and k not in owned
        )
        for k in owned:
            monkeypatch.delenv(k, raising=False)
        base = _bundle_state(bundle)["overrides"]

        monkeypatch.setenv(outsider, str(CONFIG_SCHEMA[outsider]["default"]) + "__changed")
        assert (
            _bundle_state(bundle)["overrides"] == base
        ), f"{outsider} 只是和「{bundle['name']}」同类,并不归它管,却被算进了它的偏离"


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


class TestABundleActuallyOwnsWhatItClaimsToOwn:
    """一档说自己管什么,那些键就必须真的在它那一类里。

    这条是这次分类归口留下的门。归口之前的实况:

    * 「跨设备」那一档管 ``devices``,而主脑的总线(``GALAXY_NATS_*``)在
      ``network``、主脑自己的两个旋钮在 ``advanced``。于是设置页上,总开关
      ``GALAXY_MASTER_BRAIN_ENABLED``(描述里明写「启用主脑编排 + worker/NATS
      分布式」)在「设备与跨设备」那一格,它的总线在「网络与端口」那一格,
      它的状态文件在「进阶与调优」那一格 —— 一件事被拆到三处,而三处都不说
      对方存在。
    * WebRTC 数据通道同理:关掉它失去的是**手机那端**的摄像头与麦克风,
      配套的 TURN 与信令超时却和它一起待在 ``network``。

    这类错法不会报错,只会让人在设置页上找不到东西 —— 或者更糟,改了一半。

    ``owns`` 把「这一档管哪些机件」从注释里的说法变成**可证伪的声明**:

    1. 声明里的每条模式都必须真的命中键(命中不到 = 声明在静默缩小,
       与手写清单漏一项是同一种失效);
    2. 命中的每个键都必须真的在这一档的 category 里。

    第 2 条也是**反向**的保护:想把一个键挪出去,得先把它从 owns 里划掉 ——
    也就是得先把「这一档不管它了」这句话写下来。
    """

    @pytest.mark.parametrize("bundle", CONFIG_BUNDLES, ids=lambda b: b["key"])
    def test_every_claim_matches_at_least_one_key(self, bundle: dict) -> None:
        dead = [p for p in bundle["owns"] if not fnmatch.filter(CONFIG_SCHEMA.keys(), p)]
        assert not dead, (
            f"档位「{bundle['name']}」声称管着这些机件,而 CONFIG_SCHEMA 里一个都没有: {dead} —— "
            "键改了名的话,这条声明会静默失效,而不是报错"
        )

    @pytest.mark.parametrize("bundle", CONFIG_BUNDLES, ids=lambda b: b["key"])
    def test_everything_it_claims_is_in_its_category(self, bundle: dict) -> None:
        stray = {}
        for pattern in bundle["owns"]:
            for key in fnmatch.filter(CONFIG_SCHEMA.keys(), pattern):
                cat = CONFIG_SCHEMA[key].get("category")
                if cat != bundle["category"]:
                    stray[key] = cat
        assert not stray, (
            f"档位「{bundle['name']}」管 {bundle['category']},却声称管着这些落在别处的键: {stray} —— "
            "设置页按 category 分组,这些键会出现在另一格里,"
            "总开关和它的旋钮就被拆到了两个地方"
        )

    def test_no_key_is_claimed_by_two_bundles(self) -> None:
        """一个键不许被两档同时声称管着 —— 那样「谁说了算」就没有答案。"""
        owner: dict[str, str] = {}
        clashes = {}
        for bundle in CONFIG_BUNDLES:
            for pattern in bundle["owns"]:
                for key in fnmatch.filter(CONFIG_SCHEMA.keys(), pattern):
                    if key in owner and owner[key] != bundle["key"]:
                        clashes[key] = (owner[key], bundle["key"])
                    owner[key] = bundle["key"]
        assert not clashes, f"这些键被两档同时声称管着: {clashes}"

    @pytest.mark.parametrize("bundle", CONFIG_BUNDLES, ids=lambda b: b["key"])
    def test_the_primary_is_among_what_it_claims(self, bundle: dict) -> None:
        """主键必须在自己的声明里 —— 一档连自己那个开关都不声称管,说不过去。"""
        assert any(
            fnmatch.fnmatchcase(bundle["primary"], p) for p in bundle["owns"]
        ), f"档位「{bundle['name']}」的 owns 里没有它自己的主键 {bundle['primary']}"


class TestASubtitleIsOptionalButTheTraceIsNot:
    """副标题可以不要;**留痕不能跟着一起没**。

    「声字同文」的名字已经把这一档管什么说完了,「自主」右边那枚牌子已经把当前档
    写出来了 —— 这两行都不需要副标题。但 ``overrides`` / ``unwired`` 那两句是
    留痕,它们此前是拼在副标题后面的(``${b.note} · 有 N 项手改过``):副标题一空,
    拼出来就成了以「 · 」开头的半句话。
    """

    PANEL_SRC = Path(__file__).resolve().parent.parent / "electron/renderer/panel/src"
    PANEL_DIST = Path(__file__).resolve().parent.parent / "electron/renderer/panel/dist"

    def test_an_empty_note_is_allowed(self) -> None:
        empty = [b["name"] for b in CONFIG_BUNDLES if not b["note"]]
        assert empty, "一档没有空副标题?那这份判据钉的是不存在的情况"

    def test_the_trace_is_not_glued_onto_the_subtitle(self) -> None:
        src = (self.PANEL_SRC / "ui" / "dock.ts").read_text(encoding="utf-8")
        assert (
            "`${b.note} · 有 ${b.overrides} 项手改过`" not in src
        ), "留痕又被拼回副标题后面了 —— 副标题为空时会打出以「 · 」开头的半句话"
        assert "note.hidden" in src, "空副标题的 note 元素没藏起来,会给行凭空撑出一截"

    def test_the_pill_sits_in_the_same_column_as_the_toggles(self) -> None:
        """多态那枚牌子要和上面几行的开关落在同一列。

        ``.knob`` 一直有 ``margin-left:auto``,``.stage`` 没有 —— 于是牌子紧跟在
        文字后面,文字一短就整个往左跑。去掉副标题之后这个错位一眼就能看见
        (实测右边缘 1066.8 vs 开关的 1238.0)。
        """
        css = (self.PANEL_SRC / "styles" / "hud.css").read_text(encoding="utf-8")
        assert ".bundle > .stage" in css and "margin-left: auto" in css, "牌子没有和开关对齐"

    def test_the_abcd_chips_are_not_dragged_right_by_that_rule(self) -> None:
        """对齐规则只能管 bundle 行里的牌子 —— ABCD 那一排是并排的四个。"""
        css = (self.PANEL_SRC / "styles" / "hud.css").read_text(encoding="utf-8")
        assert ".tier-stages > .stage { margin-left: auto" not in css
        assert (
            ".stage {\n  flex: none;\n  margin-left: auto" not in css
        ), "margin-left:auto 写到了 .stage 通用规则上,ABCD 四个钮会被挤到右边"

    def test_the_built_bundle_carries_both(self) -> None:
        js = sorted(self.PANEL_DIST.glob("assets/*.js"))
        assert js, "dist/assets 里没有构建产物"
        blob = "\n".join(f.read_text(encoding="utf-8", errors="replace") for f in js)
        assert ".bundle>.stage{margin-left:auto}" in blob.replace(" ", ""), "dist 里没有对齐规则 —— 改了 src 但没重建"
