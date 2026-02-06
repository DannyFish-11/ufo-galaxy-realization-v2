#!/usr/bin/env python3
"""
UFO Galaxy - API 配置向导
==========================
便捷的交互式配置工具，帮助用户快速配置系统所需的 API 和服务。

功能：
1. 自动检测已有的 API Key
2. 交互式配置向导
3. 自动验证 API 可用性
4. 生成 .env 配置文件
5. 一键测试所有服务
"""

import os
import sys
import json
import asyncio
import aiohttp
from pathlib import Path
from typing import Dict, Optional, Tuple, List
from dataclasses import dataclass
from enum import Enum

# 颜色输出
class Colors:
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def print_color(text: str, color: str = Colors.ENDC):
    """彩色输出"""
    print(f"{color}{text}{Colors.ENDC}")

def print_header(text: str):
    """打印标题"""
    print()
    print_color("=" * 60, Colors.CYAN)
    print_color(f"  {text}", Colors.BOLD + Colors.CYAN)
    print_color("=" * 60, Colors.CYAN)
    print()

def print_success(text: str):
    print_color(f"✅ {text}", Colors.GREEN)

def print_error(text: str):
    print_color(f"❌ {text}", Colors.RED)

def print_warning(text: str):
    print_color(f"⚠️  {text}", Colors.YELLOW)

def print_info(text: str):
    print_color(f"ℹ️  {text}", Colors.BLUE)


class Priority(Enum):
    """配置优先级"""
    P0 = "必需"  # 系统运行必需
    P1 = "推荐"  # 功能增强
    P2 = "可选"  # 高级功能


@dataclass
class APIConfig:
    """API 配置项"""
    name: str
    env_var: str
    description: str
    priority: Priority
    test_url: Optional[str] = None
    test_method: str = "GET"
    category: str = "其他"
    get_url: str = ""


# 所有 API 配置项
API_CONFIGS: List[APIConfig] = [
    # P0 - LLM API（至少需要一个）
    APIConfig(
        name="OpenAI",
        env_var="OPENAI_API_KEY",
        description="GPT-4/GPT-5 代码生成和对话",
        priority=Priority.P0,
        test_url="https://api.openai.com/v1/models",
        category="LLM",
        get_url="https://platform.openai.com/api-keys"
    ),
    APIConfig(
        name="Anthropic Claude",
        env_var="ANTHROPIC_API_KEY",
        description="Claude 3.5/4 代码生成和对话",
        priority=Priority.P0,
        test_url="https://api.anthropic.com/v1/messages",
        category="LLM",
        get_url="https://console.anthropic.com/"
    ),
    APIConfig(
        name="Google Gemini",
        env_var="GEMINI_API_KEY",
        description="Gemini 2.5 多模态和代码生成",
        priority=Priority.P0,
        test_url="https://generativelanguage.googleapis.com/v1/models",
        category="LLM",
        get_url="https://aistudio.google.com/apikey"
    ),
    APIConfig(
        name="DeepSeek",
        env_var="DEEPSEEK_API_KEY",
        description="DeepSeek V3 代码生成（性价比高）",
        priority=Priority.P0,
        test_url="https://api.deepseek.com/v1/models",
        category="LLM",
        get_url="https://platform.deepseek.com/"
    ),
    APIConfig(
        name="OpenRouter",
        env_var="OPENROUTER_API_KEY",
        description="统一多模型网关（推荐）",
        priority=Priority.P0,
        test_url="https://openrouter.ai/api/v1/models",
        category="LLM",
        get_url="https://openrouter.ai/keys"
    ),
    APIConfig(
        name="XAI Grok",
        env_var="XAI_API_KEY",
        description="Grok 4 代码生成和推理",
        priority=Priority.P0,
        category="LLM",
        get_url="https://console.x.ai/"
    ),
    
    # P1 - 搜索 API
    APIConfig(
        name="Brave Search",
        env_var="BRAVE_API_KEY",
        description="网页搜索",
        priority=Priority.P1,
        test_url="https://api.search.brave.com/res/v1/web/search?q=test",
        category="搜索",
        get_url="https://brave.com/search/api/"
    ),
    APIConfig(
        name="Perplexity",
        env_var="PERPLEXITY_API_KEY",
        description="AI 搜索引擎",
        priority=Priority.P1,
        category="搜索",
        get_url="https://www.perplexity.ai/settings/api"
    ),
    
    # P1 - 天气 API
    APIConfig(
        name="OpenWeatherMap",
        env_var="OPENWEATHERMAP_API_KEY",
        description="天气查询（免费）",
        priority=Priority.P1,
        test_url="https://api.openweathermap.org/data/2.5/weather?q=Beijing&appid=",
        category="天气",
        get_url="https://openweathermap.org/api"
    ),
    APIConfig(
        name="和风天气",
        env_var="QWEATHER_API_KEY",
        description="中国天气查询",
        priority=Priority.P1,
        category="天气",
        get_url="https://dev.qweather.com/"
    ),
    
    # P1 - 其他服务
    APIConfig(
        name="GitHub",
        env_var="GITHUB_TOKEN",
        description="代码管理和自动更新",
        priority=Priority.P1,
        test_url="https://api.github.com/user",
        category="开发",
        get_url="https://github.com/settings/tokens"
    ),
    APIConfig(
        name="DeepL",
        env_var="DEEPL_API_KEY",
        description="高质量翻译",
        priority=Priority.P1,
        test_url="https://api-free.deepl.com/v2/usage",
        category="翻译",
        get_url="https://www.deepl.com/pro-api"
    ),
    
    # P2 - 可选服务
    APIConfig(
        name="Slack",
        env_var="SLACK_TOKEN",
        description="消息通知",
        priority=Priority.P2,
        category="通知",
        get_url="https://api.slack.com/apps"
    ),
    APIConfig(
        name="Notion",
        env_var="NOTION_API_KEY",
        description="笔记和知识库",
        priority=Priority.P2,
        category="效率",
        get_url="https://www.notion.so/my-integrations"
    ),
]


