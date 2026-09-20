"""装一个 GitHub addon 之前，要不要先问人。

`github__install` 是 **LLM 直接可调**的工具：说一句「把 https://github.com/x/y 装上」，
它就会 clone、检测类型、注册、**在当前会话立刻生效**。改之前的默认状态是
`GITHUB_ALLOWLIST` 为空 = 全放行，没有任何人确认。

## 判据：只收紧，不放宽

`validate_repo_url()` 里那套 allowlist/blocklist 判定一个字都没改：

| 情况 | 改之前 | 改之后 |
|---|---|---|
| blocklist 命中 | 拒 | 拒（不变） |
| allowlist 非空且命中 | 放行 | 放行，**免确认** |
| allowlist 非空但不命中 | **拒** | **拒**（不变） |
| allowlist 为空 | 全放行，无确认 | **要问人** |

最后一行是唯一的变化。**「名单外」没有从「拒绝」放宽成「问人」**——那会把一道硬闸
换成一道点一下「同意」就能绕过的软闸，是净损失。下面有一条专门钉住这件事。
"""

import pytest

from core.github_addon_admission import (
    AdmissionVerdict,
    admit_addon_install,
    evaluate_addon_admission,
)


def _v(owner="me", repo="tool", *, allow=None, block=None) -> AdmissionVerdict:
    return evaluate_addon_admission(owner, repo, allowlist=allow or [], blocklist=block or [])


class TestTheGradedRule:
    def test_an_allowlisted_repo_installs_without_asking(self):
        v = _v(allow=["me/*"])
        assert (v.allowed, v.needs_human) == (True, False)
        assert v.rule == "allowlist"

    def test_an_empty_allowlist_means_ask(self):
        """改之前这里是「全放行、不问」。"""
        v = _v()
        assert (v.allowed, v.needs_human) == (True, True)
        assert v.rule == "unlisted"

    def test_a_blocked_repo_is_refused_outright(self):
        v = _v(block=["me/*"])
        assert (v.allowed, v.needs_human) == (False, False)
        assert v.rule == "blocklist"

    def test_blocklist_beats_allowlist(self):
        """两张名单都命中时，**拒**必须赢——否则 blocklist 形同虚设。"""
        v = _v(allow=["me/*"], block=["me/tool"])
        assert v.allowed is False
        assert v.rule == "blocklist"

    def test_every_verdict_says_which_rule_decided_it(self):
        """「为什么这次问了我而上次没问」是用户一定会问的问题。

        答不上来的门禁会被当成随机行为，然后被关掉。
        """
        for v in (_v(allow=["me/*"]), _v(), _v(block=["me/*"]), _v(allow=["other/*"])):
            assert v.rule, "没说是哪条规则决定的"
            assert v.reason, "没说为什么"


class TestItOnlyTightens:
    def test_an_unlisted_repo_under_a_nonempty_allowlist_is_still_refused(self):
        """**这条是整个改动的安全边界。**

        名单非空而不命中 = 拒绝，不是「问一下人」。放宽成问人的话，
        原本一道硬闸就变成了点一下「同意」就能绕过的软闸——净损失。
        """
        v = _v("stranger", "thing", allow=["me/*"])
        assert v.allowed is False
        assert v.needs_human is False, "不该给它一个「问人就能过」的机会"
        assert v.rule == "not_allowlisted"

    def test_the_hard_gate_in_validate_repo_url_is_unchanged(self):
        """判据盯着**真的那条路**：allowlist 非空不命中，URL 校验这一关就已经拒了。"""
        import os

        from core.github_installer import validate_repo_url

        prev = os.environ.get("GITHUB_ALLOWLIST")
        os.environ["GITHUB_ALLOWLIST"] = "me/*"
        try:
            result = validate_repo_url("https://github.com/stranger/thing")
        finally:
            if prev is None:
                os.environ.pop("GITHUB_ALLOWLIST", None)
            else:
                os.environ["GITHUB_ALLOWLIST"] = prev
        assert result["valid"] is False
        assert "GITHUB_ALLOWLIST" in result["error"]


