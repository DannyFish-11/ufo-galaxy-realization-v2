"""统一的配置开关读取,以及它顺带修掉的一个真 bug:空值会把开关打开。

被修的 bug
----------
语音栈里有 **5 份逐字相同**的 ``_flag()``,实现都是::

    os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off")

``os.getenv(name, default)`` 的 default **只在变量不存在时生效**;变量存在但值为空串时
返回 ``""``,而 ``"".strip().lower()`` 不在那个假值元组里 → 返回 ``True``。于是::

    GALAXY_VOICE_DUPLEX=        # 空值

会把一个**默认关闭**的开关打开。

为什么这不是纸上推演
--------------------
``main.py`` 顶部注释自己写着:设置面板自动生成的 ``.env`` 会把**全部** schema 键写成
``KEY=``(空值)。``main.py`` 做了防护(只注入非空值),但那个防护**只在 main.py 里**。
凡是别的途径把 ``.env`` 灌进环境的部署方式都会中招,而它们恰恰是最常见的:

* Docker Compose 的 ``env_file:``
* systemd 的 ``EnvironmentFile=``
* ``set -a; . .env; set +a``

这几种都会把空值原样设进环境 —— 表现就是"面板上明明关着的开关,部署到容器里自己开了"。

判定这是遗漏而非有意
--------------------
**同文件里的 ``_num()`` 处理了这个情况**(``if raw is None or not raw.strip()``)。
同一个作者在数值那边想到了,在布尔那边漏了。5 份副本意味着这个 bug 要修 5 遍 —— 这正是
把它收敛成一处的实际收益,而不只是"少几行重复"。
"""

from __future__ import annotations

import pytest

from core.config_flags import flag, integer, num, text


