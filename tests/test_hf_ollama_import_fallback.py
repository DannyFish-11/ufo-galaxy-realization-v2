"""tests/test_hf_ollama_import_fallback.py
============================================
用户实测反馈:``ollama pull gemma4:e2b`` 等在 "pulling manifest" 就失败——
这些 tag 不在用户能连到的 Ollama 库里。用户要求:Ollama 没有的模型，默认
直接从 Hugging Face 下载相关模型。

设计:不重新搭一个推理服务器(风险高),而是把从 HF 下载来的 GGUF 权重通过
``ollama create`` 导入成本地自定义 Ollama 模型，复用 Ollama 现成的 serving
路径。由于本模块运行环境无法直接联网核实候选 HF repo 是否真实存在，机制
设计为"运行时逐个候选核实、命中即用、全部落空才失败"——这些测试用依赖注入
(不碰真实网络/ollama 二进制)验证的正是这套"核实→跳过→兜底"机制本身的
正确性，而非某个具体候选名字是否真实存在。
"""

from __future__ import annotations

from unittest.mock import patch

from core.hf_ollama_import_fallback import (
    HF_GGUF_CANDIDATES,
    download_and_import_to_ollama,
    find_gguf_file,
)


class TestFindGgufFile:
    def test_returns_none_when_repo_has_no_gguf(self):
        result = find_gguf_file(
            "some/repo",
            list_repo_files=lambda repo_id: ["config.json", "model.safetensors"],
        )
        assert result is None

    def test_returns_none_when_repo_lookup_raises(self):
        def _boom(repo_id):
            raise Exception("404 repo not found")

        result = find_gguf_file("nonexistent/repo", list_repo_files=_boom)
        assert result is None

    def test_prefers_matching_quantization(self):
        result = find_gguf_file(
            "some/repo",
            prefer_quant="q4",
            list_repo_files=lambda repo_id: [
                "model-q8_0.gguf",
                "model-q4_k_m.gguf",
                "model-f16.gguf",
            ],
            get_file_sizes=lambda repo_id, files: {},
        )
        assert result == "model-q4_k_m.gguf"

    def test_falls_back_to_any_gguf_when_no_quant_match(self):
        result = find_gguf_file(
            "some/repo",
            prefer_quant="q4",
            list_repo_files=lambda repo_id: ["model-f16.gguf"],
            get_file_sizes=lambda repo_id, files: {},
        )
        assert result == "model-f16.gguf"

    def test_skips_files_over_size_budget(self):
        huge = 20 * 1024 * 1024 * 1024  # 20GB
        small = 2 * 1024 * 1024 * 1024  # 2GB
        result = find_gguf_file(
            "some/repo",
            size_budget_mb=6000,
            list_repo_files=lambda repo_id: ["huge-q4.gguf", "small-q4.gguf"],
            get_file_sizes=lambda repo_id, files: {"huge-q4.gguf": huge, "small-q4.gguf": small},
        )
        assert result == "small-q4.gguf"


class TestDownloadAndImportToOllama:
    def test_returns_none_when_ollama_not_installed(self):
        with patch("shutil.which", return_value=None):
            result = download_and_import_to_ollama("gemma4:e2b")
        assert result is None

    def test_tries_next_candidate_when_first_has_no_gguf(self):
        """核心机制:第一个候选没有 .gguf(猜错了/repo 不存在)，自动换下一个。"""
        calls = []

        def _find_gguf(repo_id, **kwargs):
            calls.append(repo_id)
            # 第一个候选查无 .gguf；第二个候选命中。
            return None if repo_id == "candidate-a" else "model-q4.gguf"

        with patch("shutil.which", return_value="/usr/bin/ollama"):
            result = download_and_import_to_ollama(
                "gemma4:e2b",
                candidates=["candidate-a", "candidate-b"],
                find_gguf_file_fn=_find_gguf,
                hf_hub_download_fn=lambda repo_id, filename, local_dir: "/fake/path/model.gguf",
                ollama_create_fn=lambda name, path: True,
            )

        assert calls == ["candidate-a", "candidate-b"], "必须先试第一个候选,查无结果才换下一个"
        assert result is not None
        assert result.startswith("galaxy-")

    def test_returns_none_when_all_candidates_fail(self):
        with patch("shutil.which", return_value="/usr/bin/ollama"):
            result = download_and_import_to_ollama(
                "gemma4:e2b",
                candidates=["candidate-a", "candidate-b"],
                find_gguf_file_fn=lambda repo_id, **kw: None,
            )
        assert result is None

    def test_moves_to_next_candidate_when_ollama_create_fails(self):
        with patch("shutil.which", return_value="/usr/bin/ollama"):
            result = download_and_import_to_ollama(
                "gemma4:e2b",
                candidates=["candidate-a", "candidate-b"],
                find_gguf_file_fn=lambda repo_id, **kw: "model-q4.gguf",
                hf_hub_download_fn=lambda repo_id, filename, local_dir: "/fake/model.gguf",
                ollama_create_fn=lambda name, path: (name.endswith("hf") and path == "/fake/model.gguf" and False),
            )
        # ollama_create_fn 总是返回 False → 两个候选都失败 → None
        assert result is None

    def test_success_returns_local_model_name(self):
        with patch("shutil.which", return_value="/usr/bin/ollama"):
            result = download_and_import_to_ollama(
                "gemma4:e2b",
                candidates=["some/repo"],
                find_gguf_file_fn=lambda repo_id, **kw: "model-q4.gguf",
                hf_hub_download_fn=lambda repo_id, filename, local_dir: "/fake/model.gguf",
                ollama_create_fn=lambda name, path: True,
            )
        assert result == "galaxy-gemma4-e2b-hf"

    def test_exception_in_one_candidate_does_not_abort_remaining(self):
        """单个候选抛异常不能中断整个流程——必须继续试下一个。"""

        def _find_gguf(repo_id, **kw):
            if repo_id == "flaky-candidate":
                raise RuntimeError("network blip")
            return "model-q4.gguf"

        with patch("shutil.which", return_value="/usr/bin/ollama"):
            result = download_and_import_to_ollama(
                "gemma4:e2b",
                candidates=["flaky-candidate", "good-candidate"],
                find_gguf_file_fn=_find_gguf,
                hf_hub_download_fn=lambda repo_id, filename, local_dir: "/fake/model.gguf",
                ollama_create_fn=lambda name, path: True,
            )
        assert result is not None


