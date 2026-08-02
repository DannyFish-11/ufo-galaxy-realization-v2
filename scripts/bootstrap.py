#!/usr/bin/env python3
"""
scripts/bootstrap.py — Galaxy 一键初始化（跨平台）
==================================================

让「克隆 → 安装」这一步真正可用。INSTALL.md 第 2 步引用本脚本。

自动完成：
  1. 校验 Python 版本（>= 3.10）
  2. 创建虚拟环境 .venv（除非 --no-venv）
  3. 安装 Python 依赖（requirements.txt）
  4. 若缺失则从 .env.example 生成 .env
  5. 确保 config/ 目录存在

NATS / Docker 基础设施 / 系统预检由 `python main.py` 在运行时处理
（见 unified_launcher 的 Phase 3.5 Docker 与 Phase 4 消息总线），此处不重复。

用法::

    python scripts/bootstrap.py            # 创建 .venv 并安装依赖
    python scripts/bootstrap.py --no-venv  # 安装到当前解释器（不建 venv）
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MIN_PY = (3, 10)


def _ok(msg: str) -> None:
    print(f"  [OK]   {msg}")


def _info(msg: str) -> None:
    print(f"  [INFO] {msg}")


def _err(msg: str) -> None:
    print(f"  [ERR]  {msg}", file=sys.stderr)


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def check_python() -> None:
    _section("1/5 Python 版本")
    if sys.version_info < MIN_PY:
        _err(f"需要 Python {MIN_PY[0]}.{MIN_PY[1]}+，当前 {sys.version.split()[0]}")
        sys.exit(1)
    _ok(f"Python {sys.version.split()[0]}")


def ensure_venv(venv_dir: Path, use_venv: bool) -> Path:
    """返回用于安装的 python 解释器路径。"""
    _section("2/5 虚拟环境")
    if not use_venv:
        _info("--no-venv：安装到当前解释器")
        return Path(sys.executable)

    py = _venv_python(venv_dir)
    if py.exists():
        _ok(f"复用已存在的虚拟环境 {venv_dir.name}")
        return py

    _info(f"创建虚拟环境 {venv_dir} …")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
    except subprocess.CalledProcessError as exc:
        _err(f"创建 venv 失败：{exc}；回退到当前解释器")
        return Path(sys.executable)
    py = _venv_python(venv_dir)
    if not py.exists():
        _err("venv 创建后未找到 python，回退到当前解释器")
        return Path(sys.executable)
    _ok(f"虚拟环境就绪 {venv_dir.name}")
    return py


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


# 弱网加固:默认源失败后逐个回退国内镜像(与 main.py Phase 2 同一套候选)。
PIP_INDEX_CANDIDATES: list = [
    None,  # 默认源(尊重用户已配置的 pip.conf / 环境)
    "https://pypi.tuna.tsinghua.edu.cn/simple",
    "https://mirrors.aliyun.com/pypi/simple/",
]


def install_deps(python_exe: Path) -> None:
    _section("3/5 安装依赖")
    req = PROJECT_ROOT / "requirements.txt"
    if not req.exists():
        _err(f"未找到 {req}")
        sys.exit(1)
    subprocess.run([str(python_exe), "-m", "pip", "install", "--upgrade", "pip"], check=False)
    base = [str(python_exe), "-m", "pip", "install", "--retries", "3", "--timeout", "60", "-r", str(req)]
    for idx, index_url in enumerate(PIP_INDEX_CANDIDATES):
        cmd = base + (["-i", index_url] if index_url else [])
        if index_url:
            _info(f"回退镜像源 {idx}/{len(PIP_INDEX_CANDIDATES) - 1}: {index_url}")
        try:
            subprocess.run(cmd, check=True)
            _ok("requirements.txt 已安装")
            return
        except subprocess.CalledProcessError as exc:
            _err(f"pip install 失败：{exc}")
    _err("默认源与国内镜像均失败，请检查网络后重试")
    sys.exit(1)


def ensure_env_file() -> None:
    _section("4/5 .env 配置")
    env = PROJECT_ROOT / ".env"
    example = PROJECT_ROOT / ".env.example"
    if env.exists():
        _ok(".env 已存在（跳过）")
        return
    if example.exists():
        shutil.copyfile(example, env)
        _ok("已从 .env.example 生成 .env —— 请填入至少一个 LLM API Key")
    else:
        _info("无 .env.example，跳过（main.py 可在无 Key 时以本地模型运行）")


def ensure_config_dir() -> None:
    _section("5/5 config 目录")
    cfg = PROJECT_ROOT / "config"
    cfg.mkdir(exist_ok=True)
    _ok(f"{cfg.name}/ 就绪")


def print_next_steps(python_exe: Path, used_venv: bool, venv_dir: Path) -> None:
    print("\n" + "=" * 60)
    print("  初始化完成 ✅  下一步：")
    print("=" * 60)
    if used_venv and python_exe != Path(sys.executable):
        if os.name == "nt":
            print(f"  1) 激活虚拟环境:  .\\{venv_dir.name}\\Scripts\\activate")
        else:
            print(f"  1) 激活虚拟环境:  source {venv_dir.name}/bin/activate")
        print("  2) 启动系统:      python main.py")
    else:
        print("  启动系统:  python main.py")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Galaxy 一键初始化")
    parser.add_argument("--no-venv", action="store_true", help="安装到当前解释器，不创建 .venv")
    parser.add_argument("--venv-dir", default=".venv", help="虚拟环境目录名（默认 .venv）")
    args = parser.parse_args()

    print("Galaxy bootstrap — 克隆到可运行的一键初始化")
    check_python()
    venv_dir = (PROJECT_ROOT / args.venv_dir).resolve()
    python_exe = ensure_venv(venv_dir, use_venv=not args.no_venv)
    install_deps(python_exe)
    ensure_env_file()
    ensure_config_dir()
    print_next_steps(python_exe, used_venv=not args.no_venv, venv_dir=venv_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
