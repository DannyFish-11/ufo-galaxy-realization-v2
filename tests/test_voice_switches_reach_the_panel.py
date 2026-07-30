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
)

#: 只匹配**真正的读取调用**,不匹配 docstring / 日志文案里对变量名的提及。
#: 这些模块的 docstring 和 warning 文案里大量出现 "GALAXY_VOICE_ECHO_GUARD=0 复核"
#: 这类字样,按裸变量名扫会扫出一堆并非配置读取点的假阳性。
_CONFIG_READ_RE = re.compile(r"""(?:os\.getenv|os\.environ\.get|_flag|_num)\(\s*["'](GALAXY_[A-Z0-9_]+)["']""")

#: 刻意**还没**登记进 CONFIG_SCHEMA 的键,连同不登记的理由。
#:
#: ``GALAXY_REALTIME_API_KEY`` 是密钥。``core/routes/config.py`` 里另有一份
#: ``_SECRET_MODEL_KEYS`` 决定哪些键走 ``ConfigService.set_secret()`` → 落
#: ``runtime/secrets.env``;**不在那份名单里的键会被 ``_write_env_file_with()``
#: 明文写进 .env**。所以只把它登进 CONFIG_SCHEMA、却不同时加进 _SECRET_MODEL_KEYS,
#: 等于给自己开一个明文落盘的口子 —— 比不登记更糟。
#:
#: 这个豁免本身是**绊线**而不是静默跳过:下面 ``test_pending_key_is_still_absent``
#: 断言它**确实不在** CONFIG_SCHEMA 里。将来谁把它登进去,那条测试就会炸,迫使
#: 他同时处理 _SECRET_MODEL_KEYS,而不是悄悄留下明文写盘。
_PENDING_SECRET_ROUTING = frozenset({"GALAXY_REALTIME_API_KEY"})


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
            key: mods for key, mods in found.items() if key not in CONFIG_SCHEMA and key not in _PENDING_SECRET_ROUTING
        }
        assert not missing, (
            "以下配置键在代码里被读取,但 core/routes/config.py::CONFIG_SCHEMA 里没有 —— "
            "GET /api/config/all 不会返回它们,POST /api/config 还会把它们当 unknown_keys "
            f"拒掉(400)。功能等于没接到面板上: {missing}"
        )

    def test_pending_key_is_still_absent(self):
        """绊线:``GALAXY_REALTIME_API_KEY`` 一旦被登进 CONFIG_SCHEMA,这条就炸。

        炸了不是坏事 —— 它是在提醒:登记密钥前必须先把它加进 ``_SECRET_MODEL_KEYS``,
        否则会被明文写进 .env。两件事一起做完,再把它从 ``_PENDING_SECRET_ROUTING``
        里删掉。
        """
        from core.routes.config import _SECRET_MODEL_KEYS, CONFIG_SCHEMA

        for key in _PENDING_SECRET_ROUTING:
            if key in CONFIG_SCHEMA:
                assert key in _SECRET_MODEL_KEYS, (
                    f"{key} 已登进 CONFIG_SCHEMA 但不在 _SECRET_MODEL_KEYS 里 —— "
                    "它会被明文写进 .env。请同时加进 _SECRET_MODEL_KEYS,"
                    "并把它从本测试的 _PENDING_SECRET_ROUTING 里删掉。"
                )


class TestEveryVoiceSwitchIsRegisteredFrontend:
    def test_every_config_read_is_listed_in_the_panel(self):
        found = _extract_config_reads()
        panel_keys = _extract_settings_tab_keys()
        missing = {
            key: mods for key, mods in found.items() if key not in panel_keys and key not in _PENDING_SECRET_ROUTING
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
