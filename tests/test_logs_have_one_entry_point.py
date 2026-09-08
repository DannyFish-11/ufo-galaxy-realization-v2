"""日志:一处登记,一个入口,一种措辞。

改之前是什么样
--------------
仓库里十几处写着"详情见 XXX 日志",而且各说各的:有的说 ``logs/docker.log``、
有的说"服务端日志"、有的只说"详情见日志"。三个毛病:

1. 同一件事在启动器里叫一个名字、在节点里叫另一个,换个地方看到就对不上;
2. "详情见服务端日志"—— 在哪?一个不看代码的人没法从这句话走到那个文件;
3. 就算知道路径,也得自己开文件管理器翻 —— **没有入口**。

现在:登记在 :mod:`core.log_locations`,右下角托盘按那张表出「日志」菜单,
所有措辞从 :func:`log_hint` 出 —— 一句话里既有托盘路径、也有文件路径,
所以托盘起不来时那句话照样是真的。
"""

from __future__ import annotations

import re
import sys
import types
from pathlib import Path

import pytest

from core.log_locations import (
    LOG_LOCATIONS,
    TRAY_ROUTE,
    existing_logs,
    get_log,
    log_hint,
    logs_root,
)


class TestTheRegistry:
    def test_every_entry_is_complete(self):
        for entry in LOG_LOCATIONS:
            assert entry.name and entry.label and entry.label_en and entry.relpath
            assert entry.purpose, f"{entry.name} 没说什么时候该来看它"

    def test_purposes_say_when_not_what(self):
        """ "这是后端日志"对着屏幕找问题的人没用;"对话没反应先看这个"才有用。
        所以每条都得像是在描述一个**症状**。"""
        for entry in LOG_LOCATIONS:
            assert len(entry.purpose) > 8, f"{entry.name} 的说明太短,像是在说它是什么而不是何时看"

    def test_names_are_unique(self):
        names = [e.name for e in LOG_LOCATIONS]
        assert len(names) == len(set(names))

    def test_paths_are_unique(self):
        paths = [e.relpath for e in LOG_LOCATIONS]
        assert len(paths) == len(set(paths))

    def test_directories_are_marked(self):
        for entry in LOG_LOCATIONS:
            assert entry.is_dir == entry.relpath.endswith("/")

    def test_an_unregistered_name_is_not_invented(self):
        """没登记过就不拼一个路径出来。"""
        assert get_log("nope") is None

    def test_the_log_root_is_overridable(self, monkeypatch, tmp_path):
        """打包/便携版会把日志放到别处。"""
        monkeypatch.setenv("GALAXY_LOG_DIR", str(tmp_path))
        assert logs_root() == tmp_path

    def test_existing_only_lists_what_is_there(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GALAXY_LOG_DIR", str(tmp_path))
        assert existing_logs() == []
        (tmp_path / "lumiv.log").write_text("x", encoding="utf-8")
        assert [e.name for e in existing_logs()] == ["backend"]


class TestTheWording:
    def test_the_hint_names_both_the_tray_and_the_file(self):
        """只给托盘的话,托盘起不来时这句话就是假的;
        只给路径的话,等于让人自己去翻文件夹 —— 那正是这次要改掉的。"""
        hint = log_hint("docker")
        assert TRAY_ROUTE in hint
        assert "logs/docker.log" in hint

    def test_an_unknown_name_still_gives_an_honest_hint(self):
        hint = log_hint("nope")
        assert TRAY_ROUTE in hint
        assert ".log" not in hint, "没登记过却拼了个路径出来"

    @pytest.mark.parametrize("name", [e.name for e in LOG_LOCATIONS])
    def test_every_registered_log_has_a_hint(self, name):
        assert log_hint(name).strip()

    def test_the_route_is_defined_once(self):
        """改一处措辞,全仓一起变。"""
        import core.log_locations as m

        assert TRAY_ROUTE in log_hint("backend")
        assert m.TRAY_ROUTE == TRAY_ROUTE


class TestNobodyHardcodesLogPathsAnymore:
    """这次要守住的:别再有人手写"详情见 logs/xxx.log"。"""

    FILES = [
        "launcher/services.py",
        "launcher/compose_failures.py",
        "core/node_lifecycle.py",
        "core/routes/c_stage.py",
        "nodes/Node_45_DesktopAuto/main.py",
    ]

    @staticmethod
    def _live_strings(path: str):
        """源码里**真的会出现在输出上**的字符串字面量。

        不能只按行扫:注释和文档串里出现 "详情见 logs/xxx.log" 往往是在**说明**
        这段历史(比如"以前只会说一句…"),那是记录,不是缺陷。
        按行扫会把这类说明判成违规 —— 这个坑我在别的测试里已经踩过两次,
        所以这里用 AST 精确地把文档串排掉。
        """
        import ast

        tree = ast.parse(open(path, encoding="utf-8").read())
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                doc = ast.get_docstring(node, clean=False)
                if doc is not None:
                    docstrings.add(doc)
        return [
            n.value
            for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value not in docstrings
        ]

    @pytest.mark.parametrize("path", FILES)
    def test_no_handwritten_log_pointer(self, path):
        offenders = [
            text
            for text in self._live_strings(path)
            if re.search(r"(详情见|详见|进度见)\s*(logs/|服务端日志|节点日志)", text)
        ]
        assert not offenders, f"{path} 还在手写日志指向: {offenders}"

    @pytest.mark.parametrize("path", FILES)
    def test_it_goes_through_the_one_authority(self, path):
        src = open(path, encoding="utf-8").read()
        assert "log_hint" in src, f"{path} 没走统一措辞"


class TestTheTrayIsTheEntryPoint:
    """托盘那半边。这台机器没有 X11,真 pystray 一 import 就炸,所以用假的跑。"""

    @staticmethod
    def _tray():
        fake = types.ModuleType("pystray")

        class MenuItem:
            def __init__(self, text, action=None, default=False, visible=True):
                self.text, self.action = text, action
                self.default, self.visible = default, visible

        class Menu:
            SEPARATOR = "---"

            def __init__(self, *items):
                self.items = items

        fake.MenuItem, fake.Menu, fake.Icon = MenuItem, Menu, type("Icon", (), {})
        sys.modules.setdefault("pystray", fake)
        pil = sys.modules.setdefault("PIL", types.ModuleType("PIL"))
        for sub in ("Image", "ImageDraw", "ImageFilter", "ImageFont"):
            mod = sys.modules.setdefault(f"PIL.{sub}", types.ModuleType(f"PIL.{sub}"))
            setattr(pil, sub, mod)

        import windows_service.tray_icon as t

        t.pystray = fake
        t._HAVE_TRAY = True
        tray = t.GalaxyTray.__new__(t.GalaxyTray)
        tray._icon = None
        opened = []
        tray._open_in_os = lambda p: (opened.append(Path(p)), True)[1]
        tray._show_notification = lambda a, b: opened.append(("通知", a))
        return t, tray, opened

    def test_the_menu_lists_the_logs_that_exist(self):
        _t, tray, _ = self._tray()
        labels = [i.text for i in tray._build_logs_menu() if not isinstance(i, str)]
        for entry in existing_logs():
            assert any(entry.label in label for label in labels), f"{entry.label} 不在托盘菜单里"

    def test_it_does_not_list_logs_that_are_not_there(self, monkeypatch, tmp_path):
        """列一个点开是空的条目比不列更让人困惑 ——
        人会以为"日志是空的",而实际是这条链路压根没跑过。"""
        monkeypatch.setenv("GALAXY_LOG_DIR", str(tmp_path))
        _t, tray, _ = self._tray()
        labels = [i.text for i in tray._build_logs_menu() if not isinstance(i, str)]
        assert len(labels) == 1  # 只剩「打开日志文件夹」
        assert "文件夹" in labels[0]

    def test_there_is_always_a_way_to_the_folder(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GALAXY_LOG_DIR", str(tmp_path))
        _t, tray, _ = self._tray()
        labels = [i.text for i in tray._build_logs_menu() if not isinstance(i, str)]
        assert any("文件夹" in x or "folder" in x.lower() for x in labels)

    def test_clicking_an_item_opens_that_log(self):
        _t, tray, opened = self._tray()
        items = [i for i in tray._build_logs_menu() if not isinstance(i, str)]
        items[0].action(None, None)
        assert opened and opened[-1].name.endswith(".log")

    def test_each_item_points_at_its_own_file(self):
        """循环里建的回调如果不绑变量,所有项都会指向最后一条 ——
        这是这类菜单最经典的 bug。"""
        _t, tray, opened = self._tray()
        items = [i for i in tray._build_logs_menu() if not isinstance(i, str)][:-1]
        for item in items:
            item.action(None, None)
        assert len(set(map(str, opened))) == len(opened)

    def test_a_log_that_vanished_says_so_instead_of_opening_nothing(self, monkeypatch, tmp_path):
        """从建菜单到点它之间文件可能已经被清掉了。"""
        monkeypatch.setenv("GALAXY_LOG_DIR", str(tmp_path))
        target = tmp_path / "lumiv.log"
        target.write_text("x", encoding="utf-8")
        _t, tray, opened = self._tray()
        items = [i for i in tray._build_logs_menu() if not isinstance(i, str)]
        target.unlink()
        items[0].action(None, None)
        assert opened and opened[-1][0] == "通知"

    def test_the_menu_is_rebuilt_each_time(self):
        """日志是跑着跑着才出现的。菜单建一次就固定的话,
        启动时还没有的那些永远不会出现在里面。"""
        import inspect

        t, _tray, _ = self._tray()
        src = inspect.getsource(t.GalaxyTray._build_menu)
        assert "lambda" in src, "日志子菜单不是延迟构建的"
