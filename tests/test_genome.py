"""tests/test_genome.py — 提示词资产化与 Genome 合并语义（R5 · 保证 G1 / G2 / G3 / G9 / G11）。

这个文件同时是 Harness-RSI 补丁的**验证器**：补丁改的是 ``config/genomes/`` 下的
``genome.json`` / ``active.json`` / ``instructions.json``，验证阶梯按文件名把本文件选进来，
其中「生效中的 Genome 满足组件契约」那一条就是补丁能不能拿到 trusted 的判据。
"""

from __future__ import annotations

import json
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

from core import genome as gm
from core.engineering_verification import VerificationObservation

REPO_ROOT = Path(__file__).resolve().parents[1]
GENOMES = REPO_ROOT / "config" / "genomes"

#: 引入 Genome 之前 core/openclawd.py 里硬编码的系统提示词 —— **独立复刻**，不从任何源码里取
#: （沿用 electron/renderer/presence_motion.test.js 的先例：旧实现单独抄一份，逐字节比对）。
HISTORICAL_SYSTEM_PROMPT = (
    "你是 Galaxy 智能助手 (OpenClawd)，一个桌面级超级 AI 智能体。\n"
    "你可以帮助用户进行对话、任务管理、设备控制、代码执行等操作。\n"
    "当你需要执行操作时，请使用提供的工具。\n"
    "如果没有合适的工具，直接用文字回答。\n"
    "表达原则：直接、简洁，不复述问题、不加客套铺垫；"
    "要调用工具就直接调用，不要先输出长段解释。"
)

HISTORICAL_PLANNER_PROMPT = (
    "你是一个规划 Agent。根据目标制定详细的执行计划。\n"
    '返回 JSON: {"plan": {"steps": [...], "resources": [...], "risks": [...]}}'
)


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    monkeypatch.delenv("GALAXY_GENOME", raising=False)
    monkeypatch.delenv("GALAXY_SYSTEM_PROMPT", raising=False)
    gm._cache.clear()
    yield
    gm._cache.clear()


def _write_genome(root: Path, name: str, components: dict, **manifest) -> None:
    d = root / name
    (d / "components").mkdir(parents=True, exist_ok=True)
    for cid, content in components.items():
        (d / "components" / f"{cid}.json").write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    body = {
        "genome_schema_version": "1",
        "genome_id": f"galaxy:{name}",
        "parent_id": None,
        "version": 1,
        "base": None,
        "components": [{"id": c, "source": f"./components/{c}.json"} for c in components],
    }
    body.update(manifest)
    (d / "genome.json").write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def genomes(tmp_path, monkeypatch):
    root = tmp_path / "genomes"
    shutil.copytree(GENOMES / "default", root / "default")
    monkeypatch.setattr(gm, "GENOMES_ROOT", root)
    return root


# ---------------------------------------------------------------------------
# G9 · 默认路径逐位一致
# ---------------------------------------------------------------------------


def test_default_genome_reproduces_the_hardcoded_prompt_byte_for_byte():
    assert gm.system_prompt() == HISTORICAL_SYSTEM_PROMPT
    assert gm.BUILTIN_SYSTEM_PROMPT == HISTORICAL_SYSTEM_PROMPT
    assert gm.load_genome("default").component("instructions")["system_prompt"] == HISTORICAL_SYSTEM_PROMPT


def test_default_genome_reproduces_every_agent_template_prompt():
    from core.agent_factory import AGENT_TEMPLATES

    templates = gm.load_genome("default").component("instructions")["agent_templates"]
    assert set(templates) == set(AGENT_TEMPLATES)
    for name, config in AGENT_TEMPLATES.items():
        assert templates[name] == config.system_prompt, name
    assert templates["planner"] == HISTORICAL_PLANNER_PROMPT


def test_openclawd_reads_the_prompt_through_the_genome():
    source = (REPO_ROOT / "core" / "openclawd.py").read_text(encoding="utf-8")
    assert '{"role": "system", "content": _genome_system_prompt()}' in source
    assert "你是 Galaxy 智能助手 (OpenClawd)" not in source, "提示词又被写回代码里了"


def test_active_genome_satisfies_component_contracts():
    """Harness-RSI 补丁的判据：仓库里（或验证工作区里）生效的 Genome 必须合法、提示词非空。

    覆盖的文件：config/genomes/active.json、config/genomes/*/genome.json、components/instructions.json。
    """
    name = gm.active_genome_name(GENOMES)
    loaded = gm.load_genome(name, root=GENOMES)
    assert loaded.component("instructions")["system_prompt"].strip()
    assert gm.active_genome(root=GENOMES) is not None


