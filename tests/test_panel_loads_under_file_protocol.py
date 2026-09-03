"""面板的构建产物必须能在 ``file://`` 下真的挂起来。

Electron 用 ``loadFile()`` 打开 ``electron/renderer/panel/dist/index.html`` ——
**协议是 file://,不是 http://**。这条路径上有三个坑,每一个都表现为「面板打不开
而且没有任何报错」(面板窗口是 transparent 的,脚本没跑就是一片空):

1. ``<script type="module">`` 在 file:// 下会被 CORS 直接拦掉::

       Access to script at 'file:///…/index.js' from origin 'null' has been
       blocked by CORS policy: Cross origin requests are only supported for
       protocol schemes: chrome, chrome-extension, …, http, https

   跟 ``crossorigin`` 属性无关,``module`` 这个类型本身就走 CORS。所以产物打成
   经典脚本(IIFE),并在 HTML 里去掉 ``type="module"``。

2. 绝对路径 ``/assets/…`` 在 file:// 下解析到**文件系统根目录**。所以
   ``vite.config.ts`` 里 ``base: './'``。

3. 经典脚本**不像 module 那样默认 defer**:标签在 ``<head>`` 里就立刻执行,那一刻
   ``#hud`` 还不存在。所以标签要带 ``defer``,并且 ``main.ts`` 自己也等一次 DOM。

这三条都是**构建配置**决定的,改一行 vite 配置就可能悄悄退回去。这个文件用静态
检查把它们钉住 —— 不需要浏览器,CI 的任何一片都能跑。

真正「打开看它有没有挂上」的那一步需要浏览器,不适合放进 pytest 分片;它由
本地的 Playwright 探针完成,结论记在这里:构建产物在 file:// 下 ``.shell`` /
``.island`` / ``.dock`` 都在,``document.fonts`` 里有 Onest。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PANEL = REPO_ROOT / "electron" / "renderer" / "panel"
DIST_HTML = PANEL / "dist" / "index.html"
VITE_CONFIG = PANEL / "vite.config.ts"
MAIN_TS = PANEL / "src" / "main.ts"


@pytest.fixture(scope="module")
def dist_html() -> str:
    if not DIST_HTML.exists():
        pytest.fail(
            f"{DIST_HTML.relative_to(REPO_ROOT)} 不存在。"
            "dist/ 必须提交进仓库 —— Electron 生产环境直接加载它,"
            "CI 的 panel-dist-consistency 门也直接 git diff 它。"
            "修法: cd electron/renderer/panel && npm ci && npm run build"
        )
    return DIST_HTML.read_text(encoding="utf-8")


class TestTheBuiltPageCanLoadOverFileProtocol:
    def test_no_module_script(self, dist_html: str) -> None:
        """``type="module"`` 会被 file:// 的 CORS 拦掉,脚本根本不执行。"""
        offenders = re.findall(r"<script[^>]*\btype=[\"']module[\"'][^>]*>", dist_html)
        assert not offenders, (
            '构建产物里还有 type="module" 脚本 —— file:// 下会被 CORS 拦掉,' f"面板会白屏且不报错: {offenders}"
        )

    def test_no_crossorigin_attribute(self, dist_html: str) -> None:
        """``crossorigin`` 同样触发 CORS 检查。"""
        offenders = re.findall(r"<(?:script|link)[^>]*\bcrossorigin\b[^>]*>", dist_html)
        assert not offenders, f"构建产物里还有 crossorigin 属性: {offenders}"

    def test_scripts_are_deferred(self, dist_html: str) -> None:
        """经典脚本不默认 defer;在 <head> 里立刻执行的话 ``#hud`` 还不存在。"""
        scripts = re.findall(r"<script\b[^>]*\bsrc=[^>]*>", dist_html)
        assert scripts, "构建产物里一个带 src 的 script 都没有?"
        missing = [s for s in scripts if not re.search(r"\b(defer|async)\b", s)]
        assert not missing, (
            "这些脚本既不是 module 也没有 defer —— 会在 <head> 阶段立刻执行,"
            f"那时 #hud 还不存在,面板什么都不挂: {missing}"
        )

    def test_asset_paths_are_relative(self, dist_html: str) -> None:
        """绝对路径在 file:// 下解析到文件系统根目录。"""
        abs_refs = re.findall(r"(?:src|href)=[\"'](/[^\"']*)[\"']", dist_html)
        assert not abs_refs, (
            "构建产物引用了绝对路径 —— file:// 下会解析到文件系统根目录,"
            f"资源全部 404。vite.config.ts 里要设 base: './': {abs_refs}"
        )

    def test_the_mount_point_exists(self, dist_html: str) -> None:
        assert 'id="hud"' in dist_html, "页面里没有 #hud,面板无处可挂"