class TestEmptyValueIsTreatedAsUnset:
    """本模块存在的首要理由。"""

    def test_empty_string_does_not_turn_a_default_off_flag_on(self, monkeypatch):
        """核心复现:默认关 + 空值 → 必须仍是关。旧实现在这里返回 True。"""
        monkeypatch.setenv("GALAXY_TEST_FLAG", "")
        assert flag("GALAXY_TEST_FLAG", False) is False

    def test_whitespace_only_also_counts_as_unset(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TEST_FLAG", "   ")
        assert flag("GALAXY_TEST_FLAG", False) is False

    def test_empty_string_does_not_turn_a_default_on_flag_off(self, monkeypatch):
        """反方向也要对:默认开 + 空值 → 仍是开(空值就是"没说",不是"关")。"""
        monkeypatch.setenv("GALAXY_TEST_FLAG", "")
        assert flag("GALAXY_TEST_FLAG", True) is True

    def test_the_old_implementation_really_had_this_bug(self, monkeypatch):
        """把旧写法原样放在这里跑一遍,证明这个 bug 真的存在过 —— 不是我臆想出来的。

        没有这条,上面那些断言只能说明"新实现是对的",无法说明"旧实现是错的"。
        """
        import os

        monkeypatch.setenv("GALAXY_TEST_FLAG", "")

        def old_flag(name: str, default: str = "0") -> bool:
            return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off")

        assert old_flag("GALAXY_TEST_FLAG", "0") is True, "旧实现居然没这个 bug?那本次改动的前提就错了"
        assert flag("GALAXY_TEST_FLAG", False) is False, "新实现没修好"


class TestFlagParsing:
    @pytest.mark.parametrize("raw", ["1", "true", "TRUE", "yes", "on", "y", "t", " true "])
    def test_truthy(self, monkeypatch, raw):
        monkeypatch.setenv("GALAXY_TEST_FLAG", raw)
        assert flag("GALAXY_TEST_FLAG", False) is True

    @pytest.mark.parametrize("raw", ["0", "false", "FALSE", "no", "off", "n", "f", " 0 "])
    def test_falsy(self, monkeypatch, raw):
        monkeypatch.setenv("GALAXY_TEST_FLAG", raw)
        assert flag("GALAXY_TEST_FLAG", True) is False

    def test_unrecognised_value_falls_back_to_default_with_a_warning(self, monkeypatch, caplog):
        """拼错的值(``flase``)必须退回默认并告警,不能静默当成"开"。

        旧实现是"只要不是那 4 个假值就算开",于是 ``GALAXY_AEC=flase`` 会静默生效成
        "开" —— 那是最难发现的一类配置错误:用户以为自己关掉了。
        """
        import logging

        monkeypatch.setenv("GALAXY_TEST_FLAG", "flase")
        with caplog.at_level(logging.WARNING, logger="Galaxy.ConfigFlags"):
            assert flag("GALAXY_TEST_FLAG", False) is False
        assert any("flase" in r.getMessage() for r in caplog.records), "没有告警,配置错误被静默吞了"

    def test_old_implementation_silently_accepted_typos(self, monkeypatch):
        """对照:证明"拼错静默变开"在旧实现里是真的。"""
        import os

        monkeypatch.setenv("GALAXY_TEST_FLAG", "flase")

        def old_flag(name: str, default: str = "0") -> bool:
            return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off")

        assert old_flag("GALAXY_TEST_FLAG", "0") is True

    def test_string_defaults_still_work(self, monkeypatch):
        """兼容既有调用点的 ``"0"``/``"1"`` 写法 —— 否则这次收敛就得顺手改一堆调用处,
        把纯重构变成有风险的批量改动。"""
        monkeypatch.delenv("GALAXY_TEST_FLAG", raising=False)
        assert flag("GALAXY_TEST_FLAG", "1") is True
        assert flag("GALAXY_TEST_FLAG", "0") is False


class TestNum:
    def test_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("GALAXY_TEST_NUM", raising=False)
        assert num("GALAXY_TEST_NUM", 1.5) == 1.5

    def test_empty_is_unset(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TEST_NUM", "")
        assert num("GALAXY_TEST_NUM", 1.5) == 1.5

    def test_parses(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TEST_NUM", "2.75")
        assert num("GALAXY_TEST_NUM", 1.0) == 2.75

    def test_invalid_falls_back_with_warning(self, monkeypatch, caplog):
        import logging

        monkeypatch.setenv("GALAXY_TEST_NUM", "abc")
        with caplog.at_level(logging.WARNING, logger="Galaxy.ConfigFlags"):
            assert num("GALAXY_TEST_NUM", 1.0) == 1.0
        assert caplog.records, "非法数值必须告警"

    def test_clamping(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TEST_NUM", "5")
        assert num("GALAXY_TEST_NUM", 0.5, lo=0.0, hi=1.0) == 1.0
        monkeypatch.setenv("GALAXY_TEST_NUM", "-5")
        assert num("GALAXY_TEST_NUM", 0.5, lo=0.0, hi=1.0) == 0.0

    def test_integer_helper(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TEST_NUM", "7.9")
        assert integer("GALAXY_TEST_NUM", 1) == 7
        monkeypatch.setenv("GALAXY_TEST_NUM", "")
        assert integer("GALAXY_TEST_NUM", 3) == 3

    def test_text_helper(self, monkeypatch):
        monkeypatch.setenv("GALAXY_TEST_TXT", "  hello  ")
        assert text("GALAXY_TEST_TXT", "d") == "hello"
        monkeypatch.setenv("GALAXY_TEST_TXT", "   ")
        assert text("GALAXY_TEST_TXT", "d") == "d"


class TestNoDuplicateHelpersRemain:
    """收敛必须是真的收敛 —— 不能留着副本继续各自演化。"""

    MODULES = (
        "core/voice_duplex_session.py",
        "core/voice_dialog_policy.py",
        "core/voice_echo_guard.py",
        "core/multimodal/acoustic_echo_canceller.py",
        "core/multimodal/system_audio_capture_service.py",
    )

    @pytest.mark.parametrize("rel", MODULES)
    def test_no_local_flag_definition(self, rel):
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")
        assert "def _flag(" not in src, f"{rel} 还留着本地 _flag 副本"

    @pytest.mark.parametrize("rel", ("core/voice_echo_guard.py", "core/multimodal/acoustic_echo_canceller.py"))
    def test_no_local_num_definition(self, rel):
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")
        assert "def _num(" not in src, f"{rel} 还留着本地 _num 副本"

    @pytest.mark.parametrize("rel", MODULES)
    def test_they_import_the_shared_one(self, rel):
        from pathlib import Path

        src = (Path(__file__).resolve().parent.parent / rel).read_text(encoding="utf-8")
        assert "from core.config_flags import" in src, f"{rel} 没有引用共享实现"


class TestVoiceSwitchesStillBehaveTheSame:
    """收敛不能改变既有默认值 —— 这是纯重构 + 一处 bug 修复,不是行为变更。"""

    def test_defaults_unchanged(self, monkeypatch):
        for k in (
            "GALAXY_AEC",
            "GALAXY_VOICE_ECHO_GUARD",
            "GALAXY_VOICE_BACKCHANNEL_TOLERANCE",
            "GALAXY_SYSTEM_AUDIO_CAPTURE",
            "GALAXY_VOICE_DUPLEX",
            "GALAXY_VOICE_DUCKING",
        ):
            monkeypatch.delenv(k, raising=False)

        from core.multimodal.acoustic_echo_canceller import enabled as aec_enabled
        from core.multimodal.system_audio_capture_service import enabled as capture_enabled
        from core.voice_dialog_policy import backchannel_tolerance_enabled
        from core.voice_duplex_session import ducking_enabled, duplex_enabled
        from core.voice_echo_guard import enabled as echo_enabled

        assert aec_enabled() is True
        assert echo_enabled() is True
        assert backchannel_tolerance_enabled() is True
        assert capture_enabled() is True
        assert duplex_enabled() is False  # 唯一默认关闭的那个
        assert ducking_enabled() is True

    def test_empty_env_no_longer_flips_duplex_on(self, monkeypatch):
        """把这个 bug 落到最要紧的那个开关上:双工默认关,空值不得把它打开。

        双工被误开的后果不是小事 —— 它会尝试连云端 realtime 端点。
        """
        from core.voice_duplex_session import duplex_enabled

        monkeypatch.setenv("GALAXY_VOICE_DUPLEX", "")
        assert duplex_enabled() is False

    def test_numeric_defaults_unchanged(self, monkeypatch):
        for k in ("GALAXY_VOICE_ECHO_SIM", "GALAXY_VOICE_ECHO_TAIL_S", "GALAXY_AEC_MU"):
            monkeypatch.delenv(k, raising=False)

        from core.multimodal.acoustic_echo_canceller import _num as aec_num
        from core.voice_echo_guard import similarity_threshold, tail_seconds

        assert similarity_threshold() == 0.62
        assert tail_seconds() == 6.0
        assert aec_num("GALAXY_AEC_MU", 0.35) == 0.35
