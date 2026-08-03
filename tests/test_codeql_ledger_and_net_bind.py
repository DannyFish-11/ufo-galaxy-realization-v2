"""tests/test_codeql_ledger_and_net_bind.py — CodeQL 处置台账与发现绑定地址。

两件事放在一份文件里,因为它们是同一轮处置的两半:
* ``core/net_bind`` —— 对那几条 ``py/bind-socket-all-network-interfaces``
  **真改了代码**的部分(把写死的 0.0.0.0 变成显式可配的决定);
* ``config/codeql_findings_ledger.json`` + ``scripts/check_codeql_ledger.py``
  —— 对**改不动**的那些(节点的本职就是抓任意 URL、多播必须绑通配地址、
  测试里那处 bind 就是被测行为本身)记下结论,并让**新增**告警无处藏身。

台账这类东西最典型的死法是"写完就没人对过账"。所以下面的用例不只检查台账的
形状,还直接驱动对账脚本跑一遍:新增能报出来、消失能提示、找不到 SARIF 判失败。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER = REPO_ROOT / "config" / "codeql_findings_ledger.json"
CHECKER = REPO_ROOT / "scripts" / "check_codeql_ledger.py"

_VALID_STATUS = {"fixed", "mitigated", "by-design", "false-positive", "vendored"}


def _ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


def _write_sarif(path: Path, pairs) -> Path:
    results = []
    for rule, loc in pairs:
        uri, line = loc.rsplit(":", 1)
        results.append(
            {
                "ruleId": rule,
                "locations": [
                    {"physicalLocation": {"artifactLocation": {"uri": uri}, "region": {"startLine": int(line)}}}
                ],
            }
        )
    path.write_text(json.dumps({"runs": [{"results": results}]}), encoding="utf-8")
    return path


def _all_pairs(ledger: dict):
    return [(e["rule"], loc) for e in ledger["findings"] for loc in e["locations"]]


def _run(*args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(CHECKER), *args], capture_output=True, text=True, cwd=str(REPO_ROOT))


class TestLedgerIsWellFormed:
    def test_every_entry_has_a_valid_status_and_a_real_reason(self):
        for entry in _ledger()["findings"]:
            assert entry["status"] in _VALID_STATUS, f"{entry['rule']} 的 status 不在约定取值里:{entry['status']}"
            assert entry["locations"], f"{entry['rule']} 没有位置,等于没记"
            # 理由要足够长到真的说明了点什么。"误报"两个字不构成处置结论 ——
            # 台账的全部价值就在于那句"为什么它不该被改"。
            assert len(entry["reason"]) > 60, f"{entry['rule']} 的理由太短,说不清为什么它不该被改"

    def test_declared_count_matches_the_locations(self):
        for entry in _ledger()["findings"]:
            assert entry["count"] == len(
                entry["locations"]
            ), f"{entry['rule']} 声称 {entry['count']} 条,实际列了 {len(entry['locations'])} 条"

    def test_total_matches(self):
        ledger = _ledger()
        assert ledger["total_recorded"] == len(_all_pairs(ledger))

    def test_no_entry_is_marked_fixed(self):
        """``fixed`` 是个过渡状态 —— 真修掉了就该从台账删除,而不是留一条"已修"。

        留着的话,下次对账会报"台账里有、SARIF 里没有",而那条提示本身就成了噪声。
        """
        stuck = [e["rule"] for e in _ledger()["findings"] if e["status"] == "fixed"]
        assert not stuck, f"这些条目标成了 fixed,应当直接从台账里删掉:{stuck}"

    def test_locations_look_like_file_colon_line(self):
        for rule, loc in _all_pairs(_ledger()):
            assert ":" in loc, f"{rule} 的位置不带行号:{loc}"
            uri, line = loc.rsplit(":", 1)
            assert line.isdigit(), f"{rule} 的位置行号不是数字:{loc}"
            assert not uri.startswith("/"), f"{rule} 的位置应当是仓库相对路径:{loc}"


class TestReconciliationActuallyBites:
    """对账脚本必须真的能分辨"存量"与"新增" —— 否则台账只是一份文档。"""

    def test_exact_match_passes(self, tmp_path):
        sarif = _write_sarif(tmp_path / "python.sarif", _all_pairs(_ledger()))
        proc = _run("--strict", str(sarif))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "没有台账之外" in proc.stdout

    def test_a_new_finding_is_reported(self, tmp_path):
        pairs = _all_pairs(_ledger()) + [("py/command-line-injection", "core/brand_new_hole.py:42")]
        sarif = _write_sarif(tmp_path / "python.sarif", pairs)
        proc = _run("--strict", str(sarif))
        assert proc.returncode == 1, "新增告警没有让 --strict 判失败 —— 那这道守卫等于不存在"
        assert "core/brand_new_hole.py:42" in proc.stdout

    def test_a_new_finding_in_an_already_recorded_file_is_still_reported(self, tmp_path):
        """同一个文件里多出一处,也必须报。

        这一条单独写出来,是因为"只比文件名"是实现这类对账时最容易走的捷径,
        而它恰好会让这种情形完全隐形 —— 一个已经被记账的文件成了盲区。
        """
        rule, existing = _all_pairs(_ledger())[0]
        uri = existing.rsplit(":", 1)[0]
        pairs = _all_pairs(_ledger()) + [(rule, f"{uri}:999999")]
        sarif = _write_sarif(tmp_path / "python.sarif", pairs)
        proc = _run("--strict", str(sarif))
        assert proc.returncode == 1
        assert "999999" in proc.stdout

    def test_pure_line_drift_is_not_treated_as_new(self, tmp_path):
        """行号漂移不该判红 —— 这一条是被真实情况逼出来的。

        第一版严格比 ``文件:行号``。结果在落地这套守卫的**同一个 PR 里**,两条记录
        的行号就漂了 —— 只因为我在 bind 上面加了两行注释。一份每次改动都要手工
        对行号的台账很快就没人维护,而那正是它要防的结局。

        现在按 ``(规则, 文件)`` 比条数:条数没变就只是漂移,提示改行号即可。
        """
        pairs = _all_pairs(_ledger())
        rule, loc = next((r, l) for r, l in pairs if "udp_adapter" in l)
        uri = loc.rsplit(":", 1)[0]
        moved = [(r, f"{uri}:99999" if (r, l) == (rule, loc) else l) for r, l in pairs]
        sarif = _write_sarif(tmp_path / "python.sarif", moved)
        proc = _run("--strict", str(sarif))
        assert proc.returncode == 0, "纯行号漂移被判成新增了 —— 那台账会被噪声淹掉:\n" + proc.stdout
        assert "位置漂移" in proc.stdout
        assert "99999" in proc.stdout

    def test_a_disappeared_finding_is_surfaced_but_not_fatal(self, tmp_path):
        pairs = [p for p in _all_pairs(_ledger()) if p[0] != "py/incomplete-url-substring-sanitization"]
        sarif = _write_sarif(tmp_path / "python.sarif", pairs)
        proc = _run("--strict", str(sarif))
        assert proc.returncode == 0, "已修掉的告警不该判红 —— 修好了反而红,会逼人不去修"
        assert "已经不见了" in proc.stdout

    def test_missing_sarif_fails_instead_of_passing(self, tmp_path):
        proc = _run("--strict", str(tmp_path / "nope.sarif"))
        assert proc.returncode == 2, "找不到 SARIF 却没判失败 —— '找不到就当通过'的守卫等于没有守卫"


class TestDiscoveryBindHost:
    def test_default_is_wildcard(self, monkeypatch):
        """默认必须仍是 0.0.0.0。

        换个"更安全"的默认值会让绝大多数用户升级后设备发现悄悄失效 ——
        广播/多播收不到,而且不会有任何报错。为安全指标弄坏功能比不改更糟。
        """
        from core.net_bind import discovery_bind_host

        monkeypatch.delenv("GALAXY_DISCOVERY_BIND_HOST", raising=False)
        assert discovery_bind_host() == "0.0.0.0"

    def test_env_override_is_honoured(self, monkeypatch):
        from core.net_bind import discovery_bind_host

        monkeypatch.setenv("GALAXY_DISCOVERY_BIND_HOST", "192.168.1.50")
        assert discovery_bind_host() == "192.168.1.50"

    @pytest.mark.parametrize("value", ["", "   ", "\t"])
    def test_blank_values_fall_back_to_default(self, value, monkeypatch):
        """环境变量里一个手滑的空格不该把发现绑到一个不存在的地址上。"""
        from core.net_bind import discovery_bind_host

        monkeypatch.setenv("GALAXY_DISCOVERY_BIND_HOST", value)
        assert discovery_bind_host() == "0.0.0.0"

    def test_value_is_stripped(self, monkeypatch):
        from core.net_bind import discovery_bind_host

        monkeypatch.setenv("GALAXY_DISCOVERY_BIND_HOST", "  10.0.0.7  ")
        assert discovery_bind_host() == "10.0.0.7"


class TestBindSitesGoThroughTheHelper:
    """两处单播/广播绑定必须走 helper;两处**多播**绑定必须**不**走。

    后半句同样重要:多播接收要绑通配地址才收得到组播,让同一个开关也管住它,
    会出现"为了收窄单播而静默弄坏多播"的情形。这条用例把那个刻意的不一致
    钉下来,免得后来有人"顺手统一一下"。
    """

    def test_unicast_sites_use_the_helper(self):
        for rel in ("core/adapters/udp_adapter.py", "galaxy_gateway/p2p_connector.py"):
            text = (REPO_ROOT / rel).read_text(encoding="utf-8")
            assert "discovery_bind_host()" in text, f"{rel} 没走 core.net_bind —— 绑定地址又变回写死的了"

    def test_multicast_sites_deliberately_do_not(self):
        rel = "nodes/Node_71_MultiDeviceCoordination/core/device_discovery.py"
        text = (REPO_ROOT / rel).read_text(encoding="utf-8")
        assert "IP_ADD_MEMBERSHIP" in text, "这个文件不再做多播了,那本用例的前提需要重新确认"
        assert "discovery_bind_host" not in text, (
            "多播接收被接上了 GALAXY_DISCOVERY_BIND_HOST —— 一旦有人设了这个变量,"
            "组播就会静默收不到。理由见 config/codeql_findings_ledger.json 里那条。"
        )