# ---------------------------------------------------------------------------
# G1 · 继承式合并
# ---------------------------------------------------------------------------


def test_merge_semantics_absent_null_value():
    base = {"keep": 1, "drop": 2, "replace": 3, "obj": {"a": 1, "b": 2}, "arr": [1, 2]}
    override = {"drop": None, "replace": 30, "obj": {"b": None, "c": 3}, "arr": [9], "new": {"x": None, "y": 1}}
    assert gm.merge_overrides(base, override) == {
        "keep": 1,
        "replace": 30,
        "obj": {"a": 1, "c": 3},
        "arr": [9],
        "new": {"y": 1},
    }
    assert base["obj"] == {"a": 1, "b": 2}, "合并不得改动入参"
    assert gm.merge_overrides(base, None) is None


def test_a_genome_declaring_only_model_leaves_instructions_untouched(genomes):
    _write_genome(genomes, "only_model", {"model": {"routing_policy": "config/other.yaml"}}, base="default")
    child, parent = gm.load_genome("only_model", root=genomes), gm.load_genome("default", root=genomes)
    assert child.component("instructions") == parent.component("instructions")
    assert child.component("model")["routing_policy"] == "config/other.yaml"
    assert child.component("model")["writable"] is False, "没声明的字段是继承，不是清空"
    assert child.lineage == ("galaxy:only_model", "galaxy:default")


def test_null_hands_a_field_back_to_the_inherited_value(genomes):
    _write_genome(genomes, "a", {"instructions": {"system_prompt": "A 的提示词"}}, base="default")
    _write_genome(genomes, "b", {"instructions": {"system_prompt": None}}, base="a")
    assert gm.load_genome("a", root=genomes).component("instructions")["system_prompt"] == "A 的提示词"
    # b 把 system_prompt 删成 null → 合并后该键不存在 → 契约报缺失：删除必须是有意识的
    with pytest.raises(gm.GenomeError, match="必填字段缺失"):
        gm.load_genome("b", root=genomes)


# ---------------------------------------------------------------------------
# G2 · 空值不等于清除
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "instructions",
    [{"system_prompt": ""}, {"system_prompt": "   "}, {"agent_templates": {"planner": ""}}],
)
def test_empty_strings_are_rejected(genomes, instructions):
    _write_genome(genomes, "blank", {"instructions": instructions}, base="default")
    with pytest.raises(gm.GenomeError, match="G2"):
        gm.load_genome("blank", root=genomes)


def test_an_invalid_active_genome_falls_back_to_the_builtin(genomes, monkeypatch):
    _write_genome(genomes, "blank", {"instructions": {"system_prompt": ""}}, base="default")
    monkeypatch.setenv("GALAXY_GENOME", "blank")
    assert gm.active_genome() is None
    assert gm.system_prompt() == HISTORICAL_SYSTEM_PROMPT


@pytest.mark.parametrize("bad", ["../escape", "a/b", ".hidden", ""])
def test_genome_names_cannot_escape_the_directory(bad):
    with pytest.raises(gm.GenomeError):
        gm.genome_dir(bad)


def test_base_cycles_are_rejected(genomes):
    _write_genome(genomes, "x", {}, base="y")
    _write_genome(genomes, "y", {}, base="x")
    with pytest.raises(gm.GenomeError, match="成环"):
        gm.load_genome("x", root=genomes)


def test_component_sources_cannot_leave_the_genome(genomes):
    _write_genome(genomes, "evil", {})
    manifest = json.loads((genomes / "evil" / "genome.json").read_text(encoding="utf-8"))
    manifest["components"] = [{"id": "instructions", "source": "../default/components/instructions.json"}]
    (genomes / "evil" / "genome.json").write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(gm.GenomeError, match="目录之外"):
        gm.load_genome("evil", root=genomes)


# ---------------------------------------------------------------------------
# G3 · 人工压制优先
# ---------------------------------------------------------------------------


def test_explicit_beats_env_beats_genome(genomes, monkeypatch):
    _write_genome(genomes, "evolved", {"instructions": {"system_prompt": "元层改过的"}}, base="default")
    (genomes / gm.ACTIVE_POINTER).write_text('{"genome": "evolved"}', encoding="utf-8")
    assert gm.system_prompt() == "元层改过的"
    monkeypatch.setenv("GALAXY_SYSTEM_PROMPT", "人写的")
    assert gm.system_prompt() == "人写的"
    assert gm.system_prompt(explicit="调用方显式给的") == "调用方显式给的"


