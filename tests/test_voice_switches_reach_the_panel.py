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

#: 语音/感知栈的模块范围 —— **按目录模式派生,不是手写清单**。
#:
#: 这里原先是一个手工维护的元组。它漏了两次:
#:   * 第一次漏掉 native_modal.py / modality_bridge.py → 5 个键静默不受保护
#:     (GALAXY_MINICPM_SERVER_URL / GALAXY_NATIVE_MODAL_AUTO / GALAXY_AMBIENT_ASR_SIZE /
#:      GALAXY_VIDEO_FPS_NATIVE / GALAXY_VIDEO_FPS_BRIDGE);
#:   * 补进那三个模块之后**仍然**漏 —— 整个 core/tts/、core/asr/、core/perception/、
#:     core/computer_use_loop.py、core/routes/chat.py 从来就不在清单里,又是 36 个键。
#:
#: 两次都是"发现一处补一处"。手写清单的失效方式不是写错,而是**新模块加进来时
#: 没人记得回来改这里** —— 补键治不了它,只有让范围自己长出来才治得了。
#:
#: 改成按 glob 派生后:新增 core/tts/xxx_engine.py、core/voice_yyy.py、
#: core/perception/zzz.py 一律自动纳管,不需要任何人记得回来登记。
#: 代价是范围可能收进一两个不读配置的模块 —— 那是零成本的(扫不出键而已),
#: 远好过漏掉一个真读配置的模块。
#: 2026-08-04 再补:统一启动器 ``launcher/`` + ``main.py``。
#: 它们不是语音模块,但**语音的总开关长在那里**(``GALAXY_VOICE`` 决定语音循环起不起、
#: ``GALAXY_WHISPER_MODEL`` 决定识别模型规格),而这份守卫的契约本来就是
#: 「代码里读了配置键 → 面板上必须有它」,与模块姓什么无关。启动器重做落地后
#: 它是整个系统唯一的入口,那 15 个键里既有语音总开关也有部署项,同样一个都不该
#: 只能靠手改 .env。收进来之后又是一次"扫出来才发现"—— 与前两次同一种漏法。
#: 2026-08-05 收口:范围直接放到**整个 core/**。
#:
#: 上面那段"让范围自己长出来"的结论只对了一半 —— 派生确实治住了「新模块没人记得
#: 登记」,但**派生的范围本身仍然是人划的**:划到 core/tts/、core/asr/ 就只保护到那里。
#: 放到整个 core/ 之后一次扫出 99 个未登记键,也就是说前三轮补完(21+5+36+15)覆盖到的
#: 仍只是这个仓库配置面的一部分。
#:
#: 「代码里读了配置键 → 面板上必须有它」这条契约与模块姓什么无关,那就别再按模块挑。
#: 现在的范围 = core/ 全量 + launcher/ 全量 + main.py,即**所有会读配置的产品代码**。
_VOICE_MODULE_PATTERNS = (
    "core/**/*.py",
    "launcher/**/*.py",
    "main.py",
)


def _voice_modules() -> list[str]:
    """按模式展开出实际存在的模块(相对仓库根,排序稳定)。"""
    return sorted(
        {str(p.relative_to(REPO_ROOT)) for pat in _VOICE_MODULE_PATTERNS for p in REPO_ROOT.glob(pat) if p.is_file()}
    )


