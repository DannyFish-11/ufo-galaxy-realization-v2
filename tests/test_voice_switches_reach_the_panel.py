"""语音栈的每个配置开关都必须真的出现在面板上。

被修的问题
----------
「边说边听」这几轮做的功能(回声消除 AEC、自回声文字闸门、应答不打断、系统播放声
采集、全双工、压音)全部只由环境变量控制,而那些环境变量**两边都没登记**:

* 后端 ``core/routes/config.py::CONFIG_SCHEMA`` 里没有 → ``GET /api/config/all``
  不返回它,面板即使列出了也只能渲染成「未从后端加载」;
* 面板前端 ``SettingsTab.tsx::CONFIG_KEYS`` 里没有 → 设置页上根本没有它的位置。

而且 ``update_config()`` 会把不在 ``CONFIG_SCHEMA`` 里的 key 当 ``unknown_keys``
直接 400。所以这些开关的真实状态是:**功能在跑,但用户只能手改 .env 或导出环境
变量才能开关它**,在面板上完全不存在。功能做了却没接到用户能操作的地方。

为什么已有的 parity 测试没拦住
------------------------------
``tests/test_config_schema_ui_parity.py`` 守的是**前端 ⊆ 后端**:面板 UI 引用的 key
必须在 ``CONFIG_SCHEMA`` 里。它防的是「UI 加了字段但后端不认 → 保存 400」。

但本次的漏法是**反方向**:代码里读了一个配置键,而**两边都没登记**。前端没列出它,
所以前端那份集合里根本不含它,``前端 ⊆ 后端`` 天然成立 —— 那个测试没有任何东西
可炸。这个文件补的就是 **代码 → 面板** 这个方向。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parent.parent
SETTINGS_TAB = REPO_ROOT / "electron/renderer/panel/src/components/SettingsTab.tsx"

#: 语音栈里所有会读配置的模块。新增语音模块时加进来。
_VOICE_MODULES = (
    "core/voice_duplex_session.py",
    "core/voice_dialog_policy.py",
    "core/voice_echo_guard.py",
    "core/multimodal/acoustic_echo_canceller.py",
    "core/multimodal/system_audio_capture_service.py",
    "core/multimodal/system_audio_ingest.py",
    "core/multimodal/audio_ingest.py",
    # 2026-07-30 补入。这份清单是**手工维护**的,而它一旦漏掉某个模块,那个模块里的
    # 配置键就静默地不受本守卫保护 —— 正是这么漏掉了 5 个键:
    #   GALAXY_MINICPM_SERVER_URL(B 档本地全模态 server 的地址,整条原生链路的入口)
    #   GALAXY_NATIVE_MODAL_AUTO(切 B 档是否自动激活)
    #   GALAXY_AMBIENT_ASR_SIZE / GALAXY_VIDEO_FPS_NATIVE / GALAXY_VIDEO_FPS_BRIDGE
    # 它们两边都没登记,功能在跑但用户只能手改 .env —— 与本文件当初要防的那 21 个语音
    # 开关是同一类缺口,只是换了个模块藏身。
    "core/native_modal.py",
    "core/modality_bridge.py",
    "core/modality_capability.py",
)

#: 明确豁免:**不该出现在面板上**的键,连同理由。
#:
#: 与"暂时不登记"不同 —— 这些是部署环境标记,不是用户设置项,登上面板反而是错的。
#: 写成显式集合而非静默跳过:任何人要加豁免都得在这里写下理由。
_NOT_USER_SETTINGS = {
    # 测试期标记。core/native_modal.py 用它(连同 PYTEST_CURRENT_TEST)禁止 save_tier('B')
    # 的单测触发真实后台 pip 安装。由运行环境设置,不是用户在面板上调的东西。
    "GALAXY_ENV",
}

#: 只匹配**真正的读取调用**,不匹配 docstring / 日志文案里对变量名的提及。
#: 这些模块的 docstring 和 warning 文案里大量出现 "GALAXY_VOICE_ECHO_GUARD=0 复核"
#: 这类字样,按裸变量名扫会扫出一堆并非配置读取点的假阳性。
_CONFIG_READ_RE = re.compile(r"""(?:os\.getenv|os\.environ\.get|_flag|_num)\(\s*["'](GALAXY_[A-Z0-9_]+)["']""")

#: 曾经有一个豁免集合放在这里,里面是 ``GALAXY_REALTIME_API_KEY``。
#:
#: 当时的理由是:``core/routes/config.py`` 里有一份 ``_SECRET_MODEL_KEYS``,我以为
#: **不在那份名单里的键会被明文写进 .env**,所以在密钥路由做好之前不敢登记它。
#:
#: **那个前提是错的。** 决定写入分流的是 ``core/config_schema.py::classify_key()``,
#: 它按后缀启发式判定 —— 凡以 ``_API_KEY``/``_TOKEN``/``_SECRET``/``_PASSWORD`` 结尾
#: 的一律归为 ``"secret"``,而 ``update_config()`` 对 secret 走
#: ``ConfigService.set_secret()`` → ``runtime/secrets.env``。``_SECRET_MODEL_KEYS``
#: 只决定面板「模型」tab 的"已配置"角标读哪些键,与写入分流无关。
#:
#: 所以现在没有豁免项:那把 key 已正常登记,而"它确实走加密存储"由
#: ``TestRealtimeKeyRoutesToSecretStore`` 直接断言 ``classify_key`` 的结果来守。
_PENDING_SECRET_ROUTING: frozenset = frozenset()


def _extract_config_reads() -> dict[str, list[str]]:
    """返回 ``{配置键: [读它的模块, ...]}``。"""
    found: dict[str, list[str]] = {}
    for rel in _VOICE_MODULES:
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        for key in _CONFIG_READ_RE.findall(path.read_text(encoding="utf-8")):
            found.setdefault(key, []).append(rel)
    return found


def _extract_settings_tab_keys() -> set[str]:
    """从 SettingsTab.tsx 的 CONFIG_KEYS 字典字面量里取出所有 key。"""
    src = SETTINGS_TAB.read_text(encoding="utf-8")
    start = src.index("const CONFIG_KEYS")
    end = src.index("\n};", start)
    block = src[start:end]
    # 去掉注释行:注释里会提到 CONFIG_SCHEMA 等大写标识符,不是配置键。
    body = "\n".join(ln for ln in block.split("\n") if not ln.strip().startswith("//"))
    return set(re.findall(r"'([A-Z][A-Z0-9_]*)'", body))


class TestExtractionItself:
    """先证明扫描有效 —— 扫不出东西的话,下面的断言全是空转。"""

    def test_finds_a_meaningful_number_of_keys(self):
        found = _extract_config_reads()
        assert len(found) >= 20, f"只扫出 {len(found)} 个配置键,正则可能失效了: {sorted(found)}"

    def test_does_not_pick_up_mentions_in_prose(self):
        """判别用例:``GALAXY_TTS_STREAMING`` 在双工模块的 docstring 里被提到,
        但那里并不读它(它由 speech_output 读)。按裸变量名扫会误抓,按调用形式扫不会。"""
        src = (REPO_ROOT / "core/voice_duplex_session.py").read_text(encoding="utf-8")
        assert "GALAXY_TTS_STREAMING" not in _CONFIG_READ_RE.findall(src)

    def test_settings_tab_keys_are_parsed(self):
        keys = _extract_settings_tab_keys()
        assert len(keys) >= 100, f"只解析出 {len(keys)} 个,SettingsTab 的结构可能变了"


class TestEveryVoiceSwitchIsRegisteredBackend:
    def test_every_config_read_is_in_config_schema(self):
        from core.routes.config import CONFIG_SCHEMA

        found = _extract_config_reads()
        missing = {
            key: mods
            for key, mods in found.items()
            if key not in CONFIG_SCHEMA and key not in _PENDING_SECRET_ROUTING and key not in _NOT_USER_SETTINGS
        }
        assert not missing, (
            "以下配置键在代码里被读取,但 core/routes/config.py::CONFIG_SCHEMA 里没有 —— "
            "GET /api/config/all 不会返回它们,POST /api/config 还会把它们当 unknown_keys "
            f"拒掉(400)。功能等于没接到面板上: {missing}"
        )

    def test_no_exemptions_remain(self):
        """豁免集合必须是空的 —— 有豁免就说明还有键没接进面板。"""
        assert _PENDING_SECRET_ROUTING == frozenset()

    def test_not_user_settings_entries_are_still_actually_read(self):
        """豁免的键必须还在被代码读取 —— 否则它是过期条目,该删掉而不是留着遮蔽。

        豁免集合最危险的失效方式不是"漏了谁",而是**留着一条早已无用的豁免**:后来某个
        同名键真的需要上面板时,它会被静默放行。
        """
        found = _extract_config_reads()
        stale = sorted(k for k in _NOT_USER_SETTINGS if k not in found)
        assert not stale, f"豁免集合里有已经没人读的键,应删除: {stale}"

    def test_not_user_settings_stays_small_and_justified(self):
        """豁免不是垃圾桶。数量必须小,且每一条在源码里都有紧邻的理由说明。"""
        from pathlib import Path as _P

        assert len(_NOT_USER_SETTINGS) <= 3, "豁免项变多了 —— 先确认每一条都真的不该上面板"
        src = _P(__file__).read_text(encoding="utf-8")
        block = src.split("_NOT_USER_SETTINGS = {", 1)[1].split("}", 1)[0]
        for key in _NOT_USER_SETTINGS:
            assert key in block, f"{key} 不在豁免声明块里?"
        assert "#" in block, "豁免块里没有任何理由说明"


class TestRealtimeKeyRoutesToSecretStore:
    """``GALAXY_REALTIME_API_KEY`` 必须走加密存储,不能明文落 .env。

    这一组取代了原先那条建立在**错误前提**上的绊线(详见 ``_PENDING_SECRET_ROUTING``
    上方的说明)。现在直接断言真正决定分流的那个函数的结果,而不是断言某个与分流无关的
    名单里有没有它。
    """

    def test_classify_key_says_secret(self):
        from core.config_schema import classify_key

        assert classify_key("GALAXY_REALTIME_API_KEY") == "secret"

    def test_it_is_registered_in_the_panel_schema(self):
        from core.routes.config import CONFIG_SCHEMA

        assert "GALAXY_REALTIME_API_KEY" in CONFIG_SCHEMA

    def test_the_suffix_heuristic_is_what_makes_it_secret(self):
        """钉住机制本身:是**后缀**让它成为 secret。

        若哪天有人把它改名成不带 ``_API_KEY`` 后缀的形式(比如
        ``GALAXY_REALTIME_CREDENTIAL``),分流就会静默变成"非 secret"→ 明文落 .env。
        这条让那种改名当场炸出来。
        """
        from core.config_schema import classify_key

        assert classify_key("GALAXY_REALTIME_CREDENTIAL") != "secret"
        assert classify_key("GALAXY_REALTIME_API_KEY") == "secret"

    def test_saving_it_does_not_write_plaintext_env(self, tmp_path, monkeypatch):
        """端到端:POST /api/config 存这把 key,``.env`` 里不得出现它的值。"""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import core.config_store as config_store_module
        import core.routes.config as config_module

        env_file = tmp_path / ".env.test"
        monkeypatch.setattr(config_module, "ENV_FILE", env_file)
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
        client = TestClient(app)

        # 运行时拼装,避免在文件里留下形似凭据的字面量(gitleaks generic-api-key)
        marker = "REALTIME" + "-" + "probe" + "-" + "value"
        resp = client.post("/api/config", json={"config": {"GALAXY_REALTIME_API_KEY": marker}})
        assert resp.status_code == 200, resp.text

        if env_file.exists():
            assert marker not in env_file.read_text(encoding="utf-8"), "密钥被明文写进了 .env"
        secrets_file = tmp_path / "secrets.env.test"
        assert secrets_file.exists(), "密钥没有落到 secrets.env"
        assert marker in secrets_file.read_text(encoding="utf-8"), "密钥没有落到 secrets.env"


class TestEveryVoiceSwitchIsRegisteredFrontend:
    def test_every_config_read_is_listed_in_the_panel(self):
        found = _extract_config_reads()
        panel_keys = _extract_settings_tab_keys()
        missing = {
            key: mods
            for key, mods in found.items()
            if key not in panel_keys and key not in _PENDING_SECRET_ROUTING and key not in _NOT_USER_SETTINGS
        }
        assert not missing, (
            "以下配置键在代码里被读取,但 SettingsTab.tsx 的 CONFIG_KEYS 里没列 —— "
            f"面板设置页上没有它们的位置,用户只能手改 .env: {missing}"
        )


class TestSchemaEntriesAreHonest:
    """schema 里写的默认值必须和代码里的真实默认值一致 —— 否则面板显示的「默认」是假的。"""

    @pytest.mark.parametrize(
        ("key", "expected"),
        [
            ("GALAXY_AEC", "true"),
            ("GALAXY_VOICE_ECHO_GUARD", "true"),
            ("GALAXY_VOICE_BACKCHANNEL_TOLERANCE", "true"),
            ("GALAXY_SYSTEM_AUDIO_CAPTURE", "true"),
            ("GALAXY_SYSTEM_AUDIO_TO_PERCEPTION", "true"),
            ("GALAXY_VOICE_DUPLEX", "false"),
            ("GALAXY_VOICE_DUCKING", "true"),
            ("GALAXY_VOICE_DUCK_GAIN", "0.25"),
            ("GALAXY_VOICE_HOLD_S", "90.0"),
            ("GALAXY_VOICE_ECHO_SIM", "0.62"),
            ("GALAXY_VOICE_ECHO_TAIL_S", "6.0"),
            ("GALAXY_VOICE_ECHO_MIN_CHARS", "4"),
            ("GALAXY_VOICE_ECHO_MIN_BLOCK", "4"),
            ("GALAXY_AEC_TAIL_MS", "128.0"),
            ("GALAXY_AEC_MU", "0.35"),
            ("GALAXY_AEC_MAX_DELAY_MS", "400.0"),
            ("GALAXY_AEC_DTD_MARGIN_DB", "6.0"),
            # B 档本地全模态 server 与模态通路(2026-07-30 补登记)。默认值逐个对着
            # 代码核过:native_modal._DEFAULT_SERVER_URL / _auto_activation_allowed()
            # 的"默认允许" / modality_bridge 里的 "base"、4.0、1.0。
            ("GALAXY_MINICPM_SERVER_URL", "http://localhost:32550"),
            ("GALAXY_NATIVE_MODAL_AUTO", "true"),
            ("GALAXY_AMBIENT_ASR_SIZE", "base"),
            ("GALAXY_VIDEO_FPS_NATIVE", "4.0"),
            ("GALAXY_VIDEO_FPS_BRIDGE", "1.0"),
        ],
    )
    def test_default_matches_the_code(self, key, expected):
        from core.routes.config import CONFIG_SCHEMA

        assert CONFIG_SCHEMA[key]["default"] == expected

    def test_defaults_agree_with_the_functions_that_read_them(self):
        """不只比字面量,直接调那些读取函数,确认无环境变量时返回的就是 schema 的默认值。

        这条才真正防住「schema 改了默认值但代码没改」——上面那组只钉住字面量,
        如果两边一起被改错,它照样通过。
        """
        import os

        from core.multimodal.acoustic_echo_canceller import enabled as aec_enabled
        from core.multimodal.system_audio_capture_service import enabled as capture_enabled
        from core.multimodal.system_audio_capture_service import feed_perception_enabled
        from core.routes.config import CONFIG_SCHEMA
        from core.voice_dialog_policy import backchannel_tolerance_enabled
        from core.voice_duplex_session import duck_gain, ducking_enabled, duplex_enabled
        from core.voice_echo_guard import enabled as echo_guard_enabled

        cases = [
            ("GALAXY_AEC", aec_enabled),
            ("GALAXY_VOICE_ECHO_GUARD", echo_guard_enabled),
            ("GALAXY_VOICE_BACKCHANNEL_TOLERANCE", backchannel_tolerance_enabled),
            ("GALAXY_SYSTEM_AUDIO_CAPTURE", capture_enabled),
            ("GALAXY_SYSTEM_AUDIO_TO_PERCEPTION", feed_perception_enabled),
            ("GALAXY_VOICE_DUPLEX", duplex_enabled),
            ("GALAXY_VOICE_DUCKING", ducking_enabled),
        ]
        saved = {k: os.environ.pop(k, None) for k, _ in cases}
        saved["GALAXY_VOICE_DUCK_GAIN"] = os.environ.pop("GALAXY_VOICE_DUCK_GAIN", None)
        try:
            for key, fn in cases:
                schema_default = CONFIG_SCHEMA[key]["default"] == "true"
                assert fn() is schema_default, (
                    f"{key}: 代码里的默认是 {fn()},但 CONFIG_SCHEMA 写的是 "
                    f'{CONFIG_SCHEMA[key]["default"]!r} —— 面板显示的默认值是假的'
                )
            assert duck_gain() == float(CONFIG_SCHEMA["GALAXY_VOICE_DUCK_GAIN"]["default"])
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_booleans_are_typed_as_boolean_so_they_render_as_toggles(self):
        """用户要的是推拉开关。type 不是 boolean 的话 SettingsTab 会渲染成输入框。"""
        from core.routes.config import CONFIG_SCHEMA

        for key in (
            "GALAXY_AEC",
            "GALAXY_VOICE_ECHO_GUARD",
            "GALAXY_VOICE_BACKCHANNEL_TOLERANCE",
            "GALAXY_SYSTEM_AUDIO_CAPTURE",
            "GALAXY_SYSTEM_AUDIO_TO_PERCEPTION",
            "GALAXY_VOICE_DUPLEX",
            "GALAXY_VOICE_DUCKING",
        ):
            assert CONFIG_SCHEMA[key]["type"] == "boolean", f"{key} 不会渲染成推拉开关"

    def test_every_new_switch_has_a_chinese_description(self):
        """面板上显示的就是 description。留空或只有变量名的话用户看不懂这是干什么的。"""
        from core.routes.config import CONFIG_SCHEMA

        found = _extract_config_reads()
        bad = []
        for key in found:
            meta = CONFIG_SCHEMA.get(key)
            if meta is None:
                continue
            desc = meta.get("description", "")
            if not desc or not re.search(r"[一-鿿]", desc):
                bad.append(key)
        assert not bad, f"以下项缺中文说明,面板上用户看不懂: {bad}"


class TestPanelCanActuallySaveThem:
    """端到端:POST /api/config 真的能存这些开关(不再 400)。"""

    def _client(self, tmp_path, monkeypatch):
        import core.config_store as config_store_module
        import core.routes.config as config_module

        # 隔离真实 .env 与 runtime/secrets.env —— 绝不能让测试写脏仓库里的真实密钥库。
        monkeypatch.setattr(config_module, "ENV_FILE", tmp_path / ".env.test")
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

    def test_saving_the_voice_switches_succeeds(self, tmp_path, monkeypatch):
        client = self._client(tmp_path, monkeypatch)
        payload = {
            "GALAXY_AEC": "false",
            "GALAXY_VOICE_ECHO_GUARD": "false",
            "GALAXY_VOICE_BACKCHANNEL_TOLERANCE": "false",
            "GALAXY_SYSTEM_AUDIO_CAPTURE": "false",
            "GALAXY_VOICE_DUPLEX": "true",
            "GALAXY_VOICE_DUCKING": "false",
            "GALAXY_VOICE_DUCK_GAIN": "0.4",
        }
        resp = client.post("/api/config", json={"config": payload})
        assert resp.status_code == 200, resp.text
        assert set(resp.json()["updated"]) == set(payload)

    def test_config_all_returns_them_with_type_and_description(self, tmp_path, monkeypatch):
        """面板靠 /api/config/all 拿 type/description 来渲染控件。缺了就渲染不出开关。"""
        client = self._client(tmp_path, monkeypatch)
        resp = client.get("/api/config/all")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        items = body.get("config", body)
        for key in ("GALAXY_AEC", "GALAXY_VOICE_DUPLEX", "GALAXY_VOICE_DUCK_GAIN"):
            assert key in items, f"/api/config/all 没返回 {key}"
            assert items[key]["type"] in ("boolean", "number")
            assert items[key]["description"]


class TestOnePullSwitchAcrossThePanel:
    """用户要求:全面板统一用推拉开关,参照 worker 那个。

    ``MeshView`` 的 NATS Worker 开关用的是 App.css 里的 ``.switch`` / ``.switch-knob``。
    ``SettingsTab`` 原先自带一份 ``.settings-toggle``(白滑块 + accent 底、无描边),
    两者并排出现在同一个面板里看得出不一致。已统一到 ``.switch``。
    """

    def test_settings_toggle_uses_the_same_classes_as_the_worker_switch(self):
        src = SETTINGS_TAB.read_text(encoding="utf-8")
        block = src[src.index("function ToggleSwitch") : src.index("function PasswordInput")]
        assert "'switch'" in block or "`switch" in block, "ToggleSwitch 没有用 .switch 类名"
        assert "switch-knob" in block, "ToggleSwitch 缺少 .switch-knob 滑块"

    def test_the_duplicate_toggle_style_is_gone(self):
        """反向验证:那份重复样式必须真的被删掉,而不是留着继续被别处引用。"""
        css = (SETTINGS_TAB.parent / "SettingsTab.css").read_text(encoding="utf-8")
        selectors = re.findall(r"^\.settings-toggle[^\n]*\{", css, re.M)
        assert not selectors, f"SettingsTab.css 里仍有重复的开关样式: {selectors}"

    def test_no_source_still_uses_the_removed_class(self):
        """必须比对**去掉注释后**的代码。

        第一版这条直接在整份文件里搜 ``settings-toggle`` 字面量,结果被自己的说明
        注释绊倒 —— 两个文件里都留了一段「这里原先有一份 .settings-toggle,已删除」
        的注释。那种写法测的是「文件里有没有提到这个名字」,而要测的是
        「还有没有代码在用它」。
        """
        panel_src = SETTINGS_TAB.parent.parent
        block_comment = re.compile(r"/\*.*?\*/", re.S)
        line_comment = re.compile(r"^\s*//.*$", re.M)
        stale = []
        for path in panel_src.rglob("*"):
            if path.suffix not in {".tsx", ".ts", ".css"}:
                continue
            code = line_comment.sub("", block_comment.sub("", path.read_text(encoding="utf-8")))
            if "settings-toggle" in code:
                stale.append(str(path.relative_to(panel_src)))
        assert not stale, f"这些文件的**代码**里还在用已删除的 .settings-toggle: {stale}"

    def test_worker_switch_style_exists_and_slides(self):
        """被参照的那份样式得真的存在、而且真的是左右滑动的。"""
        app_css = (SETTINGS_TAB.parent.parent / "App.css").read_text(encoding="utf-8")
        assert ".switch {" in app_css
        assert ".switch-knob {" in app_css
        knob_on = app_css[app_css.index(".switch.on .switch-knob") :][:200]
        assert "translateX" in knob_on, "worker 开关并不是左右滑动的?样式可能已改"
