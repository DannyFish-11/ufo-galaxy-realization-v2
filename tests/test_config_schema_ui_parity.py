"""tests/test_config_schema_ui_parity.py
==========================================
真机复现:用户点"保存"填好的 API Key,面板显示"保存失败"。上一轮以为是限流
误伤(已修复),但用户在真机上再次复现——这次找到一个完全独立的根因:

ModelsTab.tsx 在上一轮修复里新增了三行 UI(OpenRouter/DeepSeek OCR/OpenAI 自定义
地址),这三个 key(OPENROUTER_API_KEY / DEEPSEEK_OCR2_API_KEY / OPENAI_API_BASE)
当时只核对过 core/routes/system.py 的 _SECRET_MODEL_KEYS/_NON_SECRET_MODEL_KEYS
(GET /api/config 精简版读接口用的白名单),却没有核对 core/routes/config.py 的
CONFIG_SCHEMA(POST /api/config 写接口用的另一份、完全独立、未同步的白名单)。

后果:core/routes/config.py::update_config() 对 req.config 里任何不在
CONFIG_SCHEMA 里的 key 直接 400——ModelsTab 保存请求只要 changed 里包含这三个
新字段中的任何一个,整个批量保存请求全部失败(哪怕同批里还夹着本来能存的
DEEPSEEK_API_KEY),前端只会显示笼统的"保存失败"。

修复:把这三个 key(以及同样只在 system.py 里出现、不在 CONFIG_SCHEMA 里的
SONAR_API_KEY/VLLM_URL)补进 CONFIG_SCHEMA。

本文件的测试有两层:
1. 结构性回归闸门:直接解析 ModelsTab.tsx/SettingsTab.tsx 源码里引用的每个
   config key,断言它们都在 CONFIG_SCHEMA 里——以后再有人往面板 UI 加一个新
   provider/设置项而忘了同步 CONFIG_SCHEMA,这个测试会先炸,而不是等用户在
   真机上点"保存"才发现。
2. 端到端复现:直接用 TestClient 打 POST /api/config,验证这三个 key 现在
   能保存成功(不再 400)。
"""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
# 旧 React 面板已被这一版 HUD 整个替换。ModelsTab.tsx / SettingsTab.tsx 里那两份
# 手写键清单不是渲染代码而是**判据**,已搬进 panel/src/settings_inventory.ts。
# 注意:那份清单**当前没有任何界面在渲染** —— 它是待建设置面的规格。这道门守的
# 仍是同一件事:清单里的键,后端 CONFIG_SCHEMA 必须认得,否则 POST /api/config 会 400。
SETTINGS_INVENTORY = REPO_ROOT / "electron/renderer/panel/src/settings_inventory.ts"
MODELS_TAB = SETTINGS_INVENTORY
SETTINGS_TAB = SETTINGS_INVENTORY

# PROVIDER_KEYS 是纯字符串数组(旧 ModelsTab 里是 key:/extraKey: 字段)。
_KEY_RE = re.compile(r"""'([A-Z][A-Z0-9_]*)'""")
_SETTINGS_KEY_RE = re.compile(r"""'([A-Z][A-Z0-9_]*)'""")


def _extract_models_tab_keys() -> set[str]:
    src = MODELS_TAB.read_text(encoding="utf-8")
    start = src.index("export const PROVIDER_KEYS")
    end = src.index("\n];", start)
    block = src[start:end]
    body = "\n".join(ln for ln in block.split("\n") if not ln.strip().startswith("//"))
    return set(_KEY_RE.findall(body))


def _extract_settings_tab_keys() -> set[str]:
    """从 SettingsTab.tsx 的 KEY_ORDER_HINT 里提取所有 key 字符串(顺序提示,不再是分组定义)。"""
    src = SETTINGS_TAB.read_text(encoding="utf-8")
    start = src.index("const KEY_ORDER_HINT")
    end = src.index("\n};", start)
    block = src[start:end]
    return set(_SETTINGS_KEY_RE.findall(block))


