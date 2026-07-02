"""tests/test_ollama_version_check.py
=======================================
回归防护:检测 Ollama 客户端版本是否太旧、无法解析 gemma4 系列的 manifest。

联网核实(多个独立来源一致印证，非单一文本搜索命中):open-webui issue #23471
《Gemma4 requires a newer version of Ollama》、社区排障笔记(标题直接是"cannot
pull Gemma4 12B"的版本问题)、Ollama 版本变更记录里持续出现的 gemma4 相关
修复——一致指向:gemma4 系列需要 Ollama ≥ 0.22 才能解析其 manifest，旧版会在
"pulling manifest" 阶段就失败。用户实测到的现象(Ollama 0.14.1，拉取
gemma4:e2b 卡在 "pulling manifest" 就没了)与此完全吻合。
"""

from __future__ import annotations

from core.model_selection import (
    MIN_OLLAMA_VERSION_FOR_GEMMA4,
    is_ollama_version_too_old,
    parse_ollama_version,
)


class TestParseOllamaVersion:
    def test_parses_standard_output_format(self):
        assert parse_ollama_version("ollama version is 0.14.1") == (0, 14, 1)

    def test_parses_bare_version_string(self):
        assert parse_ollama_version("0.30.8") == (0, 30, 8)

    def test_returns_none_for_unparseable_input(self):
        assert parse_ollama_version("command not found") is None
        assert parse_ollama_version("") is None
        assert parse_ollama_version(None) is None  # type: ignore[arg-type]


class TestIsOllamaVersionTooOld:
    def test_user_reported_version_is_too_old(self):
        """用户真机实测版本(0.14.1)必须被判定为太旧——这是本次修复要解决的确切场景。"""
        assert is_ollama_version_too_old("ollama version is 0.14.1") is True

    def test_current_stable_is_not_too_old(self):
        assert is_ollama_version_too_old("ollama version is 0.30.8") is False

    def test_exact_minimum_version_is_not_too_old(self):
        boundary = ".".join(map(str, MIN_OLLAMA_VERSION_FOR_GEMMA4))
        assert is_ollama_version_too_old(f"ollama version is {boundary}") is False

    def test_just_below_minimum_is_too_old(self):
        major, minor, patch = MIN_OLLAMA_VERSION_FOR_GEMMA4
        just_below = f"{major}.{minor}.{max(0, patch - 1)}" if patch > 0 else f"{major}.{max(0, minor-1)}.9"
        result = is_ollama_version_too_old(f"ollama version is {just_below}")
        assert result is True

    def test_unparseable_version_returns_none_not_a_guess(self):
        """解析不出版本号时必须返回 None(未知)，不能瞎猜 True/False。"""
        assert is_ollama_version_too_old("") is None
        assert is_ollama_version_too_old("unexpected output") is None