class TestAskingHuman:
    @pytest.mark.asyncio
    async def test_no_one_to_ask_means_refused(self, monkeypatch):
        """问不到人 = 拒绝。和 Node_122_Shell 的人确认同一个取舍。"""
        monkeypatch.delenv("GITHUB_ALLOWLIST", raising=False)
        monkeypatch.delenv("GITHUB_BLOCKLIST", raising=False)
        monkeypatch.delenv("GALAXY_ADDON_UNATTENDED", raising=False)

        async def _no_devices():
            return []

        monkeypatch.setattr(
            "core.interaction.pending_decision_registry._discover_target_devices",
            _no_devices,
        )
        v = await admit_addon_install("me", "tool", "main")
        assert v.allowed is False
        assert v.rule == "human_denied"

    @pytest.mark.asyncio
    async def test_it_does_not_wait_out_the_timeout_when_nobody_is_connected(self, monkeypatch):
        """**拒绝要快。**

        没有设备在线时 `request_human_decision` 会把超时等满（实测 60 秒），
        而结论从第一秒起就已经确定。每次装插件卡一分钟会被当成坏了，
        然后有人去把这道闸关掉——这个坑 `/script` 那轮踩过。
        """
        monkeypatch.delenv("GITHUB_ALLOWLIST", raising=False)
        monkeypatch.delenv("GALAXY_ADDON_UNATTENDED", raising=False)

        async def _no_devices():
            return []

        asked = []

        async def _should_not_be_called(**kw):
            asked.append(kw)
            raise AssertionError("没有设备时不该真的去问")

        monkeypatch.setattr("core.interaction.pending_decision_registry._discover_target_devices", _no_devices)
        monkeypatch.setattr(
            "core.interaction.pending_decision_registry.request_human_decision",
            _should_not_be_called,
        )
        v = await admit_addon_install("me", "tool", "main")
        assert v.allowed is False
        assert asked == [], "没先查设备就去问了"

    @pytest.mark.asyncio
    async def test_approval_lets_it_through(self, monkeypatch):
        monkeypatch.delenv("GITHUB_ALLOWLIST", raising=False)
        monkeypatch.delenv("GALAXY_ADDON_UNATTENDED", raising=False)

        async def _one_device():
            return ["watch-1"]

        async def _approve(**kw):
            assert "me/tool" in kw["title"], "问题里要说清装的是哪个仓库"
            return type("O", (), {"selected_option": "approve"})()

        monkeypatch.setattr("core.interaction.pending_decision_registry._discover_target_devices", _one_device)
        monkeypatch.setattr("core.interaction.pending_decision_registry.request_human_decision", _approve)
        v = await admit_addon_install("me", "tool", "main")
        assert v.allowed is True
        assert v.rule == "human_approved"

    @pytest.mark.asyncio
    async def test_a_denial_is_a_denial(self, monkeypatch):
        monkeypatch.delenv("GITHUB_ALLOWLIST", raising=False)
        monkeypatch.delenv("GALAXY_ADDON_UNATTENDED", raising=False)

        async def _one_device():
            return ["watch-1"]

        async def _deny(**kw):
            return type("O", (), {"selected_option": "deny"})()

        monkeypatch.setattr("core.interaction.pending_decision_registry._discover_target_devices", _one_device)
        monkeypatch.setattr("core.interaction.pending_decision_registry.request_human_decision", _deny)
        v = await admit_addon_install("me", "tool", "main")
        assert v.allowed is False

    @pytest.mark.asyncio
    async def test_an_allowlisted_repo_never_reaches_the_human_gate(self, monkeypatch):
        """名单内免确认——判据是**根本没去问**，而不只是结果为 True。"""
        monkeypatch.setenv("GITHUB_ALLOWLIST", "me/*")
        monkeypatch.delenv("GITHUB_BLOCKLIST", raising=False)

        async def _boom():
            raise AssertionError("名单内的仓库不该去问人")

        monkeypatch.setattr("core.interaction.pending_decision_registry._discover_target_devices", _boom)
        v = await admit_addon_install("me", "tool", "main")
        assert (v.allowed, v.needs_human, v.rule) == (True, False, "allowlist")


