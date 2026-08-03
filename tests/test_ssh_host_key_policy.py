"""tests/test_ssh_host_key_policy.py — SSH 主机密钥策略必须真的在校验。

背景
----
``galaxy_gateway/routes/linux_agent.py`` 里此前 5 处都是
``set_missing_host_key_policy(AutoAddPolicy())`` —— 对**任何**主机密钥照连不误。
这条链路会把密码/私钥送过去,并在对端执行任意命令、读写任意文件;AutoAdd 意味着
一台冒充目标 IP 的机器可以直接拿到这些,而且过程完全静默。

CodeQL 的 ``py/paramiko-missing-host-key-validation`` 早就报了它,5 条全在那个文件。
之所以一直没修,是因为**没人读到过那份告警** —— 分析结果只进 Security 页,
CI 里读不到、脚本里拿不到。把摘要 tee 进作业日志之后才发现,总数根本不是当时以为的
6 条,而是 30 条。

这份测试钉什么
--------------
钉的是**行为**,不是写法。"改成了 RejectPolicy"这种断言毫无价值 —— 它挡不住
有人把 env 默认值改掉、或者在某个新方法里又写一遍 AutoAdd。所以这里断言的是:

  1. 默认(不设环境变量)拿到的策略**会拒绝**未知主机;
  2. 显式开启 TOFU 时才接受,并且**落盘** —— 不落盘的 AutoAdd 只是"每次都接受
     新钥匙",和没有校验没有区别,而这正是修之前的状态;
  3. 落盘文件的权限是 0600 —— 这个文件决定"信任谁",别人可写就等于信任可被改;
  4. 全文件不再有第二处 AutoAddPolicy(工厂里那一处是被 env 守着的)。

第 2 条是关键。AutoAdd 与 TOFU 看起来像同一件事,差别全在"记不记得住":
只有落了盘,下一次连接才是**校验**而不是再学一遍。
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "galaxy_gateway" / "routes" / "linux_agent.py"

# paramiko 的 skip **只加在真正需要它的类上**,不加在文件顶层。
#
# 顶层 importorskip 会让整份文件在没装 paramiko 的机器上静默消失 —— 包括那两条
# 纯读源码、根本不需要 paramiko 的守卫。而那两条恰恰是最不该被禁掉的:它们防的是
# "有人又在新方法里写了一句 AutoAddPolicy"。一份会自我禁用的测试,和这次要修的
# 缺陷是同一种病。
_needs_paramiko = pytest.mark.skipif(
    __import__("importlib.util", fromlist=["util"]).find_spec("paramiko") is None,
    reason="没装 paramiko;纯源码守卫不受影响,照常跑",
)


@pytest.fixture
def ssh_env(tmp_path, monkeypatch):
    """把信任库指到临时目录 —— 测试绝不该碰开发者真正的 known_hosts。"""
    from galaxy_gateway.routes.linux_agent import SSHExecutor

    monkeypatch.setattr(SSHExecutor, "_KNOWN_HOSTS", tmp_path / "ssh_known_hosts")
    monkeypatch.delenv("GALAXY_SSH_TRUST_ON_FIRST_USE", raising=False)
    return SSHExecutor


class _StubTransport:
    """paramiko 的策略在做判定**之前**先调 ``client._log()``,而那要走 ``_transport``。

    没连过的 client 其 ``_transport`` 是 None,于是直接调用策略会先炸在日志上 ——
    炸的位置离要验的行为很远,看起来像"策略坏了",其实只是没有传输层。
    给它一个最小桩,让判定本身能跑到。
    """

    def _log(self, *_args, **_kwargs):
        return None


def _client_ready_for_policy(ssh_env):
    client = ssh_env._new_ssh_client()
    client._transport = _StubTransport()
    return client


@_needs_paramiko
class TestDefaultRejectsUnknownHosts:
    def test_default_policy_rejects(self, ssh_env):
        import paramiko

        client = ssh_env._new_ssh_client()
        policy = client._policy
        assert isinstance(policy, paramiko.RejectPolicy), (
            f"默认策略是 {type(policy).__name__} —— 默认必须拒绝未知主机。"
            "家用局域网首次配对因此失败一次是**有意的**:让『我现在要信任这台机器』"
            "成为一个人做出的、看得见的决定。"
        )

    def test_reject_policy_actually_raises(self, ssh_env):
        import paramiko

        """不只是"类型对",而是它真的会拒。

        换个实现(比如 WarningPolicy)类型断言会红,但更重要的是行为:
        这一条直接调用策略本身,确认它抛异常而不是放行。
        """
        client = _client_ready_for_policy(ssh_env)
        key = paramiko.RSAKey.generate(1024)
        with pytest.raises(paramiko.SSHException):
            client._policy.missing_host_key(client, "192.0.2.10", key)

    @pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "NO"])
    def test_falsy_env_values_do_not_enable_tofu(self, value, monkeypatch, ssh_env):
        import paramiko

        monkeypatch.setenv("GALAXY_SSH_TRUST_ON_FIRST_USE", value)
        assert isinstance(ssh_env._new_ssh_client()._policy, paramiko.RejectPolicy)


@_needs_paramiko
class TestTrustOnFirstUse:
    @pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
    def test_explicit_opt_in_accepts(self, value, monkeypatch, ssh_env):
        import paramiko

        monkeypatch.setenv("GALAXY_SSH_TRUST_ON_FIRST_USE", value)
        policy = ssh_env._new_ssh_client()._policy
        assert isinstance(policy, paramiko.MissingHostKeyPolicy)
        assert not isinstance(policy, paramiko.RejectPolicy)
        # 也不该是 paramiko 自带的 AutoAddPolicy —— 那个只"接受"不"记住"。
        assert not isinstance(policy, paramiko.AutoAddPolicy), (
            "用回 AutoAddPolicy 就把『接受』和『落盘』重新拆成了两步,"
            "任何一条忘了落盘的路径都会静默退化成裸 AutoAdd。"
        )

    def test_learned_key_is_persisted(self, monkeypatch, ssh_env):
        import paramiko

        """落盘是 TOFU 与"每次都接受新钥匙"的**唯一**区别。

        这一条断了而上面那条没断,意味着改动只是把 AutoAdd 藏到了一个环境变量后面,
        安全性一点没变 —— 而那恰恰是最容易发生的"看起来修好了"。
        """
        monkeypatch.setenv("GALAXY_SSH_TRUST_ON_FIRST_USE", "1")
        client = _client_ready_for_policy(ssh_env)
        assert not ssh_env._KNOWN_HOSTS.exists(), "接受之前不该有文件"

        client._policy.missing_host_key(client, "192.0.2.10", paramiko.RSAKey.generate(1024))

        # 注意这里**没有**单独调 _persist_host_keys —— 落盘必须发生在接受的同一步里。
        # 这一条比先前那版强:先前是"接受、然后我们记得去落盘",而"记得"是靠不住的。
        assert ssh_env._KNOWN_HOSTS.is_file(), "接受主机密钥的同时必须落盘,否则下次还是在重新学"
        assert "192.0.2.10" in ssh_env._KNOWN_HOSTS.read_text(encoding="utf-8")

    def test_persisted_file_is_owner_only(self, monkeypatch, ssh_env):
        import paramiko

        monkeypatch.setenv("GALAXY_SSH_TRUST_ON_FIRST_USE", "1")
        client = _client_ready_for_policy(ssh_env)
        client._policy.missing_host_key(client, "192.0.2.11", paramiko.RSAKey.generate(1024))
        mode = os.stat(ssh_env._KNOWN_HOSTS).st_mode & 0o777
        assert mode == 0o600, f"信任库权限是 {oct(mode)};别人可写就等于信任可被改"

    def test_persisted_key_is_loaded_back(self, monkeypatch, ssh_env):
        import paramiko

        """落盘之后,新建的客户端要能读回来 —— 这才构成"下一次是校验"。"""
        monkeypatch.setenv("GALAXY_SSH_TRUST_ON_FIRST_USE", "1")
        first = _client_ready_for_policy(ssh_env)
        key = paramiko.RSAKey.generate(1024)
        first._policy.missing_host_key(first, "192.0.2.12", key)

        second = ssh_env._new_ssh_client()
        assert "192.0.2.12" in second.get_host_keys(), "重启后信任库没被读回,TOFU 等于没生效"

    def test_persist_failure_does_not_raise(self, monkeypatch, tmp_path, ssh_env):
        import paramiko

        """落盘失败不该让本次运维操作失败 —— 但也不该静默:实现里会打 warning。"""
        monkeypatch.setenv("GALAXY_SSH_TRUST_ON_FIRST_USE", "1")
        monkeypatch.setattr(ssh_env, "_KNOWN_HOSTS", tmp_path / "nope" / "x" / "known_hosts")
        client = ssh_env._new_ssh_client()
        monkeypatch.setattr(client, "save_host_keys", lambda *_: (_ for _ in ()).throw(OSError("disk full")))
        ssh_env._persist_host_keys(client)  # 不抛就算过


class TestNoStrayAutoAdd:
    def test_source_never_instantiates_autoadd_policy(self):
        """全文件**一处** ``AutoAddPolicy()`` 调用都不该有。

        直接读源码而不是靠反射:新写的方法里如果又出现一句
        ``set_missing_host_key_policy(AutoAddPolicy())``,反射看不见(那条路径没被调到),
        但它已经把洞重新打开了。修之前正是 5 处这样的调用。

        注释与 docstring 里提到这个名字是允许的 —— 那些恰恰是记录"为什么不用它"
        的地方,把它们也禁掉等于逼人删掉理由。
        """
        # 用 AST 而不是按行过滤:第一版只剥了 `#` 注释,结果被本文件自己
        # **docstring 里那句"为什么不用 AutoAddPolicy"**判红 —— 而那句话是最该留的。
        # 只有真正的调用节点才算数,散文里出现这个名字不算。
        tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
        autoadd = [
            f"line {node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and (
                (isinstance(node.func, ast.Attribute) and node.func.attr == "AutoAddPolicy")
                or (isinstance(node.func, ast.Name) and node.func.id == "AutoAddPolicy")
            )
        ]
        assert not autoadd, "不该再实例化 AutoAddPolicy:" + ", ".join(autoadd)
        text = SOURCE.read_text(encoding="utf-8")
        assert "RejectPolicy()" in text, "默认必须是 RejectPolicy"
        assert "GALAXY_SSH_TRUST_ON_FIRST_USE" in text, "开关名不在文件里,说明守卫被改掉了"

    def test_every_ssh_client_goes_through_the_factory(self):
        """不许有人绕过工厂直接 ``paramiko.SSHClient()``(工厂自己那一处除外)。"""
        text = SOURCE.read_text(encoding="utf-8")
        direct = [
            ln.strip()
            for ln in text.splitlines()
            if re.search(r"=\s*paramiko\.SSHClient\(\)", ln) and not ln.lstrip().startswith("#")
        ]
        assert (
            len(direct) == 1
        ), (
            f"有 {len(direct)} 处直接 new SSHClient,只允许工厂里那一处 —— "
            "绕过工厂就绕过了主机密钥校验:\n" + "\n".join(direct)
        )
