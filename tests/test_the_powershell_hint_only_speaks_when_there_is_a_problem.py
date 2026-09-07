"""PowerShell 显示建议：位置对，但不该每次都念一遍。

它必须打在横幅**之前** —— 讲的就是"列宽/代码页不对，横幅会画烂"，画烂之后
再说没意义。但此前它是**无条件打四行**：用户已经 ``chcp 65001``、窗口也拉到
160 列，每次启动还是被教一遍。改成按探到的事实说话之后，这里钉住三件事：

1. 都正常 → 一个字都不打；
2. 哪一条不对 → 只打那一条；
3. 探不到（``None``）→ 当"不知道"，不许当成"有问题"也不许当成"没问题"。
"""

import core.ascii_art as art


def _windows_powershell(monkeypatch):
    monkeypatch.setattr(art.os, "name", "nt")
    monkeypatch.setenv("PSModulePath", "C:\\Windows\\System32\\WindowsPowerShell")


class TestItStaysQuietWhenNothingIsWrong:
    def test_not_windows_says_nothing(self, monkeypatch, capsys):
        monkeypatch.setattr(art.os, "name", "posix")
        art.print_powershell_hint()
        assert capsys.readouterr().out == ""

    def test_windows_but_not_powershell_says_nothing(self, monkeypatch, capsys):
        monkeypatch.setattr(art.os, "name", "nt")
        monkeypatch.delenv("PSModulePath", raising=False)
        monkeypatch.delenv("PSVersionTable", raising=False)
        art.print_powershell_hint()
        assert capsys.readouterr().out == ""

    def test_a_properly_configured_console_is_not_lectured(self, monkeypatch, capsys):
        _windows_powershell(monkeypatch)
        monkeypatch.setattr(art, "_console_code_page", lambda: 65001)
        monkeypatch.setattr(art, "_console_columns", lambda: 160)
        art.print_powershell_hint()
        assert capsys.readouterr().out == "", "已经配好的窗口不该每次启动都被教一遍"

    def test_unknown_is_not_treated_as_broken(self, monkeypatch, capsys):
        # 探测失败返回 None。"不知道"不是"有问题" —— 不许凭空报一条。
        _windows_powershell(monkeypatch)
        monkeypatch.setattr(art, "_console_code_page", lambda: None)
        monkeypatch.setattr(art, "_console_columns", lambda: None)
        art.print_powershell_hint()
        assert capsys.readouterr().out == ""


class TestItSaysExactlyWhatIsWrong:
    def test_only_the_code_page_line_when_only_the_code_page_is_wrong(self, monkeypatch, capsys):
        _windows_powershell(monkeypatch)
        monkeypatch.setattr(art, "_console_code_page", lambda: 936)
        monkeypatch.setattr(art, "_console_columns", lambda: 160)
        art.print_powershell_hint()
        out = capsys.readouterr().out
        assert "chcp 65001" in out and "936" in out
        assert "列宽" not in out, "列宽没问题就不该提列宽"

    def test_only_the_width_line_when_only_the_width_is_wrong(self, monkeypatch, capsys):
        _windows_powershell(monkeypatch)
        monkeypatch.setattr(art, "_console_code_page", lambda: 65001)
        monkeypatch.setattr(art, "_console_columns", lambda: 80)
        art.print_powershell_hint()
        out = capsys.readouterr().out
        assert "列宽" in out and "80" in out
        assert "chcp" not in out, "代码页没问题就不该提 chcp"

    def test_the_font_line_never_speaks_on_its_own(self, monkeypatch, capsys):
        # 字体探不到，所以它不许单独构成"开口"的理由；只在别的毛病已经探到时顺带。
        _windows_powershell(monkeypatch)
        monkeypatch.setattr(art, "_console_code_page", lambda: 65001)
        monkeypatch.setattr(art, "_console_columns", lambda: 160)
        art.print_powershell_hint()
        assert "Consolas" not in capsys.readouterr().out

        monkeypatch.setattr(art, "_console_columns", lambda: 80)
        art.print_powershell_hint()
        assert "Consolas" in capsys.readouterr().out


class TestTheProbesThemselvesNeverThrow:
    def test_code_page_probe_on_non_windows(self, monkeypatch):
        monkeypatch.setattr(art.os, "name", "posix")
        assert art._console_code_page() is None

    def test_columns_probe_returns_none_when_redirected(self, monkeypatch):
        # 输出被重定向（管道/日志）时列宽无意义，必须是"不知道"。
        monkeypatch.setattr(art.sys.stdout, "isatty", lambda: False, raising=False)
        assert art._console_columns() is None
