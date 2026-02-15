"""
Git 自动更新模块
"""

from .auto_git_updater import (
    AutoGitUpdater,
    UpdateResult,
    UpdateStatus,
    UpdateStrategy,
    RepositoryConfig
)

__all__ = [
    'AutoGitUpdater',
    'UpdateResult',
    'UpdateStatus',
    'UpdateStrategy',
    'RepositoryConfig'
]