#: 明确豁免:**不该出现在面板上**的键,连同理由。
#:
#: 与"暂时不登记"不同 —— 这些是部署环境标记,不是用户设置项,登上面板反而是错的。
#: 写成显式集合而非静默跳过:任何人要加豁免都得在这里写下理由。
_NOT_USER_SETTINGS = {
    # 测试期标记。core/native_modal.py 用它(连同 PYTEST_CURRENT_TEST)禁止 save_tier('B')
    # 的单测触发真实后台 pip 安装。由运行环境设置,不是用户在面板上调的东西。
    "GALAXY_ENV",
    # ── 引导层:决定「配置从哪儿读」──────────────────────────────────────────
    # 统一配置文件的路径。面板是配置的**消费者**,它的值经 .env / config.json 落盘,
    # 而这个键决定那些文件在哪儿 —— 用面板改它 = 站在梯子上搬梯子:改完之后面板下次
    # 读的还是旧位置(新位置里没有它),用户只会看到"改了没生效"而无从排查。
    "GALAXY_CONFIG_PATH",
    # 配置目录。同上,同一个"梯子"问题。
    "GALAXY_CONFIG_DIR",
    # ── 进程身份:由启动器按进程分配,不是一台机器一个值 ──────────────────────
    # 节点 id。同机会同时跑多个节点,每个进程必须拿到不同的值;面板只有一份全局配置,
    # 登上去等于把所有节点的身份钉成同一个 —— 那正是要避免的事。
    "GALAXY_NODE_ID",
    # worker id。同上:一台机器多个 worker 进程,身份必须逐进程不同。
    "GALAXY_WORKER_ID",
    # 构建期版本标记,随发布产物走。由人手填毫无意义 —— 填了只会让上报的版本号说谎。
    "GALAXY_WORKER_VERSION",
    # 终端能力标记(NO_COLOR 惯例的本仓库版本)。它约束的是**命令行输出**有没有颜色,
    # 而面板是图形界面 —— 在面板上放一个"命令行要不要上色"的开关,位置就是错的。
    "GALAXY_NO_COLOR",
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


@pytest.fixture(autouse=True)
def _resync_unified_config_after_each_test():
    """每条用例跑完,让 ``UnifiedConfig`` 单例与**还原后**的进程状态重新对齐。

    为什么需要这一条
    ----------------
    本文件里有两条端到端用例会真的 ``POST /api/config``。``update_config()`` 除了
    落盘,还会 (1) 写 ``os.environ``、(2) 调 ``UnifiedConfig.reload()`` —— 生产上
    两件都对(面板改完不必重启就生效)。但对测试来说,那些假值就**留在了进程里**:

    * ``os.environ`` 那一份由各用例的 ``monkeypatch.setenv`` 还原;
    * ``UnifiedConfig._config`` 是 reload 时照着当时的 os.environ / ConfigStore 拍下
      的**内存快照**,还原环境变量并不会动它。而 ``core.secret_resolution`` 的第一层
      读的正是它 —— 于是一把测试用的假 realtime key 会一直被后面的用例解析到。

    实测污染:``tests/test_voice_duplex_session.py`` 有 8 条独立跑全绿、与本文件
    同进程跑就红("双工默认关"变成默认开、Gemini 分支的 URL 里拼进了假 key)。

    为什么是 autouse 而不是写在那两条用例里
    ------------------------------------------
    finalizer 按**建立顺序的逆序**执行。autouse fixture 在 ``monkeypatch`` 之前建立,
    所以它的收尾跑在 monkeypatch 撤销**之后** —— 那时 ``os.environ`` 与
    ``config_store._singleton`` 都已还原,这一次 reload 才拍得到干净的快照。
    写在用例体里做不到这个顺序。
    """
    yield
    try:
        from core.unified_config import config as _cfg

        _cfg.reload()
    except Exception:  # noqa: BLE001 —— 收尾失败不该把用例判红
        pass


def _extract_config_reads() -> dict[str, list[str]]:
    """返回 ``{配置键: [读它的模块, ...]}``。"""
    found: dict[str, list[str]] = {}
    for rel in _voice_modules():
        path = REPO_ROOT / rel
        if not path.exists():
            continue
        for key in _CONFIG_READ_RE.findall(path.read_text(encoding="utf-8")):
            found.setdefault(key, []).append(rel)
    return found


def _extract_settings_tab_keys() -> set[str]:
    """从 SettingsTab.tsx 的 KEY_ORDER_HINT 里取出所有 key。

    这份清单**不再是分组的定义**(2026-08-30 起分组由 /api/config/all 返回的
    category 现算),只是同类内的顺序提示。但它仍然值得查一遍:里面写错一个键名,
    那个键就会掉到字母序末尾而不报错。
    """
    src = SETTINGS_TAB.read_text(encoding="utf-8")
    start = src.index("const KEY_ORDER_HINT")
    end = src.index("\n};", start)
    block = src[start:end]
    # 去掉注释行:注释里会提到 CONFIG_SCHEMA 等大写标识符,不是配置键。
    body = "\n".join(ln for ln in block.split("\n") if not ln.strip().startswith("//"))
    return set(re.findall(r"'([A-Z][A-Z0-9_]*)'", body))


def _extract_decorated_categories() -> set[str]:
    """CATEGORIES 里有显示装饰(标签/图标)的分类。"""
    src = SETTINGS_TAB.read_text(encoding="utf-8")
    start = src.index("const CATEGORIES")
    end = src.index("\n];", start)
    return set(re.findall(r"key:\s*'([a-z_]+)'", src[start:end]))


def _extract_delegated_categories() -> set[str]:
    """显式声明「由别的 tab 拥有」的分类。"""
    src = SETTINGS_TAB.read_text(encoding="utf-8")
    start = src.index("const DELEGATED_CATEGORIES")
    end = src.index("]);", start)
    body = "\n".join(ln for ln in src[start:end].split("\n") if not ln.strip().startswith("//"))
    return set(re.findall(r"'([a-z_]+)'", body))


class TestTheModuleScopeIsDerivedNotHandWritten:
    """守住"范围自己长出来"这件事本身 —— 它才是这个文件漏过两次的真正根因。

    补键只治当次的症状。范围一旦退回手写清单(或者某条模式因为目录改名而
    静默匹配不到任何文件),下一批新模块里的配置键又会无声无息地不受保护。
    """

    def test_every_pattern_actually_matches_something(self):
        """每条模式都必须真的命中文件。

        一条命中不到文件的模式(目录改名、写错路径)不会报错,只会让守卫的
        范围**静默缩小** —— 与手写清单漏掉一个模块是完全相同的失效方式。
        """
        dead = [pat for pat in _VOICE_MODULE_PATTERNS if not any(p.is_file() for p in REPO_ROOT.glob(pat))]
        assert not dead, f"这些模式匹配不到任何文件,守卫范围已静默缩小: {dead}"

    def test_the_scope_covers_the_directories_the_hand_list_missed(self):
        """判别用例:手写清单当初漏掉的那几类目录,现在必须在范围内。

        直接钉住具体模块,而不是只数一个总数 —— 总数会被别处新增的文件顶上去,
        看起来还在涨,实际这几个目录已经掉出范围了。
        """
        mods = set(_voice_modules())
        for rel in (
            "core/tts/kokoro_engine.py",  # 整个 core/tts/ 从来不在手写清单里
            "core/asr/whisper_asr.py",  # core/asr/ 同上
            "core/perception/desktop_perception_store.py",  # core/perception/ 同上
            "core/computer_use_loop.py",
            "core/routes/chat.py",
            "core/ambient_attention_loop.py",
        ):
            assert rel in mods, f"{rel} 掉出了守卫范围 —— 它里面的配置键不再受保护"

    def test_a_new_module_is_picked_up_without_editing_this_file(self, tmp_path, monkeypatch):
        """反向验证:范围**真的是派生的**。

        往受管目录里放一个新模块,它必须自动出现在范围里 —— 不需要任何人回来
        改这个文件。如果哪天有人把派生改回硬编码清单,这条会当场炸。
        """
        probe = REPO_ROOT / "core/tts/_scope_probe_tmp.py"
        assert not probe.exists()
        probe.write_text('import os\nos.getenv("GALAXY_SCOPE_PROBE_TMP", "")\n', encoding="utf-8")
        try:
            assert "core/tts/_scope_probe_tmp.py" in _voice_modules()
            assert "GALAXY_SCOPE_PROBE_TMP" in _extract_config_reads()
        finally:
            probe.unlink()


class TestExtractionItself:
    """先证明扫描有效 —— 扫不出东西的话,下面的断言全是空转。"""

    def test_finds_a_meaningful_number_of_keys(self):
        found = _extract_config_reads()
        # 门槛按派生后的真实规模(77)下调一档留余量。原先是 20 —— 那是手写清单时代的
        # 量级,范围扩大后它形同虚设:掉回只剩 21 个键也照样通过。
        assert len(found) >= 60, f"只扫出 {len(found)} 个配置键,正则或范围可能失效了: {sorted(found)}"

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
        """豁免不是垃圾桶:数量要小,且**每一条**都得在源码里紧邻写下理由。

        上限从 3 提到 8:守卫范围放到整个 core/ 之后,真正够得上"不该上面板"的键
        从 1 个变成 7 个(引导层 2 + 进程身份 3 + 终端能力 1 + 测试标记 1)。
        这不是放水 —— 数量随范围扩大而增长是应该的,**理由的密度不能降**。

        所以判据从"块里有 # 号"改成**逐条要求紧邻注释**:原先那种写法,一条注释就能
        糊弄过任意多个键。现在每个键往上找,跳过空行后必须先遇到 ``#``。
        """
        from pathlib import Path as _P

        assert len(_NOT_USER_SETTINGS) <= 8, "豁免项变多了 —— 先确认每一条都真的不该上面板"
        src = _P(__file__).read_text(encoding="utf-8")
        block = src.split("_NOT_USER_SETTINGS = {", 1)[1].split("\n}", 1)[0]
        lines = block.split("\n")
        for key in _NOT_USER_SETTINGS:
            idx = next((i for i, ln in enumerate(lines) if f'"{key}"' in ln), None)
            assert idx is not None, f"{key} 不在豁免声明块里?"
            above = [ln.strip() for ln in lines[:idx][::-1] if ln.strip()]
            assert above and above[0].startswith("#"), f"豁免 {key} 没有紧邻的理由说明 —— 豁免必须写清楚为什么"


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
        # 关键的一步:先让 monkeypatch **接管**这个环境变量。
        #
        # update_config() 除了落盘还会写 os.environ(生产上就该这样 —— 面板改完不必
        # 重启就生效)。而这个测试原先只隔离了**文件**,没有隔离 os.environ:那把假
        # key 会一直留在进程里,后面任何走 resolve_secret("GALAXY_REALTIME_API_KEY")
        # 的测试都会捞到它。实测污染了 tests/test_voice_duplex_session.py 的 8 条
        # (它们独立跑全绿、和本文件同进程跑就红:"双工默认关"变成了默认开,
        # Gemini 分支的 URL 里拼进了这个假 key)。
        #
        # monkeypatch.setenv 会记下变量**当前的状态**(包括"原本不存在"),teardown
        # 时整个还原 —— 所以它也覆盖得住之后由路由代码写进去的值。
        monkeypatch.setenv("GALAXY_REALTIME_API_KEY", "unset-by-test")

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
    """用户改得了它吗 —— 这条保证在 2026-08-30 换了实现,但**没有变弱**。

    从前:成员关系写在 SettingsTab.tsx 的 CONFIG_KEYS 里,一个键没列进去就在设置页上
    完全看不见。于是这条测试查的是"列没列"。

    现在:分组由 /api/config/all 返回的 category 现算,列不列只影响排序。所以"可达"
    这件事改由另一个前提保证 —— **这个键的 category 得有归宿**:要么在 CATEGORIES 里
    有显示装饰,要么被显式委派给别的 tab。

    新判据比旧的严:旧的只查键在不在清单里,查不出"某个 category 根本没人管"这种情况
    (那会让整整一类设置项一起消失,而不是漏一个)。
    """

    def test_every_config_read_has_a_home_in_the_ui(self):
        from core.routes.config import CONFIG_SCHEMA

        found = _extract_config_reads()
        decorated = _extract_decorated_categories()
        delegated = _extract_delegated_categories()
        homed = decorated | delegated

        homeless = {}
        for key, mods in found.items():
            if key in _PENDING_SECRET_ROUTING or key in _NOT_USER_SETTINGS:
                continue
            meta = CONFIG_SCHEMA.get(key)
            if meta is None:
                continue  # 由同文件的 test_every_config_read_is_in_config_schema 管
            cat = meta.get("category", "")
            if cat not in homed:
                homeless[key] = (cat, mods)
        assert not homeless, (
            "以下配置键的 category 在设置页上没有归宿(既没在 CATEGORIES 里装饰,"
            f"也没显式委派给别的 tab)—— 它们在界面上不会出现: {homeless}"
        )

    def test_delegated_categories_are_actually_owned_by_that_tab(self):
        """委派不能是一句空话。

        声明「llm 这一类归 ModelsTab」之后,那些键必须真的在 ModelsTab.tsx 里出现。
        否则「委派」就成了「藏起来」的好听说法 —— 而这正是本仓最常见的那种失效:
        看起来有人管,其实没有。
        """
        from core.routes.config import CONFIG_SCHEMA

        delegated = _extract_delegated_categories()
        assert delegated, "一个委派都没有的话,这条测试就成了空转"

        models_tab = SETTINGS_TAB.parent / "ModelsTab.tsx"
        owner_src = models_tab.read_text(encoding="utf-8") if models_tab.exists() else ""
        orphans = []
        for key, meta in CONFIG_SCHEMA.items():
            if meta.get("category") not in delegated:
                continue
            if key in _PENDING_SECRET_ROUTING or key in _NOT_USER_SETTINGS:
                continue
            if re.search(r"['\"]" + re.escape(key) + r"['\"]", owner_src):
                continue
            # 别名键(描述里写明是另一个键的别名)不必各自出现
            if "别名" in str(meta.get("description", "")):
                continue
            orphans.append(key)
        assert not orphans, f"这些键声称委派给了 ModelsTab,但那边找不到它们: {orphans}"


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
            ("GALAXY_VOICE_DUPLEX", "auto"),
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
        from core.voice_duplex_session import duck_gain, ducking_enabled
        from core.voice_echo_guard import enabled as echo_guard_enabled

        cases = [
            ("GALAXY_AEC", aec_enabled),
            ("GALAXY_VOICE_ECHO_GUARD", echo_guard_enabled),
            ("GALAXY_VOICE_BACKCHANNEL_TOLERANCE", backchannel_tolerance_enabled),
            ("GALAXY_SYSTEM_AUDIO_CAPTURE", capture_enabled),
            ("GALAXY_SYSTEM_AUDIO_TO_PERCEPTION", feed_perception_enabled),
            ("GALAXY_VOICE_DUCKING", ducking_enabled),
        ]
        # GALAXY_VOICE_DUPLEX 不在这里:它是**三态**(auto/1/0),不设时按当前档位的
        # 真实供给判定 —— 根本没有一个固定的布尔默认值可比。拿一个固定值去比它，
        # 结果只取决于跑测试那台机器上有没有 realtime key，是条会飘的判据。
        # 三态开关由下面 test_three_state_switches_declare_auto 单独钉。
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
            "GALAXY_VOICE_DUCKING",
            "GALAXY_AEC_RES",
            "GALAXY_AEC_COMFORT_NOISE",
        ):
            assert CONFIG_SCHEMA[key]["type"] == "boolean", f"{key} 不会渲染成推拉开关"

    def test_three_state_switches_declare_auto(self):
        """三态开关(auto / 1 / 0)不能声明成 boolean+false —— 那是**假的默认值**。

        双工与"文字语音同刻"都已改成:不设时按真实能力自动判定。若 schema 仍写
        boolean/false，面板会显示"关"而系统实际已自动开启 —— 用户看到的与发生的
        不是一回事，正是这一组守卫要防的事。
        """
        from core.routes.config import CONFIG_SCHEMA

        for key in ("GALAXY_VOICE_DUPLEX", "GALAXY_TEXT_VOICE_LOCKSTEP"):
            entry = CONFIG_SCHEMA[key]
            assert entry["default"] == "auto", f"{key} 的默认值不是 auto —— 面板会显示假的默认"
            assert entry["type"] != "boolean", f"{key} 是三态，渲染成推拉开关就丢了 auto 档"
            assert "auto" in entry["description"], f"{key} 的说明没告诉用户 auto 是什么意思"

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
            "GALAXY_VOICE_DUPLEX": "1",
            "GALAXY_VOICE_DUCKING": "false",
            "GALAXY_VOICE_DUCK_GAIN": "0.4",
        }
        # 先让 monkeypatch 接管这几个环境变量,teardown 时整个还原。
        # update_config() 会把值写进 os.environ(生产上正该如此:面板改完立刻生效),
        # 而这里存的是一串"全部关掉"的假值 —— 不还原就会留在进程里,让后面每一条
        # 断言"AEC 默认开 / 双工默认关"的测试都看到被这个测试改过的世界。
        # 同 TestRealtimeKeyRoutesToSecretStore::test_saving_it_does_not_write_plaintext_env。
        for k in payload:
            monkeypatch.setenv(k, "unset-by-test")
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
        for key in ("GALAXY_AEC", "GALAXY_VOICE_DUPLEX", "GALAXY_VOICE_DUCK_GAIN", "GALAXY_AEC_RES"):
            assert key in items, f"/api/config/all 没返回 {key}"
            # string 也在内:三态开关(auto/1/0)本来就不是布尔,渲染成推拉开关会丢掉 auto 档。
            assert items[key]["type"] in ("boolean", "number", "string")
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
