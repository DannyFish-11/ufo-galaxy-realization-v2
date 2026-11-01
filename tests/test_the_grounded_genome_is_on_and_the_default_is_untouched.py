"""有据回答的 Genome(``config/genomes/grounded/``)出厂生效;默认 Genome 一个字节都没动(G9)。

docs/GROUNDED_AGENT_DESIGN.md 第五期。几条规矩写在 Genome 的 ``instructions.grounding`` 一格里,
接在三处提示词后面 —— OpenClawd 主循环、内核的对话路(chat_only,以前是写死在代码里的一句)、Agent 模板。
人给的提示词(``GALAXY_SYSTEM_PROMPT``、显式参数)原样用,不往后接(G3:人压过 Genome)。
"""

from __future__ import annotations

import inspect
import json
import shutil
from pathlib import Path

import pytest

import core.genome as gm

REPO = Path(__file__).resolve().parent.parent
GENOMES = REPO / "config" / "genomes"


@pytest.fixture(autouse=True)
def _no_env(monkeypatch):
    monkeypatch.delenv("GALAXY_GENOME", raising=False)
    monkeypatch.delenv("GALAXY_SYSTEM_PROMPT", raising=False)


def _grounding() -> str:
    return gm.load_genome("grounded", root=GENOMES).component("instructions")["grounding"].strip()


def test_the_repository_ships_with_the_grounded_genome_active():
    assert gm.active_genome_name(GENOMES) == "grounded"
    loaded = gm.load_genome("grounded", root=GENOMES)
    assert loaded.lineage == ("galaxy:grounded", "galaxy:default")


def test_the_default_genome_has_no_grounding_and_still_reproduces_the_old_prompt():
    default = gm.load_genome("default", root=GENOMES).component("instructions")
    assert "grounding" not in default and "chat_prompt" not in default
    assert default["system_prompt"] == gm.BUILTIN_SYSTEM_PROMPT


def test_the_grounded_genome_only_declares_the_rules():
    own = json.loads((GENOMES / "grounded" / "components" / "instructions.json").read_text(encoding="utf-8"))
    assert set(own) == {"grounding"}, "只声明多出来的那一格,其余继承 default(G1)"


def test_all_three_prompts_carry_the_same_rules():
    rules = _grounding()
    assert gm.system_prompt() == f"{gm.BUILTIN_SYSTEM_PROMPT}\n\n{rules}"
    assert gm.chat_prompt() == f"{gm.BUILTIN_CHAT_PROMPT}\n\n{rules}"
    builtin = "你是一个写代码的 Agent。"
    assert gm.agent_template_prompt("no_such_template", builtin) == f"{builtin}\n\n{rules}"


def test_the_rules_say_what_the_owner_decided():
    rules = _grounding()
    for must in ("工具结果", "没查到", "缺哪一样", "没法联网核实", "我猜", "更正"):
        assert must in rules, must


def test_a_human_prompt_is_used_verbatim(monkeypatch):
    monkeypatch.setenv("GALAXY_SYSTEM_PROMPT", "只用一句话回答。")
    assert gm.system_prompt() == "只用一句话回答。"
    assert gm.system_prompt(explicit="显式的") == "显式的"


def test_with_the_pointer_at_default_every_prompt_is_byte_identical(tmp_path, monkeypatch):
    root = tmp_path / "genomes"
    shutil.copytree(GENOMES / "default", root / "default")
    shutil.copytree(GENOMES / "grounded", root / "grounded")
    (root / gm.ACTIVE_POINTER).write_text('{"genome": "default"}', encoding="utf-8")
    monkeypatch.setattr(gm, "GENOMES_ROOT", root)
    assert gm.system_prompt() == gm.BUILTIN_SYSTEM_PROMPT
    assert gm.chat_prompt() == gm.BUILTIN_CHAT_PROMPT


def test_an_empty_grounding_is_rejected(tmp_path):
    root = tmp_path / "genomes"
    shutil.copytree(GENOMES / "default", root / "default")
    shutil.copytree(GENOMES / "grounded", root / "grounded")
    (root / "grounded" / "components" / "instructions.json").write_text('{"grounding": ""}', encoding="utf-8")
    with pytest.raises(gm.GenomeError, match="grounding"):
        gm.load_genome("grounded", root=root)


def test_the_kernel_chat_path_reads_its_prompt_from_the_genome():
    from core.agent import kernel

    src = inspect.getsource(kernel.AgentKernel._fallback_chat)
    assert "chat_prompt()" in src
    assert "自然流畅的 AI 对话伙伴" not in src, "提示词又被写回代码里了"


def test_harness_rsi_evolves_on_top_of_the_active_genome(tmp_path):
    """元层第一次建进化 Genome 时接在指针指着的那份上,不一声不响地把规矩丢掉;撤回时指针回到原来那份。"""
    import sys
    from contextlib import contextmanager

    from core.engineering_verification import VerificationObservation
    from core.meta.artifacts import create_artifact
    from core.meta.kernel import revert_patch, run_cycle
    from core.meta.operators.harness_rsi import HarnessRSIOperator, proposal_payload
    from core.meta.store import ArtifactStore

    live = tmp_path / "live"
    root = live / "config" / "genomes"
    shutil.copytree(GENOMES / "default", root / "default")
    shutil.copytree(GENOMES / "grounded", root / "grounded")
    shutil.copy(GENOMES / gm.ACTIVE_POINTER, root / gm.ACTIVE_POINTER)

    store = ArtifactStore(tmp_path / "store")
    payload = proposal_payload("instructions", ["system_prompt"], "你是 Galaxy。直接回答。", "更短")
    store.put(create_artifact("lesson", payload, operator="harness_rsi"))

    @contextmanager
    def sandbox():
        target = tmp_path / "sandbox"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(live, target)

        class _S:
            path = target

        yield _S()

    class _Verifier:
        def run(self, proposal, workspace):  # noqa: ARG002
            return [
                VerificationObservation(
                    command=(sys.executable, "-m", "pytest"),
                    requested="pytest",
                    recognized_verifier=True,
                    executed=True,
                    exit_code=0,
                    timed_out=False,
                    duration_s=0.01,
                    evidence_ref="context_archive:genome#1",
                )
            ]

    op = HarnessRSIOperator(root=live)
    report = run_cycle(
        op, op.collect(store), store=store, verifier=_Verifier(), mode="on", sandbox_factory=sandbox, live_root=live
    )
    [outcome] = report.outcomes
    assert outcome.outcome == "committed", outcome
    evolved = gm.load_genome("rsi", root=root)
    assert evolved.lineage == ("galaxy:rsi", "galaxy:grounded", "galaxy:default")
    assert evolved.component("instructions")["grounding"].strip() == _grounding()
    assert evolved.component("instructions")["system_prompt"] == "你是 Galaxy。直接回答。"
    assert evolved.parent_id == gm.load_genome("grounded", root=root).content_id
    assert revert_patch(outcome.patch_id, store=store, live_root=live) == ""
    assert gm.active_genome_name(root) == "grounded"