def test_env_genome_beats_the_meta_layer_pointer(genomes, monkeypatch):
    _write_genome(genomes, "evolved", {"instructions": {"system_prompt": "元层改过的"}}, base="default")
    (genomes / gm.ACTIVE_POINTER).write_text('{"genome": "evolved"}', encoding="utf-8")
    monkeypatch.setenv("GALAXY_GENOME", "default")
    assert gm.system_prompt() == HISTORICAL_SYSTEM_PROMPT


def test_agent_factory_template_reads_the_genome_and_explicit_override_wins(genomes):
    from core.agent_factory import AgentFactory

    _write_genome(genomes, "evolved", {"instructions": {"agent_templates": {"planner": "新规划提示"}}}, base="default")
    (genomes / gm.ACTIVE_POINTER).write_text('{"genome": "evolved"}', encoding="utf-8")
    factory = AgentFactory(None)
    assert factory.create_from_template("planner").config.system_prompt == "新规划提示"
    assert factory.create_from_template("coordinator").config.system_prompt.startswith("你是一个协调 Agent")
    overridden = factory.create_from_template("planner", overrides={"system_prompt": "手写的"})
    assert overridden.config.system_prompt == "手写的"


# ---------------------------------------------------------------------------
# Harness-RSI 算子：提案 → 验证 → 裁决 → 生效 → 回滚（G11）
# ---------------------------------------------------------------------------


def _obs(exit_code=0):
    return VerificationObservation(
        command=(sys.executable, "-m", "pytest"),
        requested="pytest",
        recognized_verifier=True,
        executed=True,
        exit_code=exit_code,
        timed_out=False,
        duration_s=0.01,
        evidence_ref="context_archive:genome#1",
    )


class _Verifier:
    def __init__(self, exit_code=0):
        self.exit_code = exit_code

    def run(self, proposal, workspace):
        return [_obs(self.exit_code)]


@pytest.fixture
def live(tmp_path):
    root = tmp_path / "live"
    shutil.copytree(GENOMES / "default", root / "config" / "genomes" / "default")
    return root


def _copy_sandbox(live: Path, tmp_path: Path):
    @contextmanager
    def factory():
        target = tmp_path / "sandbox"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(live, target)

        class _S:
            path = target

        yield _S()

    return factory


def _propose(store, component, path, value, rationale="更短的开场更好"):
    from core.meta.artifacts import create_artifact
    from core.meta.operators.harness_rsi import proposal_payload

    return store.put(
        create_artifact("lesson", proposal_payload(component, path, value, rationale), operator="harness_rsi")
    )


def _run(live, tmp_path, store, verifier=None, mode="on"):
    from core.meta.kernel import run_cycle
    from core.meta.operators.harness_rsi import HarnessRSIOperator

    op = HarnessRSIOperator(root=live)
    return run_cycle(
        op,
        op.collect(store),
        store=store,
        verifier=verifier or _Verifier(),
        mode=mode,
        sandbox_factory=_copy_sandbox(live, tmp_path),
        live_root=live,
    )


def test_operator_is_registered():
    from core.meta.operators import build_operator, registered_operators

    assert "harness_rsi" in registered_operators()
    op = build_operator("harness_rsi")
    assert (op.name, op.scope) == ("harness_rsi", "harness")


def test_trusted_patch_creates_an_evolved_genome_and_can_be_reverted(live, tmp_path):
    from core.meta.kernel import revert_patch
    from core.meta.store import ArtifactStore

    store = ArtifactStore(tmp_path / "store")
    lesson = _propose(store, "instructions", ["system_prompt"], "你是 Galaxy。直接回答。")
    report = _run(live, tmp_path, store)
    [outcome] = report.outcomes
    assert outcome.outcome == "committed", outcome

    root = live / "config" / "genomes"
    evolved = gm.load_genome("rsi", root=root)
    assert evolved.component("instructions")["system_prompt"] == "你是 Galaxy。直接回答。"
    assert (
        evolved.component("instructions")["agent_templates"]
        == gm.load_genome("default", root=root).component("instructions")["agent_templates"]
    ), "只声明被改的那一格（G1）"
    assert evolved.version == 1 and evolved.parent_id == gm.load_genome("default", root=root).content_id
    assert gm.active_genome_name(root) == "rsi"
    own_layer = json.loads((root / "rsi" / "components" / "instructions.json").read_text(encoding="utf-8"))
    assert set(own_layer) == {"system_prompt"}
    assert store.get(outcome.patch_id).lineage.parents == (lesson,)

    assert _run(live, tmp_path, store).outcomes == [], "提案被消费过就不再重复提"

    assert revert_patch(outcome.patch_id, store=store, live_root=live) == ""
    assert not (root / "rsi").exists() or not (root / "rsi" / "genome.json").exists()
    assert gm.active_genome_name(root) == "default"


