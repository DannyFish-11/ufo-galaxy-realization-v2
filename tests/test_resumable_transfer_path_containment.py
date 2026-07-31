"""ResumableTransferManager 的状态文件路径必须关在 state_dir 之内。

``create_session(session_id=...)`` 的 id 是调用方给的，而状态文件路径由它拼成。
三处拼接原先都是裸 ``os.path.join(self.state_dir, f"{session_id}.json")`` ——
传一个 ``../../`` 就能读写目录外的文件。

目前仓库里没有把 HTTP 请求参数接到这个类的生产调用方，所以当时不是可远程触达的
漏洞；这组测试的意义是：将来谁把它接上路由时，越界会当场失败，而不是悄悄写出去。
"""

import os
import tempfile

import pytest

from galaxy_gateway.resumable_transfer import ResumableTransferManager


@pytest.fixture
def manager(tmp_path):
    return ResumableTransferManager(state_dir=str(tmp_path / "states"))


def test_plain_id_maps_into_state_dir(manager, tmp_path):
    path = manager._state_path("session-abc123")

    root = os.path.realpath(str(tmp_path / "states"))
    assert os.path.realpath(path).startswith(root + os.sep)
    assert os.path.basename(path) == "session-abc123.json"


@pytest.mark.parametrize(
    "evil",
    [
        "../escape",
        "../../etc/passwd",
        "a/../../b",
        "../" * 8 + "tmp/pwned",
    ],
)
def test_traversal_is_rejected(manager, evil):
    with pytest.raises(ValueError):
        manager._state_path(evil)


def test_absolute_path_is_rejected(manager):
    """绝对路径同样不能逃出去 —— os.path.join 遇到绝对路径会丢弃前缀。"""
    with pytest.raises(ValueError):
        manager._state_path(os.path.join(tempfile.gettempdir(), "pwned"))


def test_nested_but_contained_is_allowed(manager, tmp_path):
    """留在根内的子路径不该被误伤 —— 这里做的是结果校验，不是字符黑名单。"""
    path = manager._state_path("group/sub-id")

    root = os.path.realpath(str(tmp_path / "states"))
    assert os.path.realpath(path).startswith(root + os.sep)