class TestModelsTabKeysExistInConfigSchema:
    """ModelsTab.tsx 里出现的每一个 provider key,POST /api/config 都必须认得。"""

    def test_every_models_tab_key_is_in_config_schema(self):
        from core.routes.config import CONFIG_SCHEMA

        ui_keys = _extract_models_tab_keys()
        assert ui_keys, "未能从 ModelsTab.tsx 解析出任何 key —— 正则可能需要更新"
        missing = sorted(k for k in ui_keys if k not in CONFIG_SCHEMA)
        assert not missing, (
            f"ModelsTab.tsx 引用了以下 key,但 core/routes/config.py::CONFIG_SCHEMA "
            f'里没有——POST /api/config 会对这些 key 返回 400,导致面板显示"保存失败": '
            f"{missing}"
        )

    def test_regression_openrouter_deepseek_ocr_openai_base_present(self):
        """本次真机复现直接命中的三个 key——显式钉住,防止再次漏同步。"""
        from core.routes.config import CONFIG_SCHEMA

        for key in ("OPENROUTER_API_KEY", "DEEPSEEK_OCR2_API_KEY", "OPENAI_API_BASE"):
            assert key in CONFIG_SCHEMA, f"{key} 缺失于 CONFIG_SCHEMA"


class TestSettingsTabKeysExistInConfigSchema:
    def test_every_settings_tab_key_is_in_config_schema(self):
        from core.routes.config import CONFIG_SCHEMA

        ui_keys = _extract_settings_tab_keys()
        assert ui_keys, "未能从 SettingsTab.tsx 解析出任何 key —— 正则可能需要更新"
        missing = sorted(k for k in ui_keys if k not in CONFIG_SCHEMA)
        assert not missing, f"SettingsTab.tsx 的 KEY_ORDER_HINT 引用了以下 key,但 CONFIG_SCHEMA 里没有: {missing}"


