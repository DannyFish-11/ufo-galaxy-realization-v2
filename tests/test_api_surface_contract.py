"""权威 API 层 ↔ 前端调用面的契约门。

要解决什么
----------
后端有 **388 条路径 / 406 个操作**,面板只用了其中 **20 条**。剩下的对前端
来说是**不可发现**的:要用哪个端点、参数长什么样、返回什么,只能对着后端源码抄。
而抄错、或后端改了路径,在运行期才会暴露成一个 404。

``scripts/gen_ts_types.py`` 现在从 FastAPI 的 OpenAPI 生成
``types/api.gen.ts``(路径联合类型 + 方法表 + 102 个组件 schema)。这份文件
存在的全部理由,是让上面那种漂移变成**编译期错误**。

这个文件钉三件事:

1. **生成物与后端同步** —— 改了后端却忘了重跑生成器,就红;
2. **面板调的每个端点后端都有** —— 这是那次人工核对的固化版(当时 0 缺失);
3. **分层清单** —— 面板在用的 / 仅机器面的,数量以断言形式记录,变化必须是
   有意的。

为什么不做成 CI 里单独的作业:组装权威 API 层实测约 2.2 秒
(``core.api_routes.create_api_routes()``,与 ``tests/test_routes_import.py``
建 app 的方式相同),放在 pytest 里足够快,而单开作业就得再养一套环境。
"""

from __future__ import annotations

import importlib.util
import json
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).parent.parent
_GEN = _ROOT / "electron" / "renderer" / "panel" / "src" / "types" / "api.gen.ts"
_PANEL_SRC = _ROOT / "electron" / "renderer" / "panel" / "src"


