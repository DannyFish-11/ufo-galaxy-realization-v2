#!/usr/bin/env python3
"""
Galaxy CLI
==============

命令行工具，提供便捷的技能和 MCP 管理

使用方法:
    galaxy skill install <name>      # 安装技能
    galaxy skill search <query>      # 搜索技能
    galaxy skill list               # 列出已安装技能
    galaxy skill create <name>      # 创建新技能
    
    galaxy mcp load <command>       # 加载 MCP 服务器
    galaxy mcp list                 # 列出已加载服务器
    galaxy mcp tools <server_id>    # 列出服务器工具
    
    ufo onboard                  # 安装向导
    ufo status                   # 系统状态
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional

# 添加项目路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class Colors:
    """终端颜色"""
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'


def print_success(msg: str):
    print(f"{Colors.GREEN}✅ {msg}{Colors.ENDC}")


def print_error(msg: str):
    print(f"{Colors.RED}❌ {msg}{Colors.ENDC}")


def print_info(msg: str):
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.ENDC}")


def print_step(msg: str):
    print(f"{Colors.CYAN}▶️  {msg}{Colors.ENDC}")


# ============================================================================
# Skill 命令
# ============================================================================

async def skill_install(name: str, source: str = None):
    """安装技能"""
    print_step(f"安装技能: {name}")
    
    try:
        from core.skill_loader import skill_loader
        
        # 如果是本地路径
        if source and (Path(source).exists() or source.startswith("./") or source.startswith("/")):
            result = await skill_loader.load(source, skill_id=name)
        else:
            # 从市场安装
            result = await install_from_market(name)
        
        if result.get("success"):
            print_success(f"技能已安装: {name}")
            print_info(f"描述: {result.get('description', 'N/A')}")
        else:
            print_error(f"安装失败: {result.get('error', '未知错误')}")
            
    except Exception as e:
        print_error(f"安装失败: {e}")


async def install_from_market(name: str) -> dict:
    """从市场安装技能"""
    # 查询市场 API
    import httpx
    
    market_url = os.environ.get("GALAXY_SKILL_MARKET", "https://skills.galaxy.ai")
    
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # 搜索技能
            response = await client.get(f"{market_url}/api/skills/{name}")
            
            if response.status_code == 200:
                skill_data = response.json()
                
                # 下载技能
                print_info(f"从市场下载: {skill_data.get('name', name)}")
                
                # 创建临时目录
                temp_dir = PROJECT_ROOT / "skills" / "installed" / name
                temp_dir.mkdir(parents=True, exist_ok=True)
                
                # 下载 SKILL.md
                skill_md_url = skill_data.get("download_url")
                if skill_md_url:
                    md_response = await client.get(skill_md_url)
                    if md_response.status_code == 200:
                        (temp_dir / "SKILL.md").write_text(md_response.text)
                        
                        # 加载技能
                        from core.skill_loader import skill_loader
                        return await skill_loader.load(str(temp_dir), skill_id=name)
                
                return {"success": False, "error": "下载失败"}
            else:
                return {"success": False, "error": f"技能不存在: {name}"}
                
    except Exception as e:
        return {"success": False, "error": f"市场连接失败: {e}"}


async def skill_search(query: str):
    """搜索技能"""
    print_step(f"搜索技能: {query}")
    
    try:
        # 先搜索本地
        from core.skill_loader import skill_loader
        local_results = skill_loader.search(query)
        
        if local_results:
            print_info(f"本地技能 ({len(local_results)} 个):")
            for skill in local_results:
                print(f"  • {skill['id']}: {skill['name']}")
        
        # 搜索市场
        import httpx
        market_url = os.environ.get("GALAXY_SKILL_MARKET", "https://skills.galaxy.ai")
        
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{market_url}/api/skills/search", params={"q": query})
                
                if response.status_code == 200:
                    market_results = response.json().get("skills", [])
                    
                    if market_results:
                        print_info(f"市场技能 ({len(market_results)} 个):")
                        for skill in market_results:
                            print(f"  • {skill['id']}: {skill['name']} - {skill.get('description', '')[:50]}")
                else:
                    print_info("无法连接到技能市场")
        except:
            print_info("无法连接到技能市场")
            
    except Exception as e:
        print_error(f"搜索失败: {e}")


async def skill_list():
    """列出已安装技能"""
    print_step("已安装技能:")
    
    try:
        from core.skill_loader import skill_loader
        skills = skill_loader.list_skills()
        
        if skills:
            for skill in skills:
                status = f"{Colors.GREEN}✓{Colors.ENDC}" if skill['status'] == 'loaded' else f"{Colors.RED}✗{Colors.ENDC}"
                print(f"  {status} {skill['id']}: {skill['name']} ({skill['version']})")
        else:
            print_info("没有已安装的技能")
            
    except Exception as e:
        print_error(f"获取失败: {e}")


async def skill_uninstall(name: str):
    """卸载技能"""
    print_step(f"卸载技能: {name}")
    
    try:
        from core.skill_loader import skill_loader
        result = await skill_loader.unload(name)
        
        if result.get("success"):
            print_success(f"技能已卸载: {name}")
        else:
            print_error(f"卸载失败: {result.get('error', '未知错误')}")
            
    except Exception as e:
        print_error(f"卸载失败: {e}")


async def skill_create(name: str):
    """创建新技能"""
    print_step(f"创建技能: {name}")
    
    skill_dir = PROJECT_ROOT / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    
    # 创建 SKILL.md 模板
    skill_md = f'''---
name: {name}
description: "技能描述"
version: "1.0.0"
author: ""
tags: []
---

# {name}

技能描述

## When to Use

✅ **USE this skill when:**
- 场景1
- 场景2

## When NOT to Use

❌ **DON'T use this skill when:**
- 场景1
- 场景2

## Commands

```bash
# 示例命令
echo "Hello from {name}"
```

## Examples

**用户: "示例请求"**

```bash
# 执行命令
echo "处理中..."
```
'''
    
    (skill_dir / "SKILL.md").write_text(skill_md)
    
    print_success(f"技能已创建: {skill_dir}")
    print_info("编辑 SKILL.md 来完善技能")


# ============================================================================
# MCP 命令
# ============================================================================

async def mcp_load(name: str, command: str, env: dict = None):
    """加载 MCP 服务器"""
    print_step(f"加载 MCP 服务器: {name}")
    print_info(f"命令: {command}")
    
    try:
        from core.mcp_loader import mcp_loader
        
        result = await mcp_loader.load(
            name=name,
            command=command,
            env=env or {},
            auto_start=True,
        )
        
        if result.get("success"):
            print_success(f"MCP 服务器已加载: {name}")
            print_info(f"服务器 ID: {result.get('server_id')}")
        else:
            print_error(f"加载失败: {result.get('error', '未知错误')}")
            
    except Exception as e:
        print_error(f"加载失败: {e}")


async def mcp_list():
    """列出已加载 MCP 服务器"""
    print_step("已加载 MCP 服务器:")
    
    try:
        from core.mcp_loader import mcp_loader
        servers = mcp_loader.list_servers()
        
        if servers:
            for server in servers:
                status_color = Colors.GREEN if server['status'] == 'running' else Colors.RED
                print(f"  {status_color}●{Colors.ENDC} {server['name']} ({server['id']})")
                print(f"      工具: {server['tools_count']} 个")
        else:
            print_info("没有已加载的 MCP 服务器")
            
    except Exception as e:
        print_error(f"获取失败: {e}")


async def mcp_tools(server_id: str):
    """列出 MCP 服务器的工具"""
    print_step(f"MCP 工具: {server_id}")
    
    try:
        from core.mcp_loader import mcp_loader
        tools = await mcp_loader.list_tools(server_id)
        
        if tools:
            for tool in tools:
                print(f"  • {tool['name']}")
                print(f"      {tool['description'][:60]}...")
        else:
            print_info("没有可用工具")
            
    except Exception as e:
        print_error(f"获取失败: {e}")


async def mcp_unload(server_id: str):
    """卸载 MCP 服务器"""
    print_step(f"卸载 MCP 服务器: {server_id}")
    
    try:
        from core.mcp_loader import mcp_loader
        result = await mcp_loader.unload(server_id)
        
        if result.get("success"):
            print_success(f"MCP 服务器已卸载: {server_id}")
        else:
            print_error(f"卸载失败: {result.get('error', '未知错误')}")
            
    except Exception as e:
        print_error(f"卸载失败: {e}")


# ============================================================================
# 系统命令
# ============================================================================

async def onboard():
    """安装向导"""
    print(f"""
{Colors.CYAN}{Colors.BOLD}
    ╔═══════════════════════════════════════════════════════════════╗
    ║                    Galaxy 安装向导                         ║
    ╚═══════════════════════════════════════════════════════════════╝
{Colors.ENDC}
""")
    
    print_step("Step 1: 检查环境")
    
    # 检查 Python
    print_info(f"Python: {sys.version.split()[0]}")
    
    # 检查 Node.js (MCP 需要)
    import subprocess
    try:
        result = subprocess.run(["node", "--version"], capture_output=True, text=True)
        if result.returncode == 0:
            print_info(f"Node.js: {result.stdout.strip()}")
        else:
            print_info("Node.js: 未安装 (MCP 服务器需要)")
    except:
        print_info("Node.js: 未安装 (MCP 服务器需要)")
    
    print()
    print_step("Step 2: 配置 API Key")
    
    # 检查 .env 文件
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        print_success(".env 文件已存在")
    else:
        print_info("创建 .env 文件...")
        env_example = PROJECT_ROOT / ".env.example"
        if env_example.exists():
            import shutil
            shutil.copy(env_example, env_file)
            print_success(".env 文件已创建，请编辑配置 API Key")
        else:
            # 创建默认 .env
            default_env = """# Galaxy 配置文件

