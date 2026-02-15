"""
自动 GitHub 代码更新器 (Auto Git Updater)
L4 系统能及时从 GitHub 上自动拉取和更新代码
"""

import logging
import os
import subprocess
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum
import json
from datetime import datetime

logger = logging.getLogger(__name__)


class UpdateStatus(Enum):
    """更新状态"""
    SUCCESS = "success"
    NO_CHANGES = "no_changes"
    CONFLICT = "conflict"
    FAILED = "failed"
    SKIPPED = "skipped"


class UpdateStrategy(Enum):
    """更新策略"""
    PULL_ONLY = "pull_only"  # 仅拉取
    PULL_AND_MERGE = "pull_and_merge"  # 拉取并合并
    PULL_AND_REBASE = "pull_and_rebase"  # 拉取并变基
    FETCH_ONLY = "fetch_only"  # 仅获取


@dataclass
class UpdateResult:
    """更新结果"""
    status: UpdateStatus
    branch: str
    commits_pulled: int
    files_changed: List[str]
    conflicts: List[str]
    message: str
    timestamp: str


@dataclass
class RepositoryConfig:
    """仓库配置"""
    name: str
    path: str
    remote: str
    branch: str
    auto_update: bool
    update_interval: int  # 秒
    update_strategy: UpdateStrategy