class TestTheBuildConfigStillEnforcesIt:
    """产物是对的,但配置改一行就会悄悄退回去。把三条约束钉在配置上。"""

    @pytest.fixture(scope="class")
    def vite_src(self) -> str:
        return VITE_CONFIG.read_text(encoding="utf-8")

    def test_base_is_relative(self, vite_src: str) -> None:
        assert re.search(r"base:\s*['\"]\./['\"]", vite_src), "vite.config.ts 里没有 base: './' —— 产物会引用绝对路径"

    def test_output_format_is_classic(self, vite_src: str) -> None:
        assert re.search(
            r"format:\s*['\"]iife['\"]", vite_src
        ), "输出格式不是 iife —— ES module 产物在 file:// 下加载不了"

    def test_demo_data_is_off_in_the_committed_page(self, dist_html: str) -> None:
        """演示数据绝不能随产物出厂。

        塞了假数据的话,「有卡片」和「后端没接上」在界面上就分不开了 —— 用户会
        以为记忆卡片已经接好,其实那几张是写死的。
        """
        m = re.search(r'name="galaxy-demo"\s+content="([^"]*)"', dist_html)
        assert m is not None, "构建产物里找不到 galaxy-demo 这个 meta"
        assert m.group(1) != "on", "构建产物里 galaxy-demo=on —— 演示数据会出厂," "用户看到的假卡片和真数据分不开"


class TestMountingDoesNotDependOnScriptPlacement:
    def test_main_waits_for_the_dom(self) -> None:
        """挂载不该只靠「标签属性没被人改坏」。"""
        src = MAIN_TS.read_text(encoding="utf-8")
        assert (
            "DOMContentLoaded" in src and "readyState" in src
        ), "main.ts 没有等 DOM —— 一旦构建产物的 defer 丢了,面板就静默不挂"


class TestTheShellDoesNotScrollAwayWhenTheThreadIsLong:
    """对话一长,输入栏不许被推出视口。

    ``.main`` 是 ``.panel``(grid)的项,而 **grid / flex 项的 ``min-height``
    默认是 ``auto``** —— 它拒绝缩到比内容更矮。少了 ``min-height: 0``,对话一长
    ``.main`` 就跟着内容长到两千多像素,``.thread`` 的 ``flex:1`` 按那个被撑大的
    高度算,``overflow-y:auto`` 永远不生效,底下那条输入栏被推到视口外一千八百
    像素的地方 —— **够不着**。

    实测过:30 条历史时 ``.main`` 高 2646px、``.thread`` 高 2604px 且
    ``scrollHeight == clientHeight``(根本没在滚)、``.dock`` 的 top 是 2624px,
    而视口只有 860px。

    这个 bug 一直在,只是从前面板每次打开都是空白对话所以没人撞上 —— 把历史接
    回来的那一刻它才露出来。所以这条钉在 CSS 上:一行删掉就红。
    """

    def test_main_can_shrink_below_its_content(self) -> None:
        css = (PANEL / "src" / "styles" / "hud.css").read_text(encoding="utf-8")
        block = re.search(r"\.main\s*\{([^}]*)\}", css)
        assert block, "hud.css 里找不到 .main 了?"
        body = block.group(1)
        assert "min-height: 0" in body, (
            ".main 少了 min-height: 0 —— 它是 grid 项,默认 min-height:auto 会拒绝缩到"
            "比内容矮,于是对话一长 .thread 就不滚了,输入栏被推出视口"
        )

    def test_the_thread_is_the_one_that_scrolls(self) -> None:
        css = (PANEL / "src" / "styles" / "hud.css").read_text(encoding="utf-8")
        block = re.search(r"\.thread\s*\{([^}]*)\}", css)
        assert block, "hud.css 里找不到 .thread 了?"
        body = block.group(1)
        assert "overflow-y: auto" in body, "对话区不再自己滚 —— 那就得整页滚,外壳会跟着走"
        assert "min-height: 0" in body, ".thread 自己也要能缩,否则它把 .main 顶开"
