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
    """把安装根指到临时目录，绝不碰开发机上真的 data/github_addons。

    **只设环境变量是不够的。** 这一条是踩出来的：第一版只 monkeypatch 了
    `GITHUB_INSTALL_DIR`，而路由拿的是 `get_github_installer()` —— 一个在 import
    时就构造好的单例，它的 `_install_dir` 和 `_manifest` 早就按默认路径定死了。
    结果那条端到端用例真的往仓库里的 `data/github_addons/` 克隆了一份 README，
    还被我一起提交了上去。

    所以这里把**单例本身**的两个字段都指到 tmp_path，跑完 monkeypatch 自动还原。
    """
    monkeypatch.setenv("GITHUB_INSTALL_DIR", str(tmp_path))
    from core.github_installer import _ManifestStore, get_github_installer

    inst = get_github_installer()
    monkeypatch.setattr(inst, "_install_dir", tmp_path)
    monkeypatch.setattr(inst, "_manifest", _ManifestStore(tmp_path))

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

    def test_list_always_returns_an_addons_array(self, client):
        """``addons`` 永远是一个数组，哪怕一个都没有。

        给 null、或干脆不给这个键，前端就分不清"没装过"和"拉不到"——那两件事
        在界面上必须说成两句话。

        这里断言的是**形状**，不是长度。第一版写的是 `== []`，它单独跑是绿的，
        和别的用例一起跑就红：installer 是个单例，manifest 是共享的，同一轮里
        别的用例装过东西。断言长度等于把一条形状门变成了一条依赖全局状态的门，
        而那种门迟早会被人用 `-p no:randomly` 之类的办法绕过去，而不是修好。
        """
        body = client.get("/api/v1/github/list").json()
        assert "addons" in body, "列表端点没有 addons 这个键"
        assert isinstance(body["addons"], list), f"addons 不是数组：{type(body['addons'])}"


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


class TestAProjectWithNoContractIsASuccessfulInstall:
    """接一个普通仓库（没有 mcp_tool.json / skill.json / SKILL.md）是一次**成功**的接入。

    MCP / Skill 是 GitHub 项目的交集，不是它的定义：接一个仓库可能是为了拿它跑实验、
    读它、拿它当素材。改之前 `install_success` 对所有类型一律看
    `registration && verification`，而普通仓库那条路的 registration 被写死成
    `success: False`，于是它**永远**返回 success=False + HTTP 400 —— 面板上只能
    显示成一次失败，而它明明成功了。
    """

    def test_the_three_forms_come_from_one_place(self):
        from core.github_addon_integration import integration_form

        assert integration_form("mcp") == "mcp"
        assert integration_form("skill") == "skill"
        assert integration_form("skill_md") == "skill", "skill_md 是 Skill 的一种写法，不是第三种形态"
        assert integration_form("ordinary_tool_repo") == "project"
        assert (
            integration_form("something-new-later") == "project"
        ), "认不出的类型没有归到 project —— 认不出的东西要少说一句话，不能多说一句假话"

    def test_no_contract_means_success_with_state_cloned_only(self):
        from core.github_addon_integration import build_integration, cloned_only_results

        reg, ver = cloned_only_results()
        integration, ok, state = build_integration("ordinary_tool_repo", reg, ver)
        assert ok is True, "接一个普通项目被判成了失败"
        assert integration["form"] == "project"
        assert integration["ok"] is True
        assert state == "cloned_only", "落点状态被 success 带成了 verified"
        assert integration["detail"], "没说清它以什么形式接进来的"

    def test_a_contract_that_fails_to_register_is_still_a_failure(self):
        """反面保险：这条改动放宽的只有"没有契约"那一档。

        没有这一条，上面那条在"所有类型一律判成功"的实现下也会绿 ——
        而那会把真正接坏的插件说成接好了。
        """
        from core.github_addon_integration import build_integration

        integration, ok, state = build_integration(
            "mcp", {"success": False, "error": "entrypoint 不存在"}, {"success": False}
        )
        assert ok is False
        assert integration["form"] == "mcp"
        assert state == "registration_or_verification_failed"
        assert "entrypoint 不存在" in integration["detail"], "没说清卡在哪一步"

    def test_the_cloned_only_results_carry_a_message_not_an_error(self):
        """两份结果都不带 error。

        带 error 的话，任何一个按"有没有 error"判成败的消费者都会把它读成失败 ——
        而这正是改之前那个行为的来源。
        """
        from core.github_addon_integration import cloned_only_results

        for part in cloned_only_results():
            assert "error" not in part, f"项目形态的结果里带着 error：{part}"
            assert part.get("message"), f"既没有 error 也没有 message，什么都没说：{part}"

    def test_the_route_returns_200_for_a_project_form_install(self, client, monkeypatch, tmp_path):
        """端到端：HTTP 状态码也要跟着对。

        路由是 `200 if result["success"] else 400`。只改 success 而不核这一条，
        面板拿到的仍然是一个 400 —— 而 transport 那边把 400 当成"后端拒绝了"。
        """
        import core.github_installer as gi

        repo_src = tmp_path / "src"
        repo_src.mkdir()
        (repo_src / "README.md").write_text("just a project\n", encoding="utf-8")

        def _fake_fetch(owner, repo, ref, dest):  # noqa: ANN001,ARG001
            import shutil

            shutil.copytree(repo_src, dest, dirs_exist_ok=True)
            return "0" * 40

        monkeypatch.setattr(gi, "_fetch_repo", _fake_fetch)
        monkeypatch.setenv("GITHUB_ALLOWLIST", "owner/plain-repo")

        resp = client.post("/api/v1/github/install", json={"url": "https://github.com/owner/plain-repo"})
        assert resp.status_code == 200, f"接一个普通项目被回了 {resp.status_code}：{resp.text[:300]}"
        body = resp.json()
        assert body["success"] is True
        assert body["integration"]["form"] == "project"
        assert body["install_state"] == "cloned_only"
        assert body["classification"]["integrable"] is False, "没说清它不是一个可调用工具"