# LLM API Keys (至少配置一个)
OPENAI_API_KEY=
GEMINI_API_KEY=
OPENROUTER_API_KEY=

# MCP 服务器
# GITHUB_TOKEN=your_github_token
# BRAVE_API_KEY=your_brave_api_key
"""
            env_file.write_text(default_env)
            print_success(".env 文件已创建，请编辑配置 API Key")
    
    print()
    print_step("Step 3: 安装示例技能")
    
    skills_dir = PROJECT_ROOT / "skills" / "examples"
    if skills_dir.exists():
        print_success(f"示例技能已存在: {skills_dir}")
    else:
        print_info("创建示例技能...")
        await skill_create("my-first-skill")
    
    print()
    print_success("安装向导完成!")
    print()
    print_info("下一步:")
    print("  1. 编辑 .env 文件配置 API Key")
    print("  2. 运行 'python main.py' 启动服务")
    print("  3. 访问 http://localhost:8080")


async def status():
    """系统状态"""
    print_step("系统状态")
    
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get("http://localhost:8080/health")
            
            if response.status_code == 200:
                print_success("服务运行中")
                data = response.json()
                print_info(f"状态: {data.get('status', 'unknown')}")
            else:
                print_error("服务异常")
    except:
        print_info("服务未运行")
    
    # 检查技能
    try:
        from core.skill_loader import skill_loader
        skills = skill_loader.list_skills()
        print_info(f"已加载技能: {len(skills)} 个")
    except:
        pass
    
    # 检查 MCP
    try:
        from core.mcp_loader import mcp_loader
        servers = mcp_loader.list_servers()
        print_info(f"已加载 MCP: {len(servers)} 个")
    except:
        pass


# ============================================================================
# 主函数
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="Galaxy CLI - 智能体操作系统命令行工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    
    subparsers = parser.add_subparsers(dest="command", help="命令")
    
    # skill 命令
    skill_parser = subparsers.add_parser("skill", help="技能管理")
    skill_subparsers = skill_parser.add_subparsers(dest="skill_command")
    
    # skill install
    install_parser = skill_subparsers.add_parser("install", help="安装技能")
    install_parser.add_argument("name", help="技能名称")
    install_parser.add_argument("--source", "-s", help="技能来源路径")
    
    # skill search
    search_parser = skill_subparsers.add_parser("search", help="搜索技能")
    search_parser.add_argument("query", help="搜索关键词")
    
    # skill list
    skill_subparsers.add_parser("list", help="列出已安装技能")
    
    # skill uninstall
    uninstall_parser = skill_subparsers.add_parser("uninstall", help="卸载技能")
    uninstall_parser.add_argument("name", help="技能名称")
    
    # skill create
    create_parser = skill_subparsers.add_parser("create", help="创建新技能")
    create_parser.add_argument("name", help="技能名称")
    
    # mcp 命令
    mcp_parser = subparsers.add_parser("mcp", help="MCP 服务器管理")
    mcp_subparsers = mcp_parser.add_subparsers(dest="mcp_command")
    
    # mcp load
    mcp_load_parser = mcp_subparsers.add_parser("load", help="加载 MCP 服务器")
    mcp_load_parser.add_argument("name", help="服务器名称")
    mcp_load_parser.add_argument("command", help="启动命令")
    mcp_load_parser.add_argument("--env", "-e", help="环境变量 (JSON 格式)")
    
    # mcp list
    mcp_subparsers.add_parser("list", help="列出已加载服务器")
    
    # mcp tools
    tools_parser = mcp_subparsers.add_parser("tools", help="列出服务器工具")
    tools_parser.add_argument("server_id", help="服务器 ID")
    
    # mcp unload
    mcp_unload_parser = mcp_subparsers.add_parser("unload", help="卸载服务器")
    mcp_unload_parser.add_argument("server_id", help="服务器 ID")
    
    # 系统命令
    subparsers.add_parser("onboard", help="安装向导")
    subparsers.add_parser("status", help="系统状态")
    
    args = parser.parse_args()
    
    # 执行命令
    if args.command == "skill":
        if args.skill_command == "install":
            asyncio.run(skill_install(args.name, args.source))
        elif args.skill_command == "search":
            asyncio.run(skill_search(args.query))
        elif args.skill_command == "list":
            asyncio.run(skill_list())
        elif args.skill_command == "uninstall":
            asyncio.run(skill_uninstall(args.name))
        elif args.skill_command == "create":
            asyncio.run(skill_create(args.name))
        else:
            skill_parser.print_help()
    
    elif args.command == "mcp":
        if args.mcp_command == "load":
            env = json.loads(args.env) if args.env else None
            asyncio.run(mcp_load(args.name, args.command, env))
        elif args.mcp_command == "list":
            asyncio.run(mcp_list())
        elif args.mcp_command == "tools":
            asyncio.run(mcp_tools(args.server_id))
        elif args.mcp_command == "unload":
            asyncio.run(mcp_unload(args.server_id))
        else:
            mcp_parser.print_help()
    
    elif args.command == "onboard":
        asyncio.run(onboard())
    
    elif args.command == "status":
        asyncio.run(status())
    
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