class TestTheHeadlessEscapeHatch:
    @pytest.mark.asyncio
    async def test_unattended_skips_the_ask(self, monkeypatch):
        """口子留着，但必须是一次**显式**声明，而且 rule 如实写 unattended。"""
        monkeypatch.delenv("GITHUB_ALLOWLIST", raising=False)
        monkeypatch.setenv("GALAXY_ADDON_UNATTENDED", "1")

        async def _boom():
            raise AssertionError("声明了无人值守就不该去问")

        monkeypatch.setattr("core.interaction.pending_decision_registry._discover_target_devices", _boom)
        v = await admit_addon_install("me", "tool", "main")
        assert (v.allowed, v.rule) == (True, "unattended")

    @pytest.mark.asyncio
    async def test_unattended_does_not_override_the_blocklist(self, monkeypatch):
        """无人值守只跳过**问人**，不是跳过判定。blocklist 照样拒。"""
        monkeypatch.setenv("GALAXY_ADDON_UNATTENDED", "1")
        monkeypatch.setenv("GITHUB_BLOCKLIST", "me/*")
        monkeypatch.delenv("GITHUB_ALLOWLIST", raising=False)
        v = await admit_addon_install("me", "tool", "main")
        assert v.allowed is False
        assert v.rule == "blocklist"


class TestTheKnobsReachThePanel:
    """调不到的旋钮等于没有。`GITHUB_ALLOWLIST` 原先不在配置表里——
    也就是说「权限最小化」这个开关，面板上根本调不了。"""

    @pytest.mark.parametrize(
        "key",
        [
            "GITHUB_ALLOWLIST",
            "GITHUB_BLOCKLIST",
            "GALAXY_ADDON_UNATTENDED",
            "GALAXY_ADDON_HOST_DEPS",
        ],
    )
    def test_the_knob_is_in_the_config_schema(self, key):
        from core.routes.config_schema_registry import CONFIG_SCHEMA

        assert key in CONFIG_SCHEMA, f"{key} 不在面板配置表里，用户调不到"
        assert CONFIG_SCHEMA[key]["description"], f"{key} 没有说明，用户不知道它干什么"


class TestTheGateIsOnTheRealInstallPath:
    """判据盯着 `installer.install()` 真的走过这道闸，而不只是模块里有这个函数。

    「实现了却没接线」在这个仓里有先例（`needs_human` 曾经只是个字段，
    全仓没有任何消费者）。所以这条从真正的入口打进去。
    """

    @pytest.mark.asyncio
    async def test_install_is_refused_when_nobody_can_approve(self, monkeypatch, tmp_path):
        monkeypatch.delenv("GITHUB_ALLOWLIST", raising=False)
        monkeypatch.delenv("GITHUB_BLOCKLIST", raising=False)
        monkeypatch.delenv("GALAXY_ADDON_UNATTENDED", raising=False)

        async def _no_devices():
            return []

        monkeypatch.setattr("core.interaction.pending_decision_registry._discover_target_devices", _no_devices)

        fetched = []
        monkeypatch.setattr(
            "core.github_installer._fetch_repo",
            lambda *a, **kw: fetched.append(a) or "sha",
        )

        from core.github_installer import GitHubInstaller

        installer = GitHubInstaller()
        installer._install_dir = tmp_path
        result = await installer.install("https://github.com/me/tool")

        assert result["success"] is False
        assert result.get("admission_rule") == "human_denied"
        assert fetched == [], "被拒了还是把仓库 clone 下来了"

    @pytest.mark.asyncio
    async def test_a_dry_run_does_not_ask_anyone(self, monkeypatch, tmp_path):
        """`dry_run` 只验证 URL，不该去打扰人。"""
        monkeypatch.delenv("GITHUB_ALLOWLIST", raising=False)
        monkeypatch.delenv("GALAXY_ADDON_UNATTENDED", raising=False)

        async def _boom():
            raise AssertionError("dry_run 不该去问人")

        monkeypatch.setattr("core.interaction.pending_decision_registry._discover_target_devices", _boom)

        from core.github_installer import GitHubInstaller

        installer = GitHubInstaller()
        installer._install_dir = tmp_path
        result = await installer.install("https://github.com/me/tool", dry_run=True)
        assert result["success"] is True
        assert result["dry_run"] is True