def test_second_patch_bumps_version_and_chains_parent(live, tmp_path):
    from core.meta.store import ArtifactStore

    store = ArtifactStore(tmp_path / "store")
    _propose(store, "instructions", ["system_prompt"], "第一版")
    assert _run(live, tmp_path, store).outcomes[0].outcome == "committed"
    root = live / "config" / "genomes"
    first = gm.load_genome("rsi", root=root)
    _propose(store, "instructions", ["agent_templates", "planner"], "第二版规划")
    assert _run(live, tmp_path, store).outcomes[0].outcome == "committed"
    second = gm.load_genome("rsi", root=root)
    assert (second.version, second.parent_id) == (2, first.content_id)
    assert second.component("instructions")["system_prompt"] == "第一版"
    assert second.component("instructions")["agent_templates"]["planner"] == "第二版规划"


def test_failed_verification_leaves_the_live_tree_alone(live, tmp_path):
    from core.meta.store import ArtifactStore

    store = ArtifactStore(tmp_path / "store")
    _propose(store, "instructions", ["system_prompt"], "")  # G2：验证器应判红
    [outcome] = _run(live, tmp_path, store, verifier=_Verifier(exit_code=1)).outcomes
    assert outcome.outcome == "rolled_back"
    assert not (live / "config" / "genomes" / "rsi").exists()
    assert gm.active_genome_name(live / "config" / "genomes") == "default"


def test_shadow_mode_never_writes(live, tmp_path):
    from core.meta.store import ArtifactStore

    store = ArtifactStore(tmp_path / "store")
    _propose(store, "instructions", ["system_prompt"], "影子")
    [outcome] = _run(live, tmp_path, store, mode="shadow").outcomes
    assert outcome.outcome == "shadow"
    assert not (live / "config" / "genomes" / "rsi").exists()


def test_the_model_component_is_read_only(live, tmp_path):
    from core.meta.store import ArtifactStore

    store = ArtifactStore(tmp_path / "store")
    _propose(store, "model", ["routing_policy"], "config/other.yaml")
    [outcome] = _run(live, tmp_path, store).outcomes
    assert outcome.outcome == "rejected" and "只读" in outcome.reason
    assert not (live / "config" / "genomes" / "rsi").exists()


def test_sandbox_mirrors_live_writable_surfaces(tmp_path):
    """工作区取自 HEAD；此前生效、未进 git 的补丁必须被镜像进去，否则下一轮一律判过期。"""
    from core.meta.kernel import _mirror_writable_surfaces

    live, sandbox = tmp_path / "live", tmp_path / "sandbox"
    (live / "config" / "genomes" / "rsi").mkdir(parents=True)
    (live / "config" / "genomes" / "rsi" / "genome.json").write_text("{}", encoding="utf-8")
    (sandbox / "config" / "genomes" / "stale").mkdir(parents=True)
    (sandbox / "config" / "assessment_claims.json").write_text("{}", encoding="utf-8")
    _mirror_writable_surfaces(live, sandbox)
    assert (sandbox / "config" / "genomes" / "rsi" / "genome.json").is_file()
    assert not (sandbox / "config" / "genomes" / "stale").exists()
    assert not (sandbox / "config" / "assessment_claims.json").exists()


def test_meta_rsi_cli_propose_registers_a_lesson(tmp_path):
    import subprocess

    value = tmp_path / "prompt.txt"
    value.write_text("新提示词", encoding="utf-8")
    proc = subprocess.run(
        [
            sys.executable,
            "scripts/meta_rsi.py",
            "--store",
            str(tmp_path / "store"),
            "propose",
            "--component",
            "instructions",
            "--path",
            "system_prompt",
            "--value-file",
            str(value),
            "--rationale",
            "更短",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    from core.meta.store import ArtifactStore

    lesson = ArtifactStore(tmp_path / "store").get(proc.stdout.strip())
    assert lesson.payload["value"] == "新提示词" and lesson.payload["path"] == ["system_prompt"]
