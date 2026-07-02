"""tests/test_local_brain_ollama_readiness.py
================================================
真机复现(Windows):Phase 0 明确打印"✓ Ollama 已安装"(shutil.which("ollama")
命中),但几分钟后启动"AI 大脑"阶段却打印:
    模型加载失败 [transformers]: gemma4:latest, 尝试 Ollama 回退
    Auto-install Ollama failed: HTTP Error 404: Not Found
    Ollama 不可用（未安装或未运行）。请安装: https://ollama.com/download

根因(见 core/local_brain_manager.py::_ensure_ollama_running/_auto_install_ollama):
1. `shutil.which("ollama")` 的检测结果只在 `_start_ollama()` 内部用来决定要不要
   `Popen(["ollama","serve"])`，返回值本身从未被读取来区分"命令根本不存在"和
   "命令存在、服务只是没在限定时间内响应"——无论哪种情况，10 秒重试预算耗尽后
   都无条件走到"Auto-install"分支，对着明明已经装了 Ollama 的机器去尝试
   "自动安装"，产生自相矛盾的日志和误导性提示。
2. Windows 的自动安装从 GitHub Releases 下载一个早已不存在的文件名
   ("ollama-windows-amd64.exe")，必然 404。

本文件验证修复:
- ollama 命令存在但服务迟迟不响应时，不应该再尝试"自动安装"。
- ollama 命令确实不存在时，才会走自动安装分支。
- Windows 下的自动安装不再尝试下载，直接快速返回 False（不再产生 404）。
- 失败提示文案会根据"命令是否存在"给出不同、准确的措辞。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.local_brain_manager import LocalBrainManager, LocalBrainStatus


@pytest.fixture
def manager():
    return LocalBrainManager(backend="ollama", ollama_url="http://localhost:11434")


class TestEnsureOllamaRunningSkipsAutoInstallWhenBinaryExists:
    @pytest.mark.asyncio
    async def test_auto_install_not_attempted_when_ollama_command_found(self, manager):
        """命令存在(shutil.which 命中)但服务一直没响应时，不该再去"自动安装"。"""
        with patch("core.local_brain_manager.shutil.which", return_value="/usr/bin/ollama"), \
             patch.object(manager, "_ping_ollama", new=AsyncMock(return_value=False)), \
             patch.object(manager, "_start_ollama", new=AsyncMock(return_value=True)), \
             patch.object(manager, "_auto_install_ollama", new=AsyncMock(return_value=False)) as mock_install, \
             patch("core.local_brain_manager.asyncio.sleep", new=AsyncMock()):
            result = await manager._ensure_ollama_running()

        assert result is False
        assert manager._status == LocalBrainStatus.UNAVAILABLE
        mock_install.assert_not_called(), "ollama 命令明明存在，不该再尝试自动安装"

    @pytest.mark.asyncio
    async def test_auto_install_attempted_when_ollama_command_missing(self, manager):
        """命令确实不存在时，才应该走自动安装分支。"""
        with patch("core.local_brain_manager.shutil.which", return_value=None), \
             patch.object(manager, "_ping_ollama", new=AsyncMock(return_value=False)), \
             patch.object(manager, "_start_ollama", new=AsyncMock(return_value=False)), \
             patch.object(manager, "_auto_install_ollama", new=AsyncMock(return_value=False)) as mock_install, \
             patch("core.local_brain_manager.asyncio.sleep", new=AsyncMock()):
            result = await manager._ensure_ollama_running()

        assert result is False
        mock_install.assert_called_once()

    @pytest.mark.asyncio
    async def test_failure_message_distinguishes_installed_vs_missing(self, manager, caplog):
        """日志文案必须准确区分"已安装但服务没起来"与"确实没装"，不能都说"未安装"。"""
        import logging
        caplog.set_level(logging.WARNING, logger="Galaxy.LocalBrain")

        with patch("core.local_brain_manager.shutil.which", return_value="/usr/bin/ollama"), \
             patch.object(manager, "_ping_ollama", new=AsyncMock(return_value=False)), \
             patch.object(manager, "_start_ollama", new=AsyncMock(return_value=True)), \
             patch("core.local_brain_manager.asyncio.sleep", new=AsyncMock()):
            await manager._ensure_ollama_running()

        messages = " ".join(r.message for r in caplog.records)
        assert "已安装" in messages and "未安装" not in messages, (
            f"命令明明存在，日志不该说\"未安装\"（误导用户）: {messages}"
        )


class TestAutoInstallOllamaWindowsNoLongerAttemptsBrokenDownload:
    @pytest.mark.asyncio
    async def test_windows_returns_false_fast_without_network_call(self, manager):
        """修复:Windows 分支之前会 urlretrieve 一个已 404 的 URL——现在应该直接
        快速返回 False，不再发起任何下载请求。"""
        with patch("platform.system", return_value="Windows"), \
             patch("urllib.request.urlretrieve") as mock_urlretrieve:
            result = await manager._auto_install_ollama()

        assert result is False
        mock_urlretrieve.assert_not_called(), "不应再尝试下载已确认失效的安装包 URL"