class AutoGitUpdater:
    """自动 GitHub 代码更新器"""
    
    def __init__(self, config_file: str = "git_updater_config.json"):
        """
        初始化自动 Git 更新器
        
        Args:
            config_file: 配置文件路径
        """
        self.config_file = config_file
        self.repositories: Dict[str, RepositoryConfig] = {}
        self.update_history: List[Dict] = []
        self.last_update_times: Dict[str, float] = {}
        
        self._load_config()
        
        logger.info(f"AutoGitUpdater 初始化完成，管理 {len(self.repositories)} 个仓库")
    
    def _load_config(self):
        """加载配置"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config_data = json.load(f)
                
                for repo_data in config_data.get('repositories', []):
                    repo_config = RepositoryConfig(
                        name=repo_data['name'],
                        path=repo_data['path'],
                        remote=repo_data.get('remote', 'origin'),
                        branch=repo_data.get('branch', 'main'),
                        auto_update=repo_data.get('auto_update', True),
                        update_interval=repo_data.get('update_interval', 3600),
                        update_strategy=UpdateStrategy(repo_data.get('update_strategy', 'pull_and_merge'))
                    )
                    self.repositories[repo_config.name] = repo_config
                
                logger.info(f"加载配置: {len(self.repositories)} 个仓库")
            
            except Exception as e:
                logger.error(f"加载配置失败: {e}")
                self._create_default_config()
        else:
            self._create_default_config()
    
    def _create_default_config(self):
        """创建默认配置"""
        default_repos = [
            {
                'name': 'ufo-galaxy-realization',
                'path': '/home/ubuntu/code_audit/ufo-galaxy-realization',
                'remote': 'origin',
                'branch': 'main',
                'auto_update': True,
                'update_interval': 3600,
                'update_strategy': 'pull_and_merge'
            }
        ]
        
        config_data = {
            'repositories': default_repos,
            'global_settings': {
                'auto_commit_before_pull': True,
                'auto_stash_before_pull': True,
                'notification_enabled': True
            }
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f, indent=2)
        
        logger.info("创建默认配置")
        self._load_config()
    
    def add_repository(
        self,
        name: str,
        path: str,
        remote: str = 'origin',
        branch: str = 'main',
        auto_update: bool = True,
        update_interval: int = 3600,
        update_strategy: UpdateStrategy = UpdateStrategy.PULL_AND_MERGE
    ):
        """
        添加仓库
        
        Args:
            name: 仓库名称
            path: 仓库路径
            remote: 远程名称
            branch: 分支名称
            auto_update: 是否自动更新
            update_interval: 更新间隔（秒）
            update_strategy: 更新策略
        """
        repo_config = RepositoryConfig(
            name=name,
            path=path,
            remote=remote,
            branch=branch,
            auto_update=auto_update,
            update_interval=update_interval,
            update_strategy=update_strategy
        )
        
        self.repositories[name] = repo_config
        self._save_config()
        
        logger.info(f"添加仓库: {name} ({path})")
    
    def _save_config(self):
        """保存配置"""
        config_data = {
            'repositories': [
                {
                    'name': repo.name,
                    'path': repo.path,
                    'remote': repo.remote,
                    'branch': repo.branch,
                    'auto_update': repo.auto_update,
                    'update_interval': repo.update_interval,
                    'update_strategy': repo.update_strategy.value
                }
                for repo in self.repositories.values()
            ]
        }
        
        with open(self.config_file, 'w') as f:
            json.dump(config_data, f, indent=2)
    
    async def update_repository(self, repo_name: str) -> UpdateResult:
        """
        更新指定仓库
        
        Args:
            repo_name: 仓库名称
            
        Returns:
            更新结果
        """
        if repo_name not in self.repositories:
            return UpdateResult(
                status=UpdateStatus.FAILED,
                branch="",
                commits_pulled=0,
                files_changed=[],
                conflicts=[],
                message=f"仓库不存在: {repo_name}",
                timestamp=self._get_timestamp()
            )
        
        repo = self.repositories[repo_name]
        logger.info(f"开始更新仓库: {repo_name}")
        
        try:
            # 1. 检查仓库状态
            if not self._check_repository(repo):
                return UpdateResult(
                    status=UpdateStatus.FAILED,
                    branch=repo.branch,
                    commits_pulled=0,
                    files_changed=[],
                    conflicts=[],
                    message="仓库检查失败",
                    timestamp=self._get_timestamp()
                )
            
            # 2. 获取当前分支
            current_branch = self._get_current_branch(repo)
            if current_branch != repo.branch:
                logger.warning(f"当前分支 {current_branch} 与配置分支 {repo.branch} 不一致")
            
            # 3. 检查本地更改
            has_changes = self._has_local_changes(repo)
            if has_changes:
                logger.info("检测到本地更改，自动暂存")
                self._stash_changes(repo)
            
            # 4. 拉取更新
            update_result = self._pull_updates(repo)
            
            # 5. 恢复本地更改
            if has_changes:
                self._unstash_changes(repo)
            
            # 6. 记录更新历史
            self._record_update(repo_name, update_result)
            
            # 7. 更新最后更新时间
            self.last_update_times[repo_name] = time.time()
            
            logger.info(f"仓库更新完成: {repo_name}, 状态: {update_result.status.value}")
            return update_result
        
        except Exception as e:
            logger.error(f"更新仓库失败: {repo_name}, 错误: {e}")
            return UpdateResult(
                status=UpdateStatus.FAILED,
                branch=repo.branch,
                commits_pulled=0,
                files_changed=[],
                conflicts=[],
                message=str(e),
                timestamp=self._get_timestamp()
            )
    
    def _check_repository(self, repo: RepositoryConfig) -> bool:
        """检查仓库"""
        if not os.path.exists(repo.path):
            logger.error(f"仓库路径不存在: {repo.path}")
            return False
        
        if not os.path.exists(os.path.join(repo.path, '.git')):
            logger.error(f"不是 Git 仓库: {repo.path}")
            return False
        
        return True
    
    def _get_current_branch(self, repo: RepositoryConfig) -> str:
        """获取当前分支"""
        try:
            result = subprocess.run(
                ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
                cwd=repo.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
            
            if result.returncode == 0:
                return result.stdout.decode().strip()
            else:
                logger.error(f"获取当前分支失败: {result.stderr.decode()}")
                return ""
        
        except Exception as e:
            logger.error(f"获取当前分支失败: {e}")
            return ""
    
    def _has_local_changes(self, repo: RepositoryConfig) -> bool:
        """检查是否有本地更改"""
        try:
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=repo.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
            
            if result.returncode == 0:
                output = result.stdout.decode().strip()
                return len(output) > 0
            else:
                return False
        
        except Exception as e:
            logger.error(f"检查本地更改失败: {e}")
            return False
    
    def _stash_changes(self, repo: RepositoryConfig):
        """暂存本地更改"""
        try:
            subprocess.run(
                ['git', 'stash', 'push', '-m', f'Auto stash by AutoGitUpdater at {self._get_timestamp()}'],
                cwd=repo.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30
            )
            logger.info("本地更改已暂存")
        
        except Exception as e:
            logger.error(f"暂存本地更改失败: {e}")
    
    def _unstash_changes(self, repo: RepositoryConfig):
        """恢复本地更改"""
        try:
            subprocess.run(
                ['git', 'stash', 'pop'],
                cwd=repo.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30
            )
            logger.info("本地更改已恢复")
        
        except Exception as e:
            logger.error(f"恢复本地更改失败: {e}")
    
    def _pull_updates(self, repo: RepositoryConfig) -> UpdateResult:
        """拉取更新"""
        try:
            # 获取更新前的提交数
            commits_before = self._get_commit_count(repo)
            
            # 根据策略执行更新
            if repo.update_strategy == UpdateStrategy.FETCH_ONLY:
                result = subprocess.run(
                    ['git', 'fetch', repo.remote],
                    cwd=repo.path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60
                )
            
            elif repo.update_strategy == UpdateStrategy.PULL_ONLY:
                result = subprocess.run(
                    ['git', 'pull', repo.remote, repo.branch],
                    cwd=repo.path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60
                )
            
            elif repo.update_strategy == UpdateStrategy.PULL_AND_MERGE:
                result = subprocess.run(
                    ['git', 'pull', '--no-rebase', repo.remote, repo.branch],
                    cwd=repo.path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60
                )
            
            elif repo.update_strategy == UpdateStrategy.PULL_AND_REBASE:
                result = subprocess.run(
                    ['git', 'pull', '--rebase', repo.remote, repo.branch],
                    cwd=repo.path,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60
                )
            
            # 获取更新后的提交数
            commits_after = self._get_commit_count(repo)
            commits_pulled = commits_after - commits_before
            
            # 获取更改的文件
            files_changed = self._get_changed_files(repo)
            
            # 检查输出
            output = result.stdout.decode() + result.stderr.decode()
            
            if result.returncode == 0:
                if 'Already up to date' in output or 'Already up-to-date' in output:
                    status = UpdateStatus.NO_CHANGES
                    message = "已是最新"
                else:
                    status = UpdateStatus.SUCCESS
                    message = f"成功拉取 {commits_pulled} 个提交"
            else:
                if 'CONFLICT' in output:
                    status = UpdateStatus.CONFLICT
                    message = "存在冲突"
                    conflicts = self._parse_conflicts(output)
                else:
                    status = UpdateStatus.FAILED
                    message = f"拉取失败: {output}"
                    conflicts = []
            
            return UpdateResult(
                status=status,
                branch=repo.branch,
                commits_pulled=commits_pulled,
                files_changed=files_changed,
                conflicts=conflicts if status == UpdateStatus.CONFLICT else [],
                message=message,
                timestamp=self._get_timestamp()
            )
        
        except subprocess.TimeoutExpired:
            return UpdateResult(
                status=UpdateStatus.FAILED,
                branch=repo.branch,
                commits_pulled=0,
                files_changed=[],
                conflicts=[],
                message="拉取超时",
                timestamp=self._get_timestamp()
            )
        
        except Exception as e:
            return UpdateResult(
                status=UpdateStatus.FAILED,
                branch=repo.branch,
                commits_pulled=0,
                files_changed=[],
                conflicts=[],
                message=str(e),
                timestamp=self._get_timestamp()
            )
    
    def _get_commit_count(self, repo: RepositoryConfig) -> int:
        """获取提交数"""
        try:
            result = subprocess.run(
                ['git', 'rev-list', '--count', 'HEAD'],
                cwd=repo.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
            
            if result.returncode == 0:
                return int(result.stdout.decode().strip())
            else:
                return 0
        
        except Exception as e:
            logger.error(f"获取提交数失败: {e}")
            return 0
    
    def _get_changed_files(self, repo: RepositoryConfig, limit: int = 10) -> List[str]:
        """获取更改的文件"""
        try:
            result = subprocess.run(
                ['git', 'diff', '--name-only', f'{repo.remote}/{repo.branch}..HEAD'],
                cwd=repo.path,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10
            )
            
            if result.returncode == 0:
                files = result.stdout.decode().strip().split('\n')
                return [f for f in files if f][:limit]
            else:
                return []
        
        except Exception as e:
            logger.error(f"获取更改文件失败: {e}")
            return []
    
    def _parse_conflicts(self, output: str) -> List[str]:
        """解析冲突"""
        conflicts = []
        for line in output.split('\n'):
            if 'CONFLICT' in line:
                conflicts.append(line.strip())
        return conflicts
    
    def _record_update(self, repo_name: str, result: UpdateResult):
        """记录更新历史"""
        record = {
            'repo_name': repo_name,
            'status': result.status.value,
            'branch': result.branch,
            'commits_pulled': result.commits_pulled,
            'files_changed': result.files_changed,
            'message': result.message,
            'timestamp': result.timestamp
        }
        
        self.update_history.append(record)
        
        # 保存到文件
        history_file = 'git_update_history.json'
        with open(history_file, 'w') as f:
            json.dump(self.update_history, f, indent=2)
    
    def _get_timestamp(self) -> str:
        """获取时间戳"""
        return datetime.now().isoformat()
    
    async def update_all_repositories(self) -> Dict[str, UpdateResult]:
        """更新所有仓库"""
        results = {}
        
        for repo_name, repo_config in self.repositories.items():
            if repo_config.auto_update:
                result = await self.update_repository(repo_name)
                results[repo_name] = result
            else:
                logger.info(f"跳过仓库（未启用自动更新）: {repo_name}")
                results[repo_name] = UpdateResult(
                    status=UpdateStatus.SKIPPED,
                    branch=repo_config.branch,
                    commits_pulled=0,
                    files_changed=[],
                    conflicts=[],
                    message="未启用自动更新",
                    timestamp=self._get_timestamp()
                )
        
        return results
    
    def should_update(self, repo_name: str) -> bool:
        """判断是否应该更新"""
        if repo_name not in self.repositories:
            return False
        
        repo = self.repositories[repo_name]
        
        if not repo.auto_update:
            return False
        
        # 检查更新间隔
        last_update = self.last_update_times.get(repo_name, 0)
        current_time = time.time()
        
        return (current_time - last_update) >= repo.update_interval
    
    def get_update_summary(self) -> Dict:
        """获取更新摘要"""
        if not self.update_history:
            return {
                'total_updates': 0,
                'successful_updates': 0,
                'failed_updates': 0,
                'conflicts': 0,
                'total_commits_pulled': 0
            }
        
        summary = {
            'total_updates': len(self.update_history),
            'successful_updates': 0,
            'failed_updates': 0,
            'conflicts': 0,
            'total_commits_pulled': 0
        }
        
        for record in self.update_history:
            if record['status'] == 'success':
                summary['successful_updates'] += 1
            elif record['status'] == 'failed':
                summary['failed_updates'] += 1
            elif record['status'] == 'conflict':
                summary['conflicts'] += 1
            
            summary['total_commits_pulled'] += record.get('commits_pulled', 0)
        
        return summary