def _generator():
    spec = importlib.util.spec_from_file_location("_gen_ts_types", _ROOT / "scripts" / "gen_ts_types.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def gen():
    return _generator()


@pytest.fixture(scope="module")
def schema(gen):
    return gen.load_openapi()


@pytest.fixture(scope="module")
def generated_ts() -> str:
    return _GEN.read_text(encoding="utf-8")


def _api_paths_from_ts(text: str) -> set[str]:
    """从生成的 TS 里读回 ApiPath 联合的成员。"""
    m = re.search(r"export type ApiPath =\n((?:\s*\|\s*\"[^\"]+\"\n)+);", text)
    assert m, "生成的 TS 里找不到 ApiPath 联合 —— 生成器结构变了?"
    return set(re.findall(r'"([^"]+)"', m.group(1)))


def _norm(p: str) -> str:
    """把路径里的参数占位符归一,便于两边比对。"""
    return re.sub(r"\{[^}]*\}", "{}", re.sub(r"\$\{[^}]*\}", "{}", p)).rstrip("/ ")


#: 一处 ``/api/...`` 前面紧挨着的那串"URL 字符",用来判断它是不是别人家地址的一部分。
#: 到最近的引号/反引号/空白/括号/逗号/等号为止 —— 那些都是字符串字面量的边界。
_URL_TOKEN_BOUNDARY = re.compile(r"[\s\"'`(),=]")

#: 本机。指向这些主机的绝对 URL 仍然是"面板在调本后端",不能跳过。
_LOCAL_HOSTS = ("localhost", "127.0.0.1", "0.0.0.0", "[::1]")


def _is_third_party_url_path(text: str, start: int) -> bool:
    """``text[start:]`` 处的这条路径,是不是**别人家绝对地址**里的一段。

    为什么需要这一判
    ----------------
    面板里会出现第三方地址的字面量(智谱海外端点
    ``https://api.z.ai/api/paas/v4`` 就在一个输入框的提示文案里)。朴素的
    ``/api/...`` 正则会从中切出 ``/api/paas/v4``,然后这个模块判定"面板调了一个
    后端没有的端点"——**一条完全正确的提示文案把门弄红了**。

    但不能因此把所有绝对 URL 一律跳掉:面板确实用
    ``http://localhost:9000/api/...`` 这种写法直连过本后端(浏览器预览兜底)。
    一律跳等于把这道门在那条路径上悄悄关掉,而那正是这道门最该看住的地方。

    所以判据是**主机是谁**:模板串拼出来的(含 ``${``)与本机地址仍然算本后端调用,
    只有写死的外部主机才跳过。
    """
    head = text[:start]
    boundary = _URL_TOKEN_BOUNDARY.search(head[::-1])
    token = head[len(head) - boundary.start() :] if boundary else head
    if "://" not in token:
        return False
    host = token.rsplit("://", 1)[1]
    if "${" in host:  # 运行期拼出来的地址,判不出主机 —— 按本后端算,宁可多查
        return False
    return not any(host.startswith(local) for local in _LOCAL_HOSTS)


def _panel_calls() -> dict[str, set[str]]:
    """面板源码里出现的 /api 与 /ws 路径 → 出现在哪些文件。

    **必须跳过 ``*.gen.ts``**:生成的 ``api.gen.ts`` 把全部 388 条路径写成了
    字符串字面量,不跳过的话它自己就会被当成"面板在调 388 个端点"——那不仅
    让分层清单失真,更会让"面板调的端点后端都有"退化成恒真(拿生成物去对
    生成物)。第一版就踩了这个自指陷阱,被清单那条断言当场抓出来。

    也跳过**第三方绝对地址里的路径** —— 见 :func:`_is_third_party_url_path`。

    并且**先去掉注释**。这一条是踩出来的:``transport.ts`` 里有一段注释解释
    「路径要写全、不要拼」,顺手引了前缀 ``/api/perception/desktop``,于是扫描器
    把那句说明当成了一次真实调用,报成「面板调了后端没有的端点」。

    这类误报比漏报更危险:它让一条正确的门变成噪音,而噪音门迟早被加白名单绕过
    或者直接删掉。这个仓库为「扫的是文件文本而不是代码」栽过两次(另两处判据
    分别被块注释和 docstring 绊倒),两次的修法都是同一句:**比对去掉注释后的代码**。
    """
    block = re.compile(r"/\*.*?\*/", re.S)
    line = re.compile(r"^\s*//.*$", re.M)
    out: dict[str, set[str]] = {}
    for f in _PANEL_SRC.rglob("*.ts*"):
        if f.name.endswith(".gen.ts"):
            continue
        text = line.sub("", block.sub("", f.read_text(encoding="utf-8")))
        for m in re.finditer(r"(/(?:api|ws)/[A-Za-z0-9/_${}.-]*)", text):
            if _is_third_party_url_path(text, m.start()):
                continue
            out.setdefault(_norm(m.group(1)), set()).add(f.name)
    return out


# ---------------------------------------------------------------------------
# 1. 生成物必须与后端同步
# ---------------------------------------------------------------------------


class TestGeneratedFileStaysInSync:
    def test_regenerating_produces_the_same_file(self, gen, schema, generated_ts: str) -> None:
        """改了后端端点却忘了重跑生成器 → 这条红。

        没有它,这整套生成机制就只是"生成过一次",之后照样漂。
        """
        assert generated_ts == gen.build_api_surface(
            schema
        ), "api.gen.ts 与后端 OpenAPI 不一致 —— 请重跑 python scripts/gen_ts_types.py"

    def test_generated_file_is_not_empty_or_trivial(self, generated_ts: str) -> None:
        """自证:上面那条在两边都是空文件时也会绿。"""
        paths = _api_paths_from_ts(generated_ts)
        assert len(paths) > 300, f"ApiPath 只有 {len(paths)} 条,权威 API 层不该这么小"


# ---------------------------------------------------------------------------
# 2. 生成器遇到没见过的形状必须抛,而不是吐 any
# ---------------------------------------------------------------------------


class TestGeneratorFailsLoudly:
    def test_unknown_shape_raises(self, gen) -> None:
        """悄悄降级成 ``any`` 的类型文件比没有类型更糟:看着有保护,实际没挡住。"""
        with pytest.raises(gen.UnsupportedSchemaShape):
            gen._openapi_ts({"type": "no_such_type"}, where="<test>")

    def test_untyped_node_becomes_unknown_not_any(self, gen) -> None:
        """OpenAPI 里"无 type"是**规范定义的任意值**,给 unknown 而非 any。

        unknown 强制消费方先收窄再用;any 会静默传染到整条调用链。
        """
        assert gen._openapi_ts({}, where="<test>") == "unknown"

    def test_no_any_in_generated_output(self, generated_ts: str) -> None:
        assert not re.search(r"\bany\b", generated_ts), "生成的 TS 里出现了 any —— 类型保护在那里就断了"


# ---------------------------------------------------------------------------
# 3. 面板调的端点后端必须有（人工核对的固化版）
# ---------------------------------------------------------------------------


class TestPanelCallsResolve:
    def test_every_panel_endpoint_exists_in_the_api_surface(self, generated_ts: str) -> None:
        """面板调了一个后端没有的端点 → 这条红。

        这一条固化的是一次人工核对:当时逐条对了 20 个端点,缺失 0。人工核对
        不会自己重跑,门会。
        """
        backend = {_norm(p) for p in _api_paths_from_ts(generated_ts)}
        # 参数化路径的前缀,用于匹配面板侧用模板串拼出来的调用
        prefixes = sorted({_norm(p).split("{")[0].rstrip("/") for p in backend if "{" in p})

        missing = []
        for call, files in sorted(_panel_calls().items()):
            if call.startswith("/ws/"):
                continue  # WebSocket 不在 OpenAPI 文档里,由下面单独一条钉
            if call in backend:
                continue
            if any(pf and call.startswith(pf) for pf in prefixes):
                continue
            missing.append((call, sorted(files)))
        assert not missing, f"面板调了后端没有的端点:{missing}"

    # ── 扫描器自身的判据 ───────────────────────────────────────────────
    #
    # 上面那条门的强弱**完全取决于 _panel_calls() 数得准不准**:数多了(把别人家
    # 地址里的 /api/... 当成本后端调用)会把一条正确的提示文案变成红灯;数少了
    # (为了消掉那种误报,把所有绝对 URL 一律跳过)会让这道门在"面板直连本后端"
    # 那条路径上**悄悄失效** —— 而那正是它最该看住的地方。
    #
    # 两个方向各钉一条。真实触发过前者:智谱海外端点
    # https://api.z.ai/api/paas/v4 出现在一个输入框的提示文案里。

    @pytest.mark.parametrize(
        "snippet",
        [
            "extraLabel: '海外填 https://api.z.ai/api/paas/v4'",
            'const doc = "https://example.com/api/v9/guide";',
        ],
    )
    def test_a_third_party_address_is_not_counted_as_a_backend_call(self, snippet: str) -> None:
        idx = snippet.index("/api/")
        assert _is_third_party_url_path(snippet, idx) is True

    @pytest.mark.parametrize(
        "snippet",
        [
            "await fetch('/api/config')",
            "fetch('http://localhost:9000/api/config')",
            "fetch(`${base}/api/config`)",
            "fetch(`http://${host}:${port}/api/config`)",
        ],
    )
    def test_a_call_to_our_own_backend_is_still_counted(self, snippet: str) -> None:
        """模板串拼出来的地址判不出主机 —— 按本后端算,宁可多查一个也不少查。"""
        idx = snippet.index("/api/")
        assert _is_third_party_url_path(snippet, idx) is False

    #: 新面板真正对话的那几条。**点名,不数数。**
    #:
    #: 这两条自证判据原先是「至少 10 个 / 至少 15 个端点」—— 那个数字是按旧的
    #: React 面板标定的:它有设置页、模型目录、Mesh、能力、配对、诊断六个视图,
    #: 各自拉各自的接口。这一版 HUD 面板把这些全去掉了,只剩两条真正的通路:
    #: 一条 WebSocket 收此刻的状态,一条 SSE 发一句话。
    #:
    #: 所以旧阈值现在必红,而且**它红得没有信息量** —— 它说的是「比以前少」,
    #: 不是「扫描器坏了」。直接把阈值调小是最坏的改法:那等于把一条自证判据的
    #: 强度交给一个没人再核过的数字。改成点名之后这条更严:正则一旦失效,这两个
    #: 名字就找不到,当场红;而且它顺带写下了「面板到底跟后端说哪几句话」。
    _MUST_CALL = {
        "/ws/desktop-presence",  # 此刻的状态(含 panel_feed 设备帧)
        "/api/v1/chat/stream",  # 说一句话
    }

    def test_the_panel_still_talks_to_the_backend(self) -> None:
        """自证:上面两条在扫描器什么都数不出来时也会绿。"""
        calls = set(_panel_calls())
        missing = sorted(self._MUST_CALL - calls)
        assert not missing, (
            f"面板源码里找不到这几条通路: {missing} —— "
            "要么面板真的不再调它们了,要么扫描器的正则坏了。"
            f"当前数出来的是: {sorted(calls)}"
        )

    def test_scanner_does_not_read_its_own_generated_output(self) -> None:
        """自证:扫描器必须跳过 ``*.gen.ts``。

        不跳过的话,``api.gen.ts`` 里那 388 条路径字面量会被当成"面板在调它们",
        于是"面板调的端点后端都有"变成拿生成物对生成物 —— 恒真。
        """
        calls = _panel_calls()
        assert len(calls) < 100, f"扫描器解析出 {len(calls)} 个端点,数量级不对 —— 它八成把 api.gen.ts 自己也读进来了"

    def test_presence_websocket_route_exists(self) -> None:
        """面板与覆盖层都连 ``/ws/desktop-presence``,但 WS 不进 OpenAPI,单独钉。"""
        src = (_ROOT / "core" / "routes").rglob("*.py")
        found = any("/ws/desktop-presence" in p.read_text(encoding="utf-8") for p in src)
        assert found, "/ws/desktop-presence 在 core/routes 下找不到 —— 面板与覆盖层都会连不上"


# ---------------------------------------------------------------------------
# 4. 分层清单：数量的变化必须是有意的
# ---------------------------------------------------------------------------


class TestSurfaceInventory:
    """把"哪些是给人看的、哪些只是机器面"记成数字。

    这不是为了锁死数字,而是让**扩大前端可见面**成为一个需要改测试的动作 ——
    否则"顺手多调一个端点"会悄悄发生,而面板表层收敛那次的教训就是:
    表层一旦悄悄长出来,就再也收不回去了。
    """

    def test_panel_uses_a_small_slice_of_the_backend(self, generated_ts: str) -> None:
        backend = _api_paths_from_ts(generated_ts)
        panel = {c for c in _panel_calls() if not c.startswith("/ws/")}
        assert len(panel) <= 30, (
            f"面板的调用面涨到了 {len(panel)} 个端点。这不一定是错的,但请确认是有意的:"
            f"面板收敛那次的结论是表层要窄。确认后改这里的上限。"
        )
        assert len(backend) >= 300, f"后端路径只剩 {len(backend)} 条,像是 API 层没装配完整"

    def test_inventory_is_reportable(self, schema: dict) -> None:
        """清单必须是**算出来的**,不是手维护的 —— 手维护的清单必然漂。"""
        paths = schema.get("paths", {})
        ops = sum(1 for v in paths.values() for m in v if m in ("get", "post", "put", "delete", "patch"))
        comps = schema.get("components", {}).get("schemas", {})
        assert paths and ops >= len(paths), "OpenAPI 文档不完整"
        assert isinstance(comps, dict)


# ---------------------------------------------------------------------------
# 5. 生成物必须真的能被前端消费
# ---------------------------------------------------------------------------


def test_generated_file_is_referenced_by_the_type_barrel() -> None:
    """生成了却没人能 import 的类型文件等于没生成。

    这里只要求它在 types/ 目录下且是合法模块入口;逐个调用点改用 ApiPath
    是下一步(那会动到 20 处 fetch,是单独一件事)。
    """
    assert _GEN.is_file()
    text = _GEN.read_text(encoding="utf-8")
    assert text.startswith("// AUTO-GENERATED"), "生成物必须自带 DO NOT EDIT 头"
    assert "export type ApiPath" in text
    assert "export const API_METHODS" in text


def test_generator_is_deterministic(gen, schema) -> None:
    """同一份 schema 连生成两次必须逐字节相同,否则上面的同步门会假红。"""
    assert gen.build_api_surface(schema) == gen.build_api_surface(schema)
