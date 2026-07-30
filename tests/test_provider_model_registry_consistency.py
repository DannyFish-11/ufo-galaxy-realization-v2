"""provider 型号清单的自洽性,以及本轮新增的四个旗舰型号。

被修的一处既有缺陷
------------------
``PROVIDER_MODEL_MAP``(按任务类型选型号)里的值,必须是该 provider 在
``PROVIDER_REGISTRY["models"]`` 里**声明过**的型号 —— 否则路由器会选出一个这家从没
声明过的型号,一路带到真实请求里。

这条不变式此前被违反了一处:``qwen.fast_response = "qwen-flash"``,而 qwen 的 models
清单里从来没有 ``qwen-flash``。已在干净树(含 main)上复现确认是既有问题,不是本轮
引入。修法是把 ``qwen-flash`` 补进 models 清单(而不是改掉任务映射)——任务映射写它
说明意图就是用它,补声明才是让声明与意图一致。

关于型号字符串的可验证性(必须写清楚)
----------------------------------------
型号写错的后果是**静默**的:provider 注册成功、选路成功,直到真正发起请求才 404。
本文件只能保证**内部自洽**(声明与使用一致、无重复),**无法**保证上游认账 —— 那只能
拿真 key 打官方 ``/models`` 端点比对,由 ``scripts/verify_provider_apis.py`` 完成。
本仓库的 CI 与开发沙箱都被网络策略拦掉了所有 LLM 厂商域名
(``connect_rejected``/403),所以那一步只能在有出网的机器上跑。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from core.multi_llm_router import PROVIDER_MODEL_MAP, PROVIDER_REGISTRY

REPO_ROOT = Path(__file__).resolve().parent.parent

_REGISTRY = {spec["name"]: spec for spec in PROVIDER_REGISTRY}


class TestRegistryInternalConsistency:
    def test_no_duplicate_models_within_a_provider(self):
        """同一家的 models 清单不许有重复项。

        这条是我自己踩出来的:给 anthropic 加 ``claude-opus-5`` 时,一次全局替换
        把刚加的那项和被替换的旧项变成了同一个字符串,清单里于是出现两个
        ``claude-opus-5``。当时靠人眼看出来,现在让测试兜住。
        """
        dupes = {}
        for name, spec in _REGISTRY.items():
            models = spec.get("models") or []
            if len(models) != len(set(models)):
                dupes[name] = [m for m in set(models) if models.count(m) > 1]
        assert not dupes, f"这些 provider 的 models 清单有重复项: {dupes}"

    def test_default_model_is_declared(self):
        bad = {
            name: spec.get("default_model")
            for name, spec in _REGISTRY.items()
            if spec.get("default_model") and spec["default_model"] not in (spec.get("models") or [])
        }
        assert not bad, f"default_model 不在自家 models 清单里: {bad}"

    def test_task_map_models_are_all_declared(self):
        """核心不变式:按任务选出的型号必须是该家声明过的。"""
        violations = []
        for provider, per_task in PROVIDER_MODEL_MAP.items():
            spec = _REGISTRY.get(provider)
            if spec is None:
                continue  # ollama/hf_local/oneapi 走独立注册段,不在 registry 里
            declared = set(spec.get("models") or [])
            for task_type, model in per_task.items():
                if model not in declared:
                    tt = getattr(task_type, "value", task_type)
                    violations.append(f"{provider}.{tt} = {model!r} 未在该家 models 清单中声明")
        assert not violations, "任务映射选出了未声明的型号(会一路带到真实请求): " + "; ".join(violations)

    def test_qwen_flash_regression(self):
        """显式钉住上面那处既有违反,防止再被改回去。"""
        assert "qwen-flash" in _REGISTRY["qwen"]["models"]

    def test_every_registry_provider_has_a_base_url(self):
        missing = [n for n, s in _REGISTRY.items() if not s.get("base_url")]
        assert not missing, f"这些 provider 没有 base_url: {missing}"


class TestOfficialEndpoints:
    """调用地址必须是各家官方域名 —— 不是聚合器、不是代理。

    ``OPENAI_API_BASE`` 这类"用户自定义中转"是**运行期**覆盖(见 registry 的
    ``base_env``),与这里的默认值是两回事:默认值必须是官方的,用户想走中转再自己填。
    """

    OFFICIAL_HOSTS = {
        "openai": "api.openai.com",
        "anthropic": "api.anthropic.com",
        "deepseek": "api.deepseek.com",
        "qwen": "dashscope.aliyuncs.com",
        "zhipu": "open.bigmodel.cn",
        "moonshot": "api.moonshot.cn",
        "groq": "api.groq.com",
        "openrouter": "openrouter.ai",
        "mistral": "api.mistral.ai",
        "perplexity": "api.perplexity.ai",
        "xai": "api.x.ai",
        "meta": "api.llama.com",
    }

    @pytest.mark.parametrize("provider,host", sorted(OFFICIAL_HOSTS.items()))
    def test_base_url_points_at_the_official_host(self, provider, host):
        spec = _REGISTRY.get(provider)
        if spec is None:
            pytest.skip(f"{provider} 不在 PROVIDER_REGISTRY 里")
        base = spec.get("base_url") or ""
        assert base.startswith("https://"), f"{provider} 的 base_url 不是 https: {base!r}"
        assert host in base, f"{provider} 的 base_url 不指向官方域名 {host}: {base!r}"


class TestNewFlagshipModels:
    """本轮按所有者要求新增的四个旗舰型号。

    注意区分两种确定性:

    * ``claude-opus-5`` 是**已知确定**的 Anthropic 型号 id;
    * ``kimi-k3`` / ``glm-5.2`` / ``qwen3.8-max`` 是**按本仓库既有命名惯例推得**的
      (仓库里原本就是 ``kimi-k2.6`` / ``glm-5.1`` / ``qwen3.7-max`` 这种写法),
      **未对着上游核验过**。要确认必须跑 ``scripts/verify_provider_apis.py``
      (需要出网,本沙箱与 CI 都被网络策略拦住)。
    """

    @pytest.mark.parametrize(
        "provider,model",
        [
            ("anthropic", "claude-opus-5"),
            ("moonshot", "kimi-k3"),
            ("zhipu", "glm-5.2"),
            ("qwen", "qwen3.8-max"),
            ("qwen", "qwen3.8-coder"),
        ],
    )
    def test_new_model_is_declared(self, provider, model):
        assert model in _REGISTRY[provider]["models"], f"{provider} 的 models 里没有 {model}"

    @pytest.mark.parametrize(
        "provider,model",
        [("moonshot", "kimi-k3"), ("zhipu", "glm-5.2"), ("qwen", "qwen3.8-max")],
    )
    def test_new_flagship_became_the_default(self, provider, model):
        assert _REGISTRY[provider]["default_model"] == model

    def test_anthropic_default_stays_on_the_cheaper_tier(self):
        """anthropic 刻意**不**把默认换成 opus。

        opus 是重档,按任务映射只在 reasoning/creative/analysis/planning 用;默认留
        sonnet 是成本/质量的取舍。把默认换成 opus 会让每一次普通调用都走最贵的档。
        """
        assert _REGISTRY["anthropic"]["default_model"] == "claude-sonnet-5"

    @pytest.mark.parametrize(
        "provider,task,model",
        [
            ("anthropic", "reasoning", "claude-opus-5"),
            ("anthropic", "planning", "claude-opus-5"),
            ("moonshot", "general", "kimi-k3"),
            ("moonshot", "coding", "kimi-k3"),
            ("zhipu", "reasoning", "glm-5.2"),
            ("qwen", "reasoning", "qwen3.8-max"),
            ("qwen", "coding", "qwen3.8-coder"),
        ],
    )
    def test_task_map_upgraded_to_the_new_models(self, provider, task, model):
        """新型号不只是"加进清单",原先指向旧旗舰的任务槽位要真的升上去 ——
        否则就是"加了但没人用"。"""
        per_task = {getattr(tt, "value", tt): m for tt, m in PROVIDER_MODEL_MAP[provider].items()}
        assert per_task[task] == model

    def test_superseded_opus_is_gone_everywhere(self):
        """claude-opus-4-8 已被 opus-5 取代,不该在任何一处残留。"""
        assert "claude-opus-4-8-20250529" not in _REGISTRY["anthropic"]["models"]
        assert "claude-opus-4-8-20250529" not in PROVIDER_MODEL_MAP["anthropic"].values()

    def test_zhipu_flash_tier_untouched(self):
        """没有见过 glm-5.2-flash,就不臆造一个 —— fast_response 保持 5.1-flash。"""
        per_task = {getattr(tt, "value", tt): m for tt, m in PROVIDER_MODEL_MAP["zhipu"].items()}
        assert per_task["fast_response"] == "glm-5.1-flash"


class TestConfigExampleStaysInSync:
    """``runtime/config.example.json`` 里的型号也要跟着升,否则新装机的人拿到的是旧型号。"""

    @staticmethod
    def _text() -> str:
        return (REPO_ROOT / "runtime/config.example.json").read_text(encoding="utf-8")

    def test_is_valid_json(self):
        json.loads(self._text())

    @pytest.mark.parametrize("stale", ["claude-opus-4-8-20250529", "qwen3.7-max", 'glm-5.1"'])
    def test_no_stale_model_left(self, stale):
        assert stale not in self._text(), f"config.example.json 里还残留旧型号 {stale}"

    @pytest.mark.parametrize("fresh", ["claude-opus-5", "qwen3.8-max", "glm-5.2"])
    def test_new_model_present(self, fresh):
        assert fresh in self._text()


class TestVerificationScriptExists:
    """型号是否被上游认账只能实测。这条保证那个工具还在、且能 --offline 跑通。"""

    def test_script_is_present_and_executable_offline(self):
        import subprocess

        script = REPO_ROOT / "scripts/verify_provider_apis.py"
        assert script.exists(), "上游核验脚本不见了 —— 型号正确性就再也没有可验证的手段了"
        proc = subprocess.run(
            [__import__("sys").executable, str(script), "--offline", "--json"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=180,
        )
        payload = json.loads(proc.stdout)
        assert payload["static"]["problems"] == [], f"静态对齐有问题: {payload['static']['problems']}"


class TestVerifyScriptNeverLeaksSecrets:
    """CodeQL 判过这个脚本 high severity「明文记录敏感信息」。前后两轮都有真问题。

    第一轮两处
    ----------
    1. ``_mask()`` 输出密钥**长度**。我当时在那份"安全"说明里把"只输出长度"当成安全的 ——
       它不安全:长度是指纹(能区分 ``sk-``+32 与 ``gsk_``+52,从而暴露是哪家的哪种
       key),且构成一条从密钥值到 stdout 的真实污点路径。
    2. 上游鉴权失败响应会**把收到的 key 原样回显**在 message 里,而脚本把响应体照原样
       打了出来。

    第二轮:第一轮的修法本身不够好
    ------------------------------
    我第一轮是加了个 ``_scrub(text, secret)`` 洗掉密钥再打印。CodeQL 仍然报 high,而且
    它有道理 —— 那个做法**依赖脱敏正则完备**(上游回显形式无法穷举),而且从数据流看
    就是 ``secret → _scrub → return → print``,反而让污点边更明显。

    最终改成**根本不输出上游响应体**:诊断只用 HTTP 状态码 + 一张固定措辞表,异常只报
    类型名。这样不依赖正则,也没有从密钥到输出的通路。

    另外 gitleaks 报了 3 处 ``generic-api-key`` —— 是我在这个测试文件里写的**形似真
    密钥的字面量**(``sk-live-...`` 之类)。即使是假的也不该留:它会训练人忽略扫描器。
    现在需要"非占位符的密钥值"时一律**运行时拼**,文件里不存在可被匹配的字面量。
    """

    #: 运行时拼装,避免在文件里留下形似凭据的字面量(gitleaks generic-api-key)。
    #: 这两个只用于喂 _verdict(),它只关心"空/占位符/其它"三态,不关心长相。
    FAKE_SHORT = "s" + "k" + "-" + "9" * 20
    FAKE_LONG = "g" + "s" + "k" + "_" + "7" * 60

    @staticmethod
    def _mod():
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "_verify_provider_apis", REPO_ROOT / "scripts/verify_provider_apis.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _code_only(path: Path) -> str:
        """去掉注释**与文档字符串**后的纯代码。

        这个坑本轮踩到第四次:白盒断言直接搜字面量,结果被自己的说明文字绊倒 ——
        ``_explain`` 的 docstring 里正引用着被弃用的 ``_scrub`` 来解释为什么要改。
        要断言的是"代码里还有没有这个写法",不是"文件里有没有出现过这串字"。
        用 AST 剥比正则可靠。
        """
        import ast

        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                body = getattr(node, "body", [])
                if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                    if isinstance(body[0].value.value, str):
                        body.pop(0)
        return ast.unparse(tree)

    def test_verdict_returns_only_constants(self):
        m = self._mod()
        assert m._verdict("") == "未配置"
        assert m._verdict("your_openai_api_key_here") == "占位符"
        assert m._verdict(self.FAKE_SHORT) == "已配置"

    def test_verdict_output_contains_no_length_information(self):
        """判别长度泄露的唯一有效方式:两把**长度不同**的 key 必须得到完全相同的输出。

        只断言"输出里没有 key 本身"是挡不住长度的。
        """
        m = self._mod()
        assert len(self.FAKE_SHORT) != len(self.FAKE_LONG)
        assert m._verdict(self.FAKE_SHORT) == m._verdict(self.FAKE_LONG)
        assert str(len(self.FAKE_SHORT)) not in m._verdict(self.FAKE_SHORT)

    def test_explain_returns_fixed_wording_only(self):
        """诊断措辞必须来自固定表,不含任何上游内容。"""
        m = self._mod()
        assert "key 无效" in m._explain(401)
        assert "无权限" in m._explain(403)
        assert "base_url" in m._explain(404)
        assert m._explain(418) == "上游返回了非 2xx"

    def test_http_error_path_never_reads_the_response_body(self):
        """关键:HTTPError 分支**不能**去读 exc.read() —— 响应体里可能有被回显的密钥。"""
        code = self._code_only(REPO_ROOT / "scripts/verify_provider_apis.py")
        assert "exc.read(" not in code, "又在读上游响应体了"
        assert "_explain(exc.code)" in code

    def test_exception_paths_report_type_name_only(self):
        """异常只报类型名,不报文本(某些实现会把带密钥的 URL/头写进 str(exc))。"""
        code = self._code_only(REPO_ROOT / "scripts/verify_provider_apis.py")
        assert "str(exc)" not in code, "还在输出异常文本"
        assert "type(exc).__name__" in code

    def test_payload_is_never_echoed(self):
        code = self._code_only(REPO_ROOT / "scripts/verify_provider_apis.py")
        assert "json.dumps(payload)" not in code, "还在回传上游 payload"

    def test_no_scrub_helper_remains(self):
        """反向验证:依赖正则的旧修法已被更强的做法取代,不该留着。"""
        code = self._code_only(REPO_ROOT / "scripts/verify_provider_apis.py")
        assert "_scrub" not in code
        assert "len(value)" not in code, "还有地方把密钥长度写进输出"

    def test_no_credential_shaped_literals_in_this_file(self):
        """自查:本文件不许再出现形似真密钥的字面量(gitleaks generic-api-key)。

        判据取得比 gitleaks 更严一点:``sk-``/``gsk_`` 前缀后跟 16+ 位连续字符。
        需要这种值时运行时拼装。
        """
        src = Path(__file__).read_text(encoding="utf-8")
        hits = re.findall(r"[\"']((?:sk|gsk|pk)[-_][A-Za-z0-9]{16,})[\"']", src)
        assert not hits, f"本文件出现形似凭据的字面量: {hits}"