# 数据库配置
DATABASE_CONFIGS = [
    {
        "name": "PostgreSQL",
        "env_var": "DATABASE_URL",
        "description": "主数据库",
        "priority": Priority.P0,
        "default": "postgresql://postgres:ufo123@localhost:5432/ufogalaxy",
        "docker_cmd": "docker run -d --name ufo-postgres -e POSTGRES_PASSWORD=ufo123 -e POSTGRES_DB=ufogalaxy -p 5432:5432 postgres:15"
    },
    {
        "name": "Redis",
        "env_var": "REDIS_URL",
        "description": "缓存和消息队列",
        "priority": Priority.P1,
        "default": "redis://localhost:6379",
        "docker_cmd": "docker run -d --name ufo-redis -p 6379:6379 redis:7"
    },
    {
        "name": "Qdrant",
        "env_var": "QDRANT_URL",
        "description": "向量数据库（知识库）",
        "priority": Priority.P1,
        "default": "http://localhost:6333",
        "docker_cmd": "docker run -d --name ufo-qdrant -p 6333:6333 qdrant/qdrant"
    },
]


class SetupWizard:
    """配置向导"""
    
    def __init__(self):
        self.project_root = Path(__file__).parent
        self.env_file = self.project_root / ".env"
        self.env_example = self.project_root / ".env.example"
        self.config: Dict[str, str] = {}
        self.detected_apis: Dict[str, str] = {}
        
    def load_existing_config(self):
        """加载现有配置"""
        # 从 .env 文件加载
        if self.env_file.exists():
            with open(self.env_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        if value and value != 'your-' and not value.startswith('your-'):
                            self.config[key] = value
        
        # 从环境变量加载
        for api in API_CONFIGS:
            env_value = os.environ.get(api.env_var)
            if env_value:
                self.detected_apis[api.env_var] = env_value
                
    async def test_api(self, api: APIConfig, api_key: str) -> Tuple[bool, str]:
        """测试 API 可用性"""
        if not api.test_url:
            return True, "无法测试，请手动验证"
            
        try:
            headers = {}
            url = api.test_url
            
            # 根据不同 API 设置 headers
            if "openai" in api.test_url:
                headers["Authorization"] = f"Bearer {api_key}"
            elif "anthropic" in api.test_url:
                headers["x-api-key"] = api_key
                headers["anthropic-version"] = "2023-06-01"
            elif "generativelanguage" in api.test_url:
                url = f"{api.test_url}?key={api_key}"
            elif "deepseek" in api.test_url:
                headers["Authorization"] = f"Bearer {api_key}"
            elif "openrouter" in api.test_url:
                headers["Authorization"] = f"Bearer {api_key}"
            elif "brave" in api.test_url:
                headers["X-Subscription-Token"] = api_key
            elif "openweathermap" in api.test_url:
                url = f"{api.test_url}{api_key}"
            elif "github" in api.test_url:
                headers["Authorization"] = f"token {api_key}"
            elif "deepl" in api.test_url:
                headers["Authorization"] = f"DeepL-Auth-Key {api_key}"
            else:
                headers["Authorization"] = f"Bearer {api_key}"
                
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as resp:
                    if resp.status in [200, 201]:
                        return True, "连接成功"
                    elif resp.status == 401:
                        return False, "API Key 无效"
                    elif resp.status == 403:
                        return False, "权限不足"
                    else:
                        return False, f"HTTP {resp.status}"
        except asyncio.TimeoutError:
            return False, "连接超时"
        except Exception as e:
            return False, str(e)[:50]
            
    def run_interactive_setup(self):
        """运行交互式配置"""
        print_header("UFO Galaxy 配置向导")
        
        print_info("正在检测已有的 API 配置...")
        self.load_existing_config()
        
        # 显示检测结果
        if self.detected_apis:
            print_success(f"检测到 {len(self.detected_apis)} 个已配置的 API:")
            for env_var in self.detected_apis:
                api_name = next((a.name for a in API_CONFIGS if a.env_var == env_var), env_var)
                print(f"    • {api_name}")
        else:
            print_warning("未检测到已配置的 API")
            
        print()
        
        # 按优先级分组配置
        for priority in Priority:
            apis = [a for a in API_CONFIGS if a.priority == priority]
            if not apis:
                continue
                
            print_header(f"{priority.value}配置 ({priority.name})")
            
            for api in apis:
                self._configure_api(api)
                
        # 数据库配置
        print_header("数据库配置")
        self._configure_databases()
        
        # 保存配置
        self._save_config()
        
        # 测试配置
        print_header("测试配置")
        asyncio.run(self._test_all_apis())
        
        print_header("配置完成")
        print_success("配置已保存到 .env 文件")
        print_info("运行 'python main.py' 启动系统")
        
    def _configure_api(self, api: APIConfig):
        """配置单个 API"""
        current_value = self.config.get(api.env_var) or self.detected_apis.get(api.env_var)
        
        # 显示 API 信息
        print(f"\n{Colors.BOLD}{api.name}{Colors.ENDC} - {api.description}")
        print(f"  环境变量: {api.env_var}")
        print(f"  获取地址: {api.get_url}")
        
        if current_value:
            masked = current_value[:8] + "..." + current_value[-4:] if len(current_value) > 16 else "***"
            print(f"  当前值: {masked}")
            
            choice = input(f"  是否修改? [y/N]: ").strip().lower()
            if choice != 'y':
                self.config[api.env_var] = current_value
                return
                
        # 输入新值
        new_value = input(f"  请输入 {api.env_var} (留空跳过): ").strip()
        if new_value:
            self.config[api.env_var] = new_value
        elif current_value:
            self.config[api.env_var] = current_value
            
    def _configure_databases(self):
        """配置数据库"""
        for db in DATABASE_CONFIGS:
            print(f"\n{Colors.BOLD}{db['name']}{Colors.ENDC} - {db['description']}")
            print(f"  环境变量: {db['env_var']}")
            print(f"  默认值: {db['default']}")
            print(f"  Docker 部署: {db['docker_cmd']}")
            
            current = self.config.get(db['env_var'])
            if current:
                print(f"  当前值: {current}")
                choice = input("  是否修改? [y/N]: ").strip().lower()
                if choice != 'y':
                    continue
                    
            new_value = input(f"  请输入 {db['env_var']} (留空使用默认值): ").strip()
            self.config[db['env_var']] = new_value or db['default']
            
    def _save_config(self):
        """保存配置到 .env 文件"""
        lines = [
            "# UFO Galaxy - 环境变量配置",
            "# 由配置向导自动生成",
            f"# 生成时间: {__import__('datetime').datetime.now().isoformat()}",
            "",
        ]
        
        # 按类别分组
        categories = {}
        for api in API_CONFIGS:
            if api.env_var in self.config:
                if api.category not in categories:
                    categories[api.category] = []
                categories[api.category].append((api.env_var, self.config[api.env_var]))
                
        for category, items in categories.items():
            lines.append(f"# === {category} ===")
            for key, value in items:
                lines.append(f"{key}={value}")
            lines.append("")
            
        # 数据库配置
        lines.append("# === 数据库 ===")
        for db in DATABASE_CONFIGS:
            if db['env_var'] in self.config:
                lines.append(f"{db['env_var']}={self.config[db['env_var']]}")
        lines.append("")
        
        # 写入文件
        with open(self.env_file, 'w') as f:
            f.write('\n'.join(lines))
            
    async def _test_all_apis(self):
        """测试所有已配置的 API"""
        tasks = []
        for api in API_CONFIGS:
            if api.env_var in self.config and api.test_url:
                tasks.append((api, self.config[api.env_var]))
                
        if not tasks:
            print_warning("没有可测试的 API")
            return
            
        print_info(f"正在测试 {len(tasks)} 个 API...")
        
        for api, key in tasks:
            success, message = await self.test_api(api, key)
            if success:
                print_success(f"{api.name}: {message}")
            else:
                print_error(f"{api.name}: {message}")


def quick_setup():
    """快速配置（非交互式）"""
    print_header("UFO Galaxy 快速配置")
    
    project_root = Path(__file__).parent
    env_file = project_root / ".env"
    
    # 从环境变量自动检测
    detected = {}
    for api in API_CONFIGS:
        value = os.environ.get(api.env_var)
        if value:
            detected[api.env_var] = value
            
    if detected:
        print_success(f"从环境变量检测到 {len(detected)} 个 API Key")
        
        # 生成 .env 文件
        lines = ["# UFO Galaxy - 自动检测的配置", ""]
        for key, value in detected.items():
            lines.append(f"{key}={value}")
            
        # 添加默认数据库配置
        lines.extend([
            "",
            "# 数据库配置（使用默认值）",
            "DATABASE_URL=postgresql://postgres:ufo123@localhost:5432/ufogalaxy",
            "REDIS_URL=redis://localhost:6379",
            "QDRANT_URL=http://localhost:6333",
        ])
        
        with open(env_file, 'w') as f:
            f.write('\n'.join(lines))
            
        print_success(f"配置已保存到 {env_file}")
    else:
        print_warning("未检测到环境变量中的 API Key")
        print_info("请运行 'python setup_wizard.py --interactive' 进行交互式配置")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="UFO Galaxy 配置向导")
    parser.add_argument("--interactive", "-i", action="store_true", help="交互式配置")
    parser.add_argument("--quick", "-q", action="store_true", help="快速配置（自动检测）")
    parser.add_argument("--test", "-t", action="store_true", help="测试现有配置")
    
    args = parser.parse_args()
    
    if args.interactive:
        wizard = SetupWizard()
        wizard.run_interactive_setup()
    elif args.test:
        wizard = SetupWizard()
        wizard.load_existing_config()
        asyncio.run(wizard._test_all_apis())
    else:
        quick_setup()


if __name__ == "__main__":
    main()
