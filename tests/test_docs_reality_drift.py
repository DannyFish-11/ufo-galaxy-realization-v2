"""文档与代码的漂移守卫。

## 为什么需要这道守卫

所有者让我从"体验者视角"走一遍从克隆到使用的流程。我没照 README 转述,
而是真跑了一遍 `python main.py` —— 于是发现 README 里**最基本的两件事**
都和代码对不上:

- **端口**:README 里 3 处写 `8765`,而另外 8 处写 `9000`,实际跑起来是 `9000`。
  同一份文档自相矛盾,比统一写错更坑:照着前半段敲 curl 全部连不上,
  照着后半段又能通,人会以为是自己环境的问题。
- **唤醒键**:README 写 `Ctrl+Space`,实际是 `Ctrl+Alt+Space`。
  新用户按下去没反应,第一反应是"这东西坏了"。

这类漂移的共同点是:**代码改了,文档没跟**。而它伤的恰恰是最没有容错能力
的那批人 —— 第一次接触这个项目、只能照文档操作的人。

所以把"文档里的关键事实必须与代码一致"变成测试,而不是靠人记得同步。

## 守什么、不守什么

只守**照着做会失败**的那几件事:端口、快捷键。

**不守**架构描述、功能介绍、设计理念那些 —— 那些本来就是概述,要求逐字
对应代码既不现实也没意义,只会逼人写空洞的文档。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
README = REPO / "README.md"


def _readme() -> str:
    return README.read_text(encoding="utf-8")


def _authoritative_port() -> int:
    """代码里的权威默认端口 —— 取自 ``launcher/bootstrap.py`` 的配置**定义处**。

    此前这里读的是 ``core/deployment_baseline.py``。那个来源本来就不对：
    该模块只是在自己的基线检查里**又赋了一遍**同样的值
    （``config.web_ui_port = 9000``），真正的默认值定义在
    ``launcher/bootstrap.py`` 的配置 dataclass 字段上（``web_ui_port: int = 9000``）。
    读"复述者"而不是"定义者"，那两处一旦分叉，守卫会跟着错误的一方走。

    该模块已作为空转的观测报告模块删除，这条守卫随之指回定义处 —— 顺带把这个
    间接层去掉了。
    """
    src = (REPO / "launcher" / "bootstrap.py").read_text(encoding="utf-8")
    m = re.search(r"^\s*web_ui_port\s*:\s*int\s*=\s*(\d+)", src, re.MULTILINE)
    assert m, "未能从 launcher/bootstrap.py 读出 web_ui_port 默认值,守卫自身失效"
    return int(m.group(1))


# ── 端口 ────────────────────────────────────────────────────────────────


def test_readme_uses_only_the_real_default_port():
    """README 里出现的 localhost 端口必须就是代码里的那个。

    原状是 3 处 8765 + 8 处 9000 —— 同一份文档自相矛盾。
    """
    port = _authoritative_port()
    found = set(re.findall(r"localhost:(\d{4})", _readme()))

    # 只校验"网关/面板"这一类端口;数据库那几个(5432/6379/6333/4222)另有出处。
    infra_ports = {"5432", "6379", "6333", "4222", "7687", "27017", "1143"}
    gateway_ports = found - infra_ports

    assert gateway_ports == {str(port)}, (
        f"README 里的网关端口 {sorted(gateway_ports)} 与代码默认值 {port} 不一致 —— " "照文档敲 curl 会连不上"
    )


def test_readme_has_no_stale_8765():
    """8765 是历史遗留端口,现在一处都不该有。"""
    assert "8765" not in _readme(), "README 仍残留旧端口 8765"


# ── 快捷键 ──────────────────────────────────────────────────────────────


def test_readme_wake_hotkey_matches_the_launcher_banner():
    """README 写的唤醒键必须与启动器横幅、托盘菜单一致。

    三处任何一处对不上,用户按下去就是没反应。
    """
    launcher = (REPO / "unified_launcher.py").read_text(encoding="utf-8")
    assert "Ctrl+Alt+Space" in launcher, "前提:启动器横幅用的是 Ctrl+Alt+Space"

    readme = _readme()
    assert "Ctrl+Alt+Space" in readme, "README 未写出真实的唤醒键"

    # 不能出现"裸" Ctrl+Space(即前面不带 Alt+ 的那种)。
    bare = re.findall(r"(?<!Alt\+)Ctrl\+Space", readme)
    assert not bare, f"README 仍写着 {bare} —— 实际是 Ctrl+Alt+Space,按了没反应"


def test_readme_documents_the_hide_hotkey_too():
    """唤醒键写了、隐藏键没写,用户会不知道怎么收起覆盖层。"""
    assert "Ctrl+Alt+H" in _readme()


# ── 反向:守卫本身不能失效 ──────────────────────────────────────────────


def test_guard_reads_a_plausible_port():
    """如果哪天 deployment_baseline 改了写法导致读不出端口,上面的用例会
    静默变成"永远通过"。这条把守卫自身钉住。"""
    port = _authoritative_port()
    assert 1024 <= port <= 65535
