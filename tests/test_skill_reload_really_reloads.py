"""技能热重载真的重新读了技能；没有这个技能就说没有。

全面排查第 7 轮把写接口都打了一遍：``POST /api/v1/protocols/skills/r7-nope/reload``（根本没有这个技能）回
200 ``{"loaded": true, "validated": true}``。往下查：``core/mcp_skill_reload.reload_skill`` 探测
``unload_skill`` / ``reload_skill`` / ``load_skill`` 三个方法 —— ``SkillLoader`` 一个都没有（它的是
``load(path, skill_id)`` / ``unload``），``hasattr`` 守卫下整段空转，然后照样报「重载成功」。MCP 那一半早先修过，
技能这一半漏了。同一个文件里「全部重载」与加载状态读 ``list_skills()`` 每项的 ``skill_id``，而那里的键是
``id`` —— 一个技能也没重载过、加载状态里一个技能也没有。

MCP 那边重载一个没登记的名字回 500（「未注册」是调用方的事），一并改成 404。
"""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
HELLO = REPO_ROOT / "skills" / "examples" / "hello_skill"


class _Registry:
    async def refresh(self, force=False):
        return None


@pytest.fixture()
def loader(tmp_path, monkeypatch):
    """一个干净的 SkillLoader，里面装着 hello 技能的一份拷贝（能改它的文件）；不往全局能力总线里写。"""
    import core.agent.capability_registry as cr
    import core.mcp_skill_reload as msr
    from core.skill_loader import SkillLoader

    async def _no_refresh(self, skill_id, event):
        return None

    monkeypatch.setattr(SkillLoader, "_inject_skill_to_registry", lambda self, skill_id: None)
    monkeypatch.setattr(SkillLoader, "_refresh_capability_registry", _no_refresh)
    monkeypatch.setattr(cr, "get_capability_registry", lambda: _Registry())
    fresh = SkillLoader()
    monkeypatch.setattr(SkillLoader, "_instance", fresh)
    monkeypatch.setattr(msr, "_load_status", {})
    skill_dir = tmp_path / "hello_skill"
    shutil.copytree(HELLO, skill_dir, ignore=shutil.ignore_patterns("__pycache__"))
    assert asyncio.run(fresh.load(str(skill_dir)))["success"]
    fresh.dir = skill_dir
    return fresh


def _rewrite(skill_dir: Path, **changes) -> None:
    f = skill_dir / "skill.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    data.update(changes)
    f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_a_reload_reads_the_skill_again(loader):
    from core.mcp_skill_reload import reload_skill

    _rewrite(loader.dir, description="改过的说明")
    result = asyncio.run(reload_skill("hello"))
    assert result["loaded"] is True and result["validated"] is True, result
    assert loader.skills["hello"].description == "改过的说明", "说重载了，读到的还是旧的"


def test_a_skill_that_is_not_there_is_not_reported_as_reloaded(loader):
    from core.mcp_skill_reload import reload_skill

    result = asyncio.run(reload_skill("r7-nope"))
    assert result["loaded"] is False and result.get("not_found") is True


def test_a_broken_skill_file_keeps_the_old_one(loader):
    from core.mcp_skill_reload import reload_skill

    (loader.dir / "skill.json").write_text("{ not json", encoding="utf-8")
    result = asyncio.run(reload_skill("hello"))
    assert result["loaded"] is False and "重新加载失败" in result["error"]
    assert loader.skills["hello"].description == "一个简单的问候技能示例"


def test_reload_all_and_the_load_status_see_the_skills(loader):
    from core.mcp_skill_reload import get_load_status, reload_all

    assert "hello" in asyncio.run(reload_all())["skills"]
    assert "hello" in get_load_status()["skills"]


@pytest.fixture()
def api():
    from core.api_routes import create_api_routes

    app = FastAPI()
    app.include_router(create_api_routes())
    with TestClient(app) as c:
        yield c


@pytest.mark.parametrize("kind", ["skills", "mcp"])
def test_reloading_a_name_nobody_registered_is_a_404(api, auth_headers, kind):
    r = api.post(f"/api/v1/protocols/{kind}/r7-nope/reload", headers=auth_headers)
    assert r.status_code == 404, r.text
    assert r.json()["loaded"] is False