def test_all_choice_order_tags_have_candidates():
    """本地主脑候选（现派生自 model_catalog）每一档都要有 HF 回退候选。

    _CHOICE_ORDER 常量已改为函数 _choice_order()（统一到 model_catalog 后）。
    """
    from core.model_selection import _choice_order

    for tag in _choice_order():
        assert tag in HF_GGUF_CANDIDATES, f"{tag} 缺少 HF 回退候选列表"
        assert len(HF_GGUF_CANDIDATES[tag]) >= 2, f"{tag} 候选太少,建议至少两个兜底"


def test_size_budget_follows_the_model_weight_not_a_fixed_ceiling():
    """大权重型号不该被固定的 6 GB 预算按住。

    注意失效模式**不是**下载失败 —— 见下一条测试的实测。
    """
    from core.hf_ollama_import_fallback import DEFAULT_SIZE_BUDGET_MB, _size_budget_for

    assert _size_budget_for("gemma4:e2b") == DEFAULT_SIZE_BUDGET_MB, "小模型的预算不该被抬高"
    big = _size_budget_for("qwen3.6:35b-a3b")
    assert big > DEFAULT_SIZE_BUDGET_MB
    assert big >= 18000, f"18 GB 权重却只给了 {big} MB 预算 —— 每个候选都会被判超预算"
    # 目录外的型号维持原默认，不因为查不到就放开预算。
    assert _size_budget_for("nobody/knows-this") == DEFAULT_SIZE_BUDGET_MB


def test_download_derives_the_budget_from_the_tag(monkeypatch):
    """把预算真的传下去 —— 只在 _size_budget_for 里算对没用。"""
    import core.hf_ollama_import_fallback as m

    seen = {}
    monkeypatch.setattr(m.shutil, "which", lambda _n: "/usr/bin/ollama")

    def _probe(repo_id, *, size_budget_mb=0, **_kw):
        seen["budget"] = size_budget_mb
        return None  # 不继续走下载

    m.download_and_import_to_ollama("qwen3.6:35b-a3b", find_gguf_file_fn=_probe)
    assert seen["budget"] >= 18000, f"传下去的预算是 {seen.get('budget')} —— 没跟着型号走"


def test_a_fixed_budget_silently_drops_to_the_worst_quantisation():
    """固定预算的真实后果：**静默降到最小的量化档**，不是下载失败。

    这条是照着真实调用跑出来的结果写的。构造一个真实形状的 MoE GGUF repo
    (同一模型三个量化档)，两种预算下 find_gguf_file 的选择：

    .. code-block:: text

        预算 6000  -> Q2_K.gguf     ← 全部超预算，走"选最小的"分支
        预算 19800 -> Q4_K_M.gguf   ← Q4 在预算内，prefer_quant 生效

    "全部超预算"那条分支**绕过了 prefer_quant**。于是下载成功、导入成功、
    什么都不报错，用户拿到的却是一个被过度量化、质量明显更差的模型 ——
    比直接失败难查得多。
    """
    from core.hf_ollama_import_fallback import _size_budget_for, find_gguf_file

    gb = 1024**3
    files = ["Qwen3-30B-A3B-Q2_K.gguf", "Qwen3-30B-A3B-Q4_K_M.gguf", "Qwen3-30B-A3B-Q8_0.gguf"]
    sizes = {files[0]: 11 * gb, files[1]: 18 * gb, files[2]: 32 * gb}

    def pick(budget):
        return find_gguf_file(
            "x/y",
            size_budget_mb=budget,
            list_repo_files=lambda _r: files,
            get_file_sizes=lambda _r, _f: sizes,
        )

    assert pick(6000) == "Qwen3-30B-A3B-Q2_K.gguf", "固定预算下的旧行为变了，这条测试的前提没了"
    assert pick(_size_budget_for("qwen3.6:35b-a3b")) == "Qwen3-30B-A3B-Q4_K_M.gguf"