class TestTheUiDoesNotInventWhatTheBackendDidNotSay:
    """界面上每一个判断都要有后端的出处。"""

    def test_the_panel_does_not_derive_the_approval_mode_itself(self):
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        transport = (PANEL_SRC / "transport.ts").read_text(encoding="utf-8")
        assert "approval_mode" in transport, "transport.ts 没有读后端给的安装策略"
        assert "approvalMode" in ui, "界面上没有把安装策略说出来"
        for env in ("GITHUB_ALLOWLIST", "GALAXY_ADDON_UNATTENDED"):
            assert env not in ui, f"界面自己读了 {env} —— 那就成了第二处权威，规则改一次两边分家"

    def test_the_section_routes_projects_and_tools_into_separate_columns(self):
        """这一段里混着两种东西，要**分流**：左边项目，右边接出来的工具。

        "我接了一个项目"和"我多了一个模型能调的工具"是两件事，人来这一页找的
        往往只是其中一件。混成一列时，想找项目的人要在一堆工具里扒，反之亦然。
        """
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        css = (PANEL_SRC / "styles/hud.css").read_text(encoding="utf-8")
        assert "'ga-split'" in ui, "没有分流，还是一列"
        assert "const target = def.form === 'project' ? colLeft : colRight;" in ui, "分流的去向不是按形态定的"
        assert ".ga-split {" in css and "grid-template-columns" in css.split(".ga-split {", 1)[1].split("}", 1)[0]

    def test_every_addon_lands_in_exactly_one_group(self):
        """一张卡片必须落进某一组，一个都不许掉在两边之外。

        掉出去的那一条**不会报错**，它只是从界面上消失 —— 而"我明明装过"和
        "它不见了"之间没有任何提示，这正是最难发现的那种坏法。认不出的形态
        归到「项目」：少说一句话是安全的，悄悄消失不是。
        """
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        assert "byForm.get(a.form) ?? byForm.get('project')!" in ui, "认不出的形态没有兜底，会从界面上消失"
        forms = {"project", "mcp", "skill"}
        declared = {m for m in forms if f"form: '{m}' as const" in ui}
        assert declared == forms, f"分组名单缺了：{forms - declared}"

    def test_groups_collapse_natively_and_empty_ones_are_still_drawn(self):
        """用原生 <details>，而且空组照样画出来。

        自己造一套展开收缩，要把键盘操作、无障碍语义、状态同步各补一遍，
        每补一遍都是一次出错的机会。

        空组不许省：「一个 Skill 都没接过」和「这里根本没有 Skill 这一档」
        是两件事。这条和左栏底下那块「接上了什么」第 3 条规矩是同一条。
        """
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        assert "createElement('details')" in ui, "没用原生 details，自己造了一套"
        assert "createElement('summary')" in ui
        assert "box.open = rows.length > 0" in ui, "空组没有默认收起"
        assert "这一档还没有" in ui, "空组什么都不画 —— 那一档在界面上就不存在了"

    def test_each_group_has_an_icon_drawn_the_way_the_panel_draws_icons(self):
        """分组要有图标，而且用面板**已有**的那一种画法。

        多一种画法就要多认一次；而且 dock.ts 那个 helper 已经把 24 格、
        currentColor 描边、圆头圆角定死了，另起一套迟早对不齐。
        """
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        dock = (PANEL_SRC / "ui/dock.ts").read_text(encoding="utf-8")
        assert "head.append(icon(def.path)" in ui, "分组标题上没有图标"
        for attr in ("viewBox', '0 0 24 24'", "stroke', 'currentColor'"):
            assert attr in ui and attr in dock, f"图标画法和 dock.ts 那套对不上：{attr}"

    def test_a_contract_that_was_present_but_not_chosen_is_named(self):
        """根上还摆着别的契约、但没被选中 —— 要说出来。

        判定是"第一个命中就停"（mcp → skill → SKILL.md）。一个同时带
        mcp_tool.json 和 skill.json 的仓库，后者是**被忽略了**。不说的话，
        人会以为那份文件有问题；说了他才知道这是判定顺序，不是坏了。
        """
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        assert "a.contracts[k].present && !a.contracts[k].chosen" in ui, "没被选中的契约被当成不存在"
        assert "没被选中" in ui

    def test_there_is_no_mhs_group_and_the_reason_is_on_file(self):
        """右栏只有两组，没有 MHS —— 而且这条是**有据**的，不是忘了做。

        MHS（Model Hardware Standard，Anthropic 2026-08-27 研究预览）在
        `docs/EXTERNAL_AGENT_FRAMEWORK_EVALUATION.md` 第 ④ 节已经判过：至今没有
        公开规范、没有 SDK、没有 schema、没有一致性测试，"接入"只能照新闻稿
        把消息格式编出来 —— 那不是实现协议，是造一个同名的赝品。那份文档还专门
        写了一节「也不放占位模块」，理由是本仓的历史：一路删掉的正是这种
        "先声明、以后再实现"的空架子。

        一个**永远是空的、而且永远填不满**的分组，就是界面版的占位模块。

        这条门有两半：既挡住"哪天有人顺手把空分组加回去"，也挡住"那份判断被
        删掉之后没人记得为什么不做"。规范真开源了，该做的是改这条门，
        而不是绕过它。
        """
        doc = (PANEL_SRC.parents[3] / "docs/EXTERNAL_AGENT_FRAMEWORK_EVALUATION.md").read_text(encoding="utf-8")
        assert "MHS" in doc and "也不放占位模块" in doc, "那份判断不在了 —— 不做 MHS 就成了一句没来由的话"

        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        groups = ui.split("const GROUPS = [", 1)[1].split("] as const;", 1)[0]
        assert "mhs" not in groups.lower(), "右栏加了一个永远填不满的 MHS 分组"
        assert "EXTERNAL_AGENT_FRAMEWORK_EVALUATION" in ui, "没写明为什么只有两组 —— 下一个人会当成漏做"

    def test_state_is_told_with_light_and_depth_never_with_hue(self):
        """状态不许用颜色说。

        这条不是审美偏好，是这个仓已经判过一次的事：左栏底下那块「接上了什么」
        原先是红/黄/绿/空心四个彩色小点，所有者的原话写在 `.wired-dot` 那段注释里
        ——「那个点儿就是红绿绿黄，是有点不太好看……可以通过白光加动效的方式，
        让人体会，而不是这种奇怪的颜色」。这一面上只有一支色相，彩色小点是整面
        唯一跳出来的东西。

        我在第一版里又犯了一次（绿点 / 琥珀点）。所以写成门：凡是给这一段里的
        小圆点定底色的规则，底色只能是中性的白/灰，不能带色相。

        颜色仍然可以用在**字**上——「没人把关」「没接上」是需要人看见的一句话，
        而字那一层没有深度可用。门只管点。
        """
        import re

        css = (PANEL_SRC / "styles/hud.css").read_text(encoding="utf-8")
        hued = ("var(--warn)", "var(--bad)", "var(--a-mid)", "var(--a-hi)", "var(--a-lo)")
        offenders = []
        for m in re.finditer(r"(\.ga-[^{}]*\.ga-dot[^{]*)\{([^}]*)\}", css):
            selector, body = m.group(1).strip(), m.group(2)
            for decl in body.split(";"):
                if "background" not in decl:
                    continue
                if any(h in decl for h in hued):
                    offenders.append(f"{selector} → {decl.strip()}")
                    continue
                for hexcol in re.findall(r"#([0-9a-fA-F]{3,8})", decl):
                    h = hexcol[:6]
                    if len(h) >= 6 and not (h[0:2] == h[2:4] == h[4:6]):
                        offenders.append(f"{selector} → {decl.strip()}")
        assert not offenders, "这一段的状态点用了色相（这个仓已经判过一次不要）：\n" + "\n".join(offenders)

    def test_the_card_is_inset_not_a_raised_block(self):
        """卡片是内嵌的：底色就是这一页的底色，边界靠一圈内凹痕迹说。

        第一版和隔壁 `.up-card` 一样，是自带渐变底、带外投影的浮起卡片。排成一列
        之后整段变成一串亮条摞在页面上，而这一页其余地方全是裸行——同一个页面上
        两种重量，那块东西看着就是贴上去的。
        """
        css = (PANEL_SRC / "styles/hud.css").read_text(encoding="utf-8")
        block = css.split(".ga-card {", 1)[1].split("}", 1)[0]
        assert "background: transparent" in block, "卡片自带了填充 —— 那就不是内嵌的"
        shadow = block.split("box-shadow:", 1)[1].split(";", 1)[0]
        assert shadow.count("inset") >= 2, "边界痕迹不是内凹的"
        # 按**顶层**逗号切。第一版直接 split(",")，结果被 rgba(93, 84, 102, .11)
        # 里的逗号切碎，断言对着一个 " 84" 报错——一条自己解析错了的门，
        # 报出来的话会把人引到完全不相干的地方。
        parts, depth, cur = [], 0, ""
        for ch in shadow:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(cur)
                cur = ""
            else:
                cur += ch
        parts.append(cur)
        for part in parts:
            if not part.strip():
                continue
            assert "inset" in part, f"卡片带着一道外投影（浮起来了）：{part.strip()}"

    def test_the_project_group_says_it_holds_no_callable_tools(self):
        """「项目」那一组必须**说出**它里面的东西不是可调用工具。

        不说的话，两栏看起来就是并列的两堆工具 —— 那就从"把成功说成失败"
        翻到了另一头，变成"把没接成工具说成接成了"。
        """
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        assert "不注册成可调用的工具" in ui, "「项目」这一组没说清它不是可调用工具"

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

    def test_an_unknown_form_is_named_not_silently_filed_as_a_project(self):
        """后端将来多一档形态时，那张卡片要**说**自己认不出，而不是装成普通项目。

        分流的兜底是把它放进「项目」组——那是为了不让它从界面上消失。但光有兜底
        还不够：它会静静躺在项目堆里，看起来就是一个普通项目，而界面就在替后端
        说一句它没说过的话。

        两件事要同时做到：**不消失**（兜底）和**不伪装**（这一行）。
        """
        ui = (PANEL_SRC / "ui/github_addons.ts").read_text(encoding="utf-8")
        assert "!GROUPS.some((g) => g.form === a.form)" in ui, "认不出的形态没有被识别出来"
        assert "这个面板还不认识" in ui, "认不出的形态悄悄装成了普通项目"

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
        assert "不一定要让它变成工具" in ui, "没说清接项目 ≠ 接工具"
        assert "顺带注册成一个 MCP 工具或一个 Skill" in ui, "没说清 MCP / Skill 是顺带的那一档"
        assert "同样是一次成功的接入" in ui, "没说清项目形态也是成功"
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