class TestPostConfigEndToEnd:
    """直接打 POST /api/config,复现并验证修复。"""

    def _client(self, tmp_path, monkeypatch):
        import core.config_store as config_store_module
        import core.routes.config as config_module

        # 隔离真实 .env,避免测试写脏仓库根目录的 .env。
        monkeypatch.setattr(config_module, "ENV_FILE", tmp_path / ".env.test")
        # 隔离真实 runtime/secrets.env:此前这里漏了这一步 —— POST /api/config
        # 里凡是分类为 secret 的 key(DEEPSEEK_API_KEY/OPENROUTER_API_KEY/...)会经
        # ConfigService().set_secret() 落到进程级单例 ConfigStore(core/config_store.py
        # 的 get_config_store()),而该单例默认路径就是仓库真实的
        # runtime/secrets.env——测试假密钥(sk-ds-test 等)会真的写进本地这份文件,
        # 污染真实的密钥库状态。改为进程级单例注入一个指向 tmp_path 的 ConfigStore。
        monkeypatch.setattr(
            config_store_module,
            "_singleton",
            config_store_module.ConfigStore(
                config_path=tmp_path / "config.json.test",
                secrets_path=tmp_path / "secrets.env.test",
            ),
        )

        app = FastAPI()
        app.include_router(config_module.router)
        return TestClient(app)

    def test_saving_openrouter_key_no_longer_400s(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        resp = client.post("/api/config", json={"config": {"OPENROUTER_API_KEY": "sk-or-test"}})
        assert resp.status_code == 200, resp.text
        assert resp.json()["success"] is True

    def test_saving_deepseek_ocr_key_no_longer_400s(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        resp = client.post("/api/config", json={"config": {"DEEPSEEK_OCR2_API_KEY": "sk-ocr-test"}})
        assert resp.status_code == 200, resp.text

    def test_saving_openai_api_base_no_longer_400s(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        resp = client.post("/api/config", json={"config": {"OPENAI_API_BASE": "https://proxy.example.com/v1"}})
        assert resp.status_code == 200, resp.text

    def test_batch_save_with_one_previously_unknown_key_no_longer_fails_whole_batch(self, tmp_path, monkeypatch):
        """真实故障模式:同一批里混着一个能存的 key 和一个当时不认识的 key,
        整批 400,连本来能存的那个也存不进去。"""
        client = self._client(tmp_path, monkeypatch)
        resp = client.post(
            "/api/config",
            json={"config": {"DEEPSEEK_API_KEY": "sk-ds-test", "OPENROUTER_API_KEY": "sk-or-test"}},
        )
        assert resp.status_code == 200, resp.text
        assert set(resp.json()["updated"]) == {"DEEPSEEK_API_KEY", "OPENROUTER_API_KEY"}

    def test_truly_unknown_key_still_rejected(self, tmp_path, monkeypatch):
        """确认修复没有把校验整个关掉——真正未知的 key 仍应 400。"""
        client = self._client(tmp_path, monkeypatch)
        resp = client.post("/api/config", json={"config": {"TOTALLY_MADE_UP_KEY_XYZ": "x"}})
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════
# 反方向:CONFIG_SCHEMA → 面板
# ═══════════════════════════════════════════════════════════════════════════


class TestEverySchemaKeyIsReachableOrDeclaredAnAlias:
    """上面那一层查的是 **面板 → CONFIG_SCHEMA**(面板引用的键必须登记过)。
    这一层查**反方向**,而缺的一直是这个方向。

    没有它会发生什么(实际发生过)
    ----------------------------
    2026-08-29 盘点时,331 个配置项里有 8 个既不在面板上、也没被说明为什么不在。
    逐条查完是三种完全不同的东西:

    * **3 个是真别名**(``GEMINI_API_KEY`` / ``DASHSCOPE_API_KEY`` /
      ``SONAR_API_KEY``)—— 它们在 ``PROVIDER_REGISTRY`` 的 ``alt_env`` 里声明过,
      规范键已经在面板上。给别名再开一个输入框,等于同一个设置有两个框,
      填哪个都对但看起来像两件事。**不在面板上是对的。**
    * **4 个是真缺口**(``GALAXY_REASONING_OPENAI_*``)—— 推理位/独显那条泳道,
      ``multi_llm_router._LOCAL_OPENAI_LANES`` 早就按 env_prefix 认它们了,
      只是面板上没有地方填。感知位那台能在界面里配、推理位那台只能改 .env,
      而双模型档本来就是两台一起用。**已补。**
    * **1 个是死键**(``VLLM_URL``)—— 登记着、在明文回显白名单里、描述说是
      ``LOCAL_VLLM_URL`` 的别名,但**代码里零读取**。设了等于没设,而界面上
      看起来是可配的。这比"配不了"更糟:它谎称自己有用。**已删。**

    这三种混在一起时,盘点结果只是"8 个配不了",看不出哪个该补、哪个该删、
    哪个本来就该缺。这条判据把它们分开。

    别名从哪儿来
    ------------
    ``PROVIDER_REGISTRY[*].alt_env`` —— **不在这里另攒一份别名表**。另攒一份的
    表现是:registry 里加一个别名,这道门当场红,然后有人把它加进本地清单里
    "修好",于是两份清单开始各自漂移。
    """

    @staticmethod
    def _alias_keys() -> set[str]:
        from core.multi_llm_router import PROVIDER_REGISTRY

        return {alias for spec in PROVIDER_REGISTRY for alias in (spec.get("alt_env") or [])}

    @staticmethod
    def _reachable_keys() -> set[str]:
        """在设置面的**规格**里有归宿的键。

        .. warning::

           **这个方法名现在名不副实,而这是刻意留着的。**

           旧 React 面板整个被 HUD 面板替换之后,设置页还没重建 —— 新面板的设置
           浮层只有四个整档开关,「全部设置」按钮还没接东西。所以此刻严格来说
           **没有任何键在界面上够得着**。

           把这条判据改成按新面板的实际渲染来算,它会为全部 300 多个键报红,
           三周内必被关掉或加白名单绕过 —— 那正是下面这段历史注释警告过的事。
           把它改成继续返回「够得着」,又是在说谎:清单在,界面不在。

           折中是**改口径不改严格度**:这里查的是「每个 schema 键在规格里有没有
           归宿」。设置面建起来之后,把这里连同 :data:`SETTINGS_INVENTORY` 一起
           改回按真实渲染算,并把这段说明删掉。

        以下是口径变更前的原始说明,仍然适用于「归宿」这层含义:

        **这个定义在 2026-08-30 变过。** 从前是"键名在面板源码里出现过" —— 那时
        SettingsTab 用一份手工的 CONFIG_KEYS 决定谁出现,所以"出现在源码里"确实
        等价于"够得着"。

        现在分组由 /api/config/all 返回的 category 现算,一个键完全可以够得着却
        不出现在任何 .tsx 里。继续按旧定义查的话,哪天有人精简那份顺序提示,这条
        判据就会为一批**其实够得着**的键报红 —— 一条会误报的判据,三周内一定会被
        关掉或者被随手加白名单绕过。

        新定义:
          · category 在 CATEGORIES 里有装饰   → 现算时会分到设置页上,够得着;
          · 键名直接出现在面板源码里 → 够得着。这一条覆盖被委派出去的分类
            (llm 那批在 ModelsTab 里逐条列着),以及被组件直接引用的键
            (如 ModelsTab 的 extraKey)—— 它们不走分类那条路。

        「委派是不是一句空话」由 test_voice_switches_reach_the_panel.py 那边单独查
        (声称委派给 ModelsTab 的键,必须真的在 ModelsTab 里找得到)。
        """
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        src_dir = REPO_ROOT / "electron/renderer/panel/src"
        panel_src = "\n".join(p.read_text(encoding="utf-8") for p in src_dir.rglob("*.ts*"))
        settings_src = SETTINGS_INVENTORY.read_text(encoding="utf-8")

        def _block(start_marker: str, end_marker: str) -> str:
            i = settings_src.index(start_marker)
            return settings_src[i : settings_src.index(end_marker, i)]

        decorated = set(re.findall(r"key:\s*'([a-z_]+)'", _block("const CATEGORIES", "\n];")))

        out: set[str] = set()
        for k, meta in CONFIG_SCHEMA.items():
            if meta.get("category") in decorated:
                out.add(k)
            elif re.search(r"['\"]" + re.escape(k) + r"['\"]", panel_src):
                out.add(k)
        return out

    def test_no_schema_key_is_silently_unreachable(self):
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        unaccounted = sorted(set(CONFIG_SCHEMA) - self._reachable_keys() - self._alias_keys())
        assert not unaccounted, (
            "这些配置项既不在面板上、也不是 PROVIDER_REGISTRY 声明的别名 —— "
            "用户改不了它们,而 CONFIG_SCHEMA 让它们看起来是可配的。"
            "该补面板就补,该删就删(零读取的死键),是别名就在 alt_env 里声明:"
            f"{unaccounted}"
        )

    def test_the_declared_aliases_are_actually_read(self):
        """别名之所以可以不上面板,前提是**它真的被读**。

        一个既不上面板、又没人读的键,挂着 alt_env 的名义就成了合法的死键 ——
        那正好绕过了上面那条判据。
        """
        import subprocess

        for alias in sorted(self._alias_keys()):
            hits = subprocess.run(
                ["grep", "-rl", alias, "--include=*.py", "core/", "galaxy_gateway/"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
            ).stdout.strip()
            assert hits, f"{alias} 声明为别名但代码里没有任何一处提到它"

    def test_the_reasoning_lane_is_configurable_from_the_panel(self):
        """回归:推理位那条泳道曾经只能改 .env。

        钉住四个键而不是"至少一个" —— 少一个 SERVES,槽位解析就说不出这台服务
        伺候的是目录里哪个型号。
        """
        panel = self._reachable_keys()
        for key in (
            "GALAXY_REASONING_OPENAI_URL",
            "GALAXY_REASONING_OPENAI_MODEL",
            "GALAXY_REASONING_OPENAI_SERVES",
            "GALAXY_REASONING_OPENAI_KEY",
        ):
            assert key in panel, f"{key} 不在面板上 —— 推理位那台服务又只能改 .env 了"

    def test_the_dead_key_stays_dead(self):
        """回归:``VLLM_URL`` 零读取,已从 CONFIG_SCHEMA 删除。

        ``LOCAL_VLLM_URL`` 是真的那个,留着。这条挡的是"看着像少了个别名,顺手补回去"。
        """
        from core.routes.config import _NON_SECRET_MODEL_KEYS
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        assert "VLLM_URL" not in CONFIG_SCHEMA
        assert "VLLM_URL" not in _NON_SECRET_MODEL_KEYS
        assert "LOCAL_VLLM_URL" in CONFIG_SCHEMA


def _extract_hint_groups() -> dict[str, list[str]]:
    """``{分组名: [键, ...]}`` —— 分组名就是设置页拿去查表的那个 category。"""
    src = SETTINGS_TAB.read_text(encoding="utf-8")
    start = src.index("export const KEY_ORDER_HINT")
    block = src[start : src.index("\n};", start)]
    parts = re.split(r"\n  ([a-z_]+): \[", block)[1:]
    out: dict[str, list[str]] = {}
    for name, body in zip(parts[0::2], parts[1::2]):
        body = "\n".join(ln for ln in body.split("\n") if not ln.strip().startswith("//"))
        out[name] = _SETTINGS_KEY_RE.findall(body)
    return out


class TestTheOrderHintIsLookedUpByARealCategory:
    """顺序提示的**分组名**必须是后端真会返回的 category。

    设置页是 ``KEY_ORDER_HINT[item.category]`` 这样查的:分组名对不上,查出来就是
    ``undefined``,那一类默默按字母序排 —— 不报错,不留痕,只是这份表白写了。

    实况(2026-09-03 修):九个分组名里有八个是**更早一版**的后端分类
    (behavior / ports / auth / mesh / circuit / storage / dev / slo)。后端早改成了
    voice / perception / agent / … 这九类,只有 ``network`` 这个名字碰巧还对得上。
    也就是说 303 个键里有 291 个的顺序提示从来没有生效过,而两边都不报错。

    这正是本仓要躲的那类失效:**接口还在、调用还在、什么都没发生。**

    第二条(成员关系)同样重要:分组名对了、键列错了类,那个键仍然查不到自己的
    顺序 —— 表面上「它在表里」,实际还是字母序。
    """

    def test_every_group_name_is_a_real_category(self):
        from core.routes.config import CONFIG_SCHEMA

        real = {m.get("category", "") for m in CONFIG_SCHEMA.values()}
        bogus = sorted(set(_extract_hint_groups()) - real)
        assert not bogus, (
            f"KEY_ORDER_HINT 里这些分组名不是后端真会返回的 category: {bogus} —— "
            f"设置页查不到它们,那几类会默默按字母序排。真有的是: {sorted(real)}"
        )

    def test_every_key_is_listed_under_its_own_category(self):
        from core.routes.config import CONFIG_SCHEMA

        misfiled = {}
        for group, keys in _extract_hint_groups().items():
            for key in keys:
                meta = CONFIG_SCHEMA.get(key)
                if meta is None:
                    continue  # 由 TestSettingsTabKeysExistInConfigSchema 管
                if meta.get("category") != group:
                    misfiled[key] = (group, meta.get("category"))
        shown = dict(list(misfiled.items())[:20])
        assert not misfiled, (
            f"{len(misfiled)} 个键被列在了别的分类下面(列出的是 列在哪 → 实际属于哪,"
            f"只展示前 20 个): {shown} —— 设置页按实际 category 查表,查不到就还是字母序"
        )
