"""「接进来的 GitHub 项目」：后端早就能装，面板上却没有入口。

## 这一整套要挡的是什么

``core/github_installer.py`` 从很早就实现了"填一个仓库地址就把它接进来"：克隆、
按清单判类型、装依赖、注册成 MCP 工具或 Skill、再自证一次。``/api/v1/github/*``
四个端点也都在。**但面板上一个入口都没有** —— 能力有、界面上够不着。

这正是本仓最怕那种缺陷的镜像：不是"看起来接上了其实没有"，而是"其实有，但没有
任何入口"。两者都靠肉眼发现不了，所以都要有门。这个文件就是那道门。

## 它和 test_user_providers_are_really_wired.py 的关系

那边挡的是同一类病，形状也一样（按源码核接线、端点路径写全串不许拼接，这样搜索
和这道门都能找到它）。这里刻意沿用那套形状，不另发明一种。

## 为什么"安装策略"这一条要单独立一个断言

装一个第三方仓库是有后果的动作，准入闸有三档（名单内免确认 / 每次问人 / 显式
声明无人值守）。**这三档必须由后端报**：面板自己按环境变量推会成为第二处权威，
判定规则改一次两边就分家 —— 而"界面说会问我、实际没问"是最坏的那种不一致。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

PANEL_SRC = Path(__file__).resolve().parents[1] / "electron/renderer/panel/src"


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """把安装根指到临时目录，绝不碰开发机上真的 data/github_addons。"""
    monkeypatch.setenv("GITHUB_INSTALL_DIR", str(tmp_path))
    from core.routes import github as route

    app = FastAPI()
    app.include_router(route.create_router())
    with TestClient(app) as c:
        yield c


class TestTheBackendPublishesWhatThePanelNeeds:
    """面板要画的每一件事，后端都得真的发出来 —— 否则前端只能自己编一份。"""

    def test_status_says_whether_it_will_ask_a_human(self, client, monkeypatch):
        """``approval_mode`` 必须在 /status 里，而且三档都要能被报出来。

        前端不许自己按 GITHUB_ALLOWLIST / GALAXY_ADDON_UNATTENDED 推：那会成为
        第二处权威。判定规则只在 core/github_addon_admission.py 那一处。
        """
        for env, expected in (
            ({}, "ask"),
            ({"GITHUB_ALLOWLIST": "me/repo"}, "allowlist"),
            ({"GALAXY_ADDON_UNATTENDED": "1"}, "unattended"),
        ):
            monkeypatch.delenv("GITHUB_ALLOWLIST", raising=False)
            monkeypatch.delenv("GALAXY_ADDON_UNATTENDED", raising=False)
            for k, v in env.items():
                monkeypatch.setenv(k, v)
            body = client.get("/api/v1/github/status").json()
            assert body.get("approval_mode") == expected, f"环境 {env} 下报的是 {body.get('approval_mode')!r}"

    def test_the_three_modes_are_not_collapsible(self):
        """三档不能合并成"会问/不会问"两档。

        ``allowlist`` 和 ``unattended`` 都不问人，但一个是"只有名单里的能进"，
        另一个是"谁都能进"。合成一句，后者会被读成前者。
        """
        from core.github_addon_admission import approval_mode

        modes = set()
        for env in ({}, {"GITHUB_ALLOWLIST": "me/repo"}, {"GALAXY_ADDON_UNATTENDED": "1"}):
            old = {k: os.environ.get(k) for k in ("GITHUB_ALLOWLIST", "GALAXY_ADDON_UNATTENDED")}
            try:
                for k in old:
                    os.environ.pop(k, None)
                os.environ.update(env)
                modes.add(approval_mode())
            finally:
                for k, v in old.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
        assert modes == {"ask", "allowlist", "unattended"}, f"三档没分开：{modes}"

    def test_status_names_the_lists_and_whether_a_token_is_configured(self, client, monkeypatch):
        monkeypatch.setenv("GITHUB_ALLOWLIST", "me/a,me/b")
        monkeypatch.setenv("GITHUB_BLOCKLIST", "evil/*")
        body = client.get("/api/v1/github/status").json()
        assert body["allowlist"] == ["me/a", "me/b"]
        assert body["blocklist"] == ["evil/*"]
        assert "token_configured" in body, "没说 token 配没配 —— 私有仓会在装的时候才失败"
        assert "install_dir" in body, "没说装在哪 —— 出问题时人连去哪儿看都不知道"

    def test_list_returns_an_addons_array_even_when_empty(self, client):
        """空也要是数组。给 null 或干脆不给这个键，前端分不清"没装过"和"拉不到"。"""
        body = client.get("/api/v1/github/list").json()
        assert body["addons"] == []


class TestThePanelIsActuallyWiredToThoseEndpoints:
    """面板那一段必须真的打这几个端点，而不是长得像。

    后端做好、面板画了一个漂亮的表单 —— 但按钮什么都不做。这在本仓发生过
    （「喂文件」那个按钮拿到 pickFiles 的结果之后什么都没干，接了整整一轮才被
    发现）。所以这里按**源码**核一遍接线。
    """

    @pytest.mark.parametrize(
        "path",
        [
            "/api/v1/github/list",
            "/api/v1/github/status",
            "/api/v1/github/install",
            "/api/v1/github/uninstall",
        ],
    )
    def test_transport_names_the_endpoint_in_full(self, path):
        src = (PANEL_SRC / "transport.ts").read_text(encoding="utf-8")
        assert path in src, f"transport.ts 里找不到 {path} —— 面板没在打这个端点，或者路径被拼接拆碎了"

    @pytest.mark.parametrize("verb", ["fetchGitHubAddons", "installGitHubAddon", "uninstallGitHubAddon"])
    def test_main_actually_calls_each_transport_function(self, verb):
        src = (PANEL_SRC / "main.ts").read_text(encoding="utf-8")
        assert f"{verb}(" in src, f"main.ts 里没有调用 {verb} —— 那它就是个没接线的按钮"

    def test_the_section_is_mounted_into_the_settings_page(self):
        main = (PANEL_SRC / "main.ts").read_text(encoding="utf-8")
        settings = (PANEL_SRC / "ui/settings.ts").read_text(encoding="utf-8")
        assert "createGitHubAddons(" in main, "main.ts 没有创建这一段"
        assert "githubAddons.root" in main, "创建了但没交给设置页 —— 那它永远不会出现在屏幕上"
        assert "cb.topSections" in settings, "设置页没有把它挂进 body"

    def test_it_is_loaded_at_startup_not_only_when_settings_open(self):
        """开机就拉一次。

        只在打开设置时拉的话，别处想用"接进来了什么"这份清单就永远是空的 ——
        隔壁「我的模型服务」正是因为这个改过一次。
        """
        main = (PANEL_SRC / "main.ts").read_text(encoding="utf-8")
        assert "void loadAddons();" in main, "没有在开机时拉一次"

    def test_the_install_button_goes_through_the_backend_not_optimistic_state(self):
        """装完必须重新拉一次列表，不做乐观更新。

        乐观更新时，被准入闸拦下的那一次会在界面上留下一条并不存在的插件 ——
        而那正是"看起来接上了，其实没有"。
        """
        main = (PANEL_SRC / "main.ts").read_text(encoding="utf-8")
        body = main.split("async function installAddon(", 1)[1].split("\n  }", 1)[0]
        assert "await loadAddons()" in body, "装完没有重新拉 —— 界面显示的是前端拼的，不是后端认的"


class TestTheUiDoesNotInventWhatTheBackendDidNotSay:
    """界面上每一个判断都要有后端的出处。"""

    def test_the_panel_does_not_derive_the_approval_mode_itself(self):
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        transport = (PANEL_SRC / "transport.ts").read_text(encoding="utf-8")
        assert "approval_mode" in transport, "transport.ts 没有读后端给的安装策略"
        assert "approvalMode" in ui, "界面上没有把安装策略说出来"
        for env in ("GITHUB_ALLOWLIST", "GALAXY_ADDON_UNATTENDED"):
            assert env not in ui, f"界面自己读了 {env} —— 那就成了第二处权威，规则改一次两边分家"

    def test_the_two_states_are_styled_apart(self):
        """active / degraded 必须长得不一样。

        "代码拿下来了但没注册上"画成绿点，等于告诉用户"这个工具能用"，
        而实际上模型调它的时候才会报错。
        """
        css = (PANEL_SRC / "styles/hud.css").read_text(encoding="utf-8")
        for state in ("active", "degraded"):
            assert f"data-state='{state}'" in css, f"{state} 这一态没有自己的样式 —— 两种状态被画成了同一件事"

    def test_the_three_approval_modes_are_styled_apart(self):
        css = (PANEL_SRC / "styles/hud.css").read_text(encoding="utf-8")
        for mode in ("ask", "allowlist", "unattended"):
            assert f"data-mode='{mode}'" in css, f"{mode} 这一档没有自己的样式 —— 三档被画成了同一件事"

    def test_not_fetched_is_distinguished_from_nothing_installed(self):
        """「拉不到」不是「一个都没装」。

        画成同一个空白，人会以为自己接过的项目丢了。
        """
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        assert "rows === null" in ui, "没有区分「拉不到」和「一个都没装」"
        assert "拉不到已接进来的项目" in ui
        assert "还没接过" in ui

    def test_the_form_never_lets_a_human_pick_the_addon_type(self):
        """类型由仓库自己的清单说了算，表单里不给"猜一个类型去覆盖它"的入口。

        后端的 type 名单（mcp / skill / skill_md / 自动判）不通过任何接口报出来。
        在表单里摆一个选择器，就等于在前端立一份**会漂移且不报错**的名单 ——
        协议牌当初写死成 'openai' 是同一个坑。

        这条门管的是**输入**，不是显示。卡片上把 ``mcp`` 写成「MCP 工具」是显示，
        而且它带 ``?? a.type`` 兜底：后端多一种类型时原值会照样露出来，
        不会悄悄消失。下一条钉的就是那个兜底。
        """
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        assert "GitHubAddonDraft" in ui
        draft = ui.split("export interface GitHubAddonDraft", 1)[1].split("}", 1)[0]
        assert "type" not in draft, f"表单草稿里出现了 type 字段：{draft!r}"
        assert "createElement('select')" not in ui, "表单里出现了类型选择器"

    def test_an_unknown_addon_type_still_shows_up_verbatim(self):
        """认不出的类型要**露出来**，不能画成空白。

        没有兜底的话，后端将来多一种类型时，那张卡片上的类型位就是空的 ——
        而"什么都没显示"会被读成"没有类型"，不是"我不认识它"。
        """
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        assert "KIND_TEXT[a.type] ?? a.type" in ui, "类型显示没有兜底"

    def test_it_says_plainly_that_mcp_and_skill_are_what_a_repo_becomes(self):
        """「这上面的 MCP / skill 跟 GitHub 是不是一块儿的」必须在界面上答得出来。

        一个 GitHub 仓库接进来之后**就变成**一个 MCP 工具或一个 Skill，注册进的是
        全系统共用的那套 MCP 网关与 SkillLoader（见 core/github_installer.py 的
        ``_register_mcp_tool`` / ``_register_skill``）。不把这句话写在脸上，卡片上
        那个 ``mcp`` 徽章会被当成"另一类东西"。

        反过来同样要说清：这份清单**只**列从 GitHub 接进来的，系统自带的不在这里。
        看到"2 个"就以为全系统只有 2 个 MCP 工具，是同一种误读。
        """
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        assert "会变成一个 MCP 工具或一个 Skill" in ui, "没说清 MCP / Skill 就是这个仓库变成的样子"
        assert "只列" in ui and "系统自带的" in ui, "没说清这份清单不包含系统自带的那些"

    def test_no_markdown_markers_leak_into_visible_text(self):
        """界面上的字是**给人读的**，不是 Markdown。

        这条是被真实结果补出来的：我在 hint 里照着代码注释的习惯写了
        ``只列**从 GitHub 接进来的**``，而 ``textContent`` 不解析 Markdown ——
        渲染出来就是两串星号摆在句子中间。注释里的强调写法和界面文案用的是
        同一双手，所以这个错会反复犯，得有门挡着。

        整个 panel/src 一起扫，不只扫新加的那一段。
        """
        import re

        bad = []
        for f in sorted(PANEL_SRC.rglob("*.ts")):
            src = f.read_text(encoding="utf-8")
            for m in re.finditer(r"(?:textContent|placeholder)\s*=\s*\n?\s*'((?:[^'\\]|\\.)*)'", src):
                if "**" in m.group(1) or "``" in m.group(1):
                    bad.append(f"{f.name}: {m.group(1)[:80]}")
        assert not bad, "界面文案里混进了 Markdown 标记（textContent 不解析它，会原样显示）：\n" + "\n".join(bad)

    def test_the_policy_line_is_not_dressed_up_as_a_card(self):
        """准入策略是一句说明文字，不是一张卡片。

        给说明文字套上圆角底色内阴影，会在这一页上多出一种谁都没有的容器：
        上面那 335 个键是裸行，端点和插件是对象卡片，而它只是一句
        "接下来会发生什么"。套了框它就会被当成一个可操作的对象。
        """
        css = (PANEL_SRC / "styles/hud.css").read_text(encoding="utf-8")
        block = css.split(".ga-policy {", 1)[1].split("}", 1)[0]
        for forbidden in ("border-radius", "background:", "box-shadow"):
            assert forbidden not in block, f".ga-policy 又被做成了一个框（{forbidden}）"
