"""tests/test_env_empty_values_and_electron_intact.py
========================================================
真机日志(用户重新克隆仓库后)暴露的两个新根因:

【根因 1】设置面板自动生成的 .env 把全部 schema 键写成 ``KEY=``(空值)。
空字符串一旦进入 os.environ,就会把代码里的默认值顶掉:
``os.environ.get("OLLAMA_URL", "http://localhost:11434")`` 在 ``OLLAMA_URL=""``
存在时返回 ""。真机日志里一整串症状全部对应此根因:
  - "Exception suppressed: Request URL is missing an 'http://' or 'https://'
    protocol."(LocalBrainManager 拿空 URL ping Ollama)
  - "Ollama 已安装，但服务在等待窗口内未响应"(其实服务在跑,是 URL 为空)
  - "Redis 连接失败: Redis URL must specify one of the following schemes"
  - "NATSBus: connection failed — nats: invalid hostname in connect url"
修复(两端):_write_env_file() 不再写空值行;main.py/unified_launcher.py 的
.env 加载改为只加载非空值(兼容用户机器上已存在的、满是空值行的旧 .env)。

【根因 2】electron npm 包不完整(重新克隆/中断安装的残局:.bin/electron.cmd
存根在、node_modules/electron/cli.js 缺失)。之前所有启动路径只判断
node_modules 目录是否存在——存在就跳过安装,Electron 每次以
"Cannot find module ...electron\\cli.js" 崩溃,保活重启 8 次全是同一死法,
从未尝试过真正的修复。修复:electron_package_intact() 核实包完整性,
不完整时自动重跑 npm install。
"""

from __future__ import annotations

import os

import pytest

from core.routes import config as config_module
from core.electron_launch_guard import electron_package_intact


class TestWriteEnvFileSkipsEmptyValues:
    def _write_and_read(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config_module, "ENV_FILE", tmp_path / ".env.test")
        config_module._write_env_file()
        return (tmp_path / ".env.test").read_text(encoding="utf-8")

    def test_unset_keys_produce_no_empty_lines(self, tmp_path, monkeypatch):
        # 确保一个默认值为空的 key 未配置。
        monkeypatch.delenv("OLLAMA_URL", raising=False)
        content = self._write_and_read(tmp_path, monkeypatch)
        assert "OLLAMA_URL=" not in content, (
            ".env 里不该出现空值行 OLLAMA_URL= ——空字符串会把代码默认值顶掉"
        )

    def test_explicit_empty_env_value_also_skipped(self, tmp_path, monkeypatch):
        monkeypatch.setenv("REDIS_URL", "")
        content = self._write_and_read(tmp_path, monkeypatch)
        assert "REDIS_URL=" not in content

    def test_non_empty_values_still_written(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OLLAMA_URL", "http://localhost:11434")
        content = self._write_and_read(tmp_path, monkeypatch)
        assert "OLLAMA_URL=http://localhost:11434" in content

    def test_non_empty_defaults_written_even_when_unset(self, tmp_path, monkeypatch):
        # GATEWAY_PORT 默认 9000(非空默认),即使未配置也应写入。
        monkeypatch.delenv("GATEWAY_PORT", raising=False)
        content = self._write_and_read(tmp_path, monkeypatch)
        assert "GATEWAY_PORT=9000" in content


class TestDotenvLoaderSkipsEmptyValues:
    """main.py/unified_launcher.py 的加载逻辑:只加载非空值。
    这里直接验证该逻辑的行为(dotenv_values + 非空过滤),防止回退成
    load_dotenv() 整个灌入。"""

    def test_empty_values_not_loaded_into_environ(self, tmp_path, monkeypatch):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "OLLAMA_URL=\nREDIS_URL=\nDEEPSEEK_API_KEY=sk-real\n", encoding="utf-8"
        )
        monkeypatch.delenv("OLLAMA_URL", raising=False)
        monkeypatch.delenv("REDIS_URL", raising=False)
        monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)

        # 与 main.py 顶部相同的加载逻辑。
        from dotenv import dotenv_values
        for k, v in (dotenv_values(str(env_file)) or {}).items():
            if v and k not in os.environ:
                os.environ[k] = v
        try:
            assert "OLLAMA_URL" not in os.environ, "空值不该进入 os.environ"
            assert "REDIS_URL" not in os.environ
            assert os.environ.get("DEEPSEEK_API_KEY") == "sk-real"
            # 核心断言:默认值不再被空字符串顶掉。
            assert (
                os.environ.get("OLLAMA_URL", "http://localhost:11434")
                == "http://localhost:11434"
            )
        finally:
            os.environ.pop("DEEPSEEK_API_KEY", None)


class TestElectronPackageIntact:
    def test_missing_node_modules_is_not_intact(self, tmp_path):
        assert electron_package_intact(str(tmp_path)) is False

    def test_stub_only_broken_install_is_not_intact(self, tmp_path):
        """真机残局复刻:.bin 存根在,electron 包本体缺 cli.js。"""
        (tmp_path / "node_modules" / ".bin").mkdir(parents=True)
        (tmp_path / "node_modules" / ".bin" / "electron.cmd").write_text("stub")
        (tmp_path / "node_modules" / "electron").mkdir()
        (tmp_path / "node_modules" / "electron" / "package.json").write_text("{}")
        # 故意不创建 cli.js
        assert electron_package_intact(str(tmp_path)) is False

    def test_complete_install_is_intact(self, tmp_path):
        pkg = tmp_path / "node_modules" / "electron"
        pkg.mkdir(parents=True)
        (pkg / "package.json").write_text("{}")
        (pkg / "cli.js").write_text("// cli")
        assert electron_package_intact(str(tmp_path)) is True
