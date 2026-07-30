"""核验脚本的输出:既不能含密钥值,字段名也不能**冒充**密钥值。

第二条不是洁癖,它是一个被误诊了三轮的真实事故的收尾
--------------------------------------------------------
``scripts/verify_provider_apis.py`` 的静态明细字典里有一项曾叫 ``"secret_keys"``,值是
``len(_SECRET_MODEL_KEYS)`` —— 一个 int。CodeQL 的
``py/clear-text-logging-sensitive-data`` 仍判 high severity,因为该规则的敏感源启发式会
匹配**字符串下标本身**:``detail["secret_keys"]`` 中 "secret" 一词就足以让它认定这个
表达式是 secret 类敏感数据(告警文案 "logs sensitive data (secret) as clear text" 里的
``(secret)`` 分类正是由这个词触发),再看到它流进 ``print()`` 就报。值是个计数,规则不看。

代价是实打实的:为清这条告警,先后改了三轮**密钥值**的输出路径 —— 去掉长度输出、不再
打印上游响应体、参数改成只传布尔。告警一动没动,因为被标的表达式里从来没有密钥值。

所以这里钉两件事:

* 明细字典的**键名**不得再出现 secret/token/password 之类的字样(否则同一个误判会回来,
  而且下一个人同样会去改错的地方);
* 明细字典的**值**必须全是数字(这才是"这里没有密钥"的实质保证 —— 只靠改名字是把静态
  分析哄住了,不等于真的安全)。

顺带钉住的第二处
----------------
同一次排查发现 ``static_audit()`` 里有条问题描述是错的:它写着某个 key 不在
``_SECRET_MODEL_KEYS`` 就"会被【明文】写进 .env"。落盘去向其实由
``core.config_schema.classify_key()`` 的后缀启发式决定(以 ``_API_KEY`` 结尾一律判
``"secret"`` → ``set_secret()`` → ``runtime/secrets.env``),与这份名单无关。这份名单在
全仓库只有一个用处:``core/routes/config.py:833`` 的 ``"configured"`` 映射,也就是面板
「模型」tab 上的"已配置"角标。真实后果是**填了 key 面板却不亮绿标**。

一条报错信息说错了后果,比不报错更糟 —— 它会把人引向错误的修法。
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts/verify_provider_apis.py"

#: CodeQL 敏感源启发式会认的字样(``SensitiveDataHeuristics``)。
_SENSITIVE_WORD = re.compile(r"secret|passw(or)?d|token|credential|api_?key", re.I)


def _static_audit_detail() -> dict:
    from scripts.verify_provider_apis import static_audit

    _problems, detail = static_audit()
    return detail


class TestDetailDictHasNoSensitiveLookingNames:
    def test_no_key_name_matches_the_heuristic(self):
        offenders = [k for k in _static_audit_detail() if _SENSITIVE_WORD.search(k)]
        assert not offenders, (
            f"明细字典的键名 {offenders} 会被 CodeQL 判成敏感源 —— "
            "它们的值只是计数,但规则匹配的是下标字符串本身。改个准确的名字。"
        )

    def test_all_values_are_plain_numbers(self):
        """实质保证:这里装的全是计数,不是任何密钥值。"""
        for key, val in _static_audit_detail().items():
            assert isinstance(val, int) and not isinstance(val, bool), f"{key} 的值不是计数: {val!r}"

    def test_the_badge_roster_count_is_still_reported(self):
        """改名不能顺手把这项信息弄丢 —— 四份清单的对齐报告里它是其中一份。"""
        detail = _static_audit_detail()
        assert "configured_badge_keys" in detail
        assert detail["configured_badge_keys"] > 0


class TestPrintedLinesReferenceOnlyExistingFields:
    """改名最容易漏的是打印处 —— 漏了就是运行时 KeyError,而这个脚本平时没人跑。"""

    def test_every_detail_subscript_in_the_script_exists(self):
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        detail = _static_audit_detail()
        referenced = {
            node.slice.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Subscript)
            and isinstance(node.value, ast.Name)
            and node.value.id == "detail"
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
        }
        assert referenced, "没找到任何 detail[...] 引用,本测试失去意义(是否改了变量名?)"
        missing = sorted(referenced - set(detail))
        assert not missing, f"脚本里引用了不存在的明细字段 {missing} —— 运行时会 KeyError"


class TestNoSecretValuesReachTheOutput:
    """把此前三轮改动的成果一并钉住,防止回退。"""

    def test_error_path_never_reads_the_upstream_response_body(self):
        """只针对**错误分支**。

        成功分支读 body 是这个脚本的本职(要拿型号清单),不能一刀切禁掉 ``.read()``
        —— 我第一版就是这么写的,结果断言打到了合法的成功路径上。会回显 key 原文的是
        鉴权失败响应,也就是 ``HTTPError`` 那条分支。
        """
        tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
        handlers = [
            h
            for h in ast.walk(tree)
            if isinstance(h, ast.ExceptHandler) and "HTTPError" in ast.unparse(h.type or ast.Constant(""))
        ]
        assert handlers, "找不到 HTTPError 分支 —— 本测试失去意义"
        for h in handlers:
            reads = [
                n
                for n in ast.walk(ast.Module(body=h.body, type_ignores=[]))
                if isinstance(n, ast.Attribute) and n.attr == "read"
            ]
            assert not reads, "HTTPError 分支又开始读响应体了 —— 多家的鉴权失败响应会回显 key 原文"

    def test_script_never_reports_key_length(self):
        """长度是指纹:``sk-``+32 与 ``gsk_``+52 一看就知道是哪家的哪种 key。"""
        code = _strip_prose(SCRIPT.read_text(encoding="utf-8"))
        assert not re.search(r"len\(\s*(api_)?key\b", code), "又在输出密钥长度了"


class TestWrongConsequenceMessageIsFixed:
    """那条报错信息必须说真实后果。"""

    def test_message_no_longer_claims_plaintext_env_write(self):
        code = _strip_prose(SCRIPT.read_text(encoding="utf-8"))
        assert "明文】写进 .env" not in code, (
            "这条描述是错的:落盘去向由 classify_key() 的后缀启发式决定," "跟 _SECRET_MODEL_KEYS 无关"
        )

    def test_message_states_the_real_consequence(self):
        code = _strip_prose(SCRIPT.read_text(encoding="utf-8"))
        assert "角标" in code, "应说明真实后果:面板「已配置」角标不亮"

    def test_the_roster_really_only_drives_the_badge(self):
        """反过来验证上面那个说法本身 —— 否则我只是把一句错话换成另一句。

        ``_SECRET_MODEL_KEYS`` 在 core/routes/config.py 里应当只被"已配置"映射用到。
        """
        tree = ast.parse((REPO_ROOT / "core/routes/config.py").read_text(encoding="utf-8"))
        # 按 AST 的 Name 节点数,不按文本行:``ast.unparse`` 会把整个 dict 字面量压成一行,
        # 于是 _SECRET_MODEL_KEYS 与 _NON_SECRET_MODEL_KEYS 挤在同一行 —— 我第一版用
        # "该行不含 _NON_SECRET" 过滤,恰好把唯一的真实用处滤掉了。
        loads = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Name) and n.id == "_SECRET_MODEL_KEYS" and isinstance(n.ctx, ast.Load)
        ]
        assert len(loads) == 1, f"读取处变成 {len(loads)} 处,本测试的前提需要重新核实: 行号 {[n.lineno for n in loads]}"

        # 那唯一一处必须落在 "configured" 那个映射里。
        owners = [
            d
            for d in ast.walk(tree)
            if isinstance(d, ast.Dict)
            and any(isinstance(k, ast.Constant) and k.value == "configured" for k in d.keys)
            and "_SECRET_MODEL_KEYS" in ast.unparse(d)
        ]
        assert owners, "唯一的读取处不在 configured 映射里了 —— 用途变了,报错信息的措辞要跟着改"


def _strip_prose(src: str) -> str:
    """去掉注释与 docstring,只留可执行代码。

    这一步是必须的:本文件的说明性文字里就写着 ``secret_keys``、``明文】写进 .env`` 这些
    字样,若直接对原文做断言,断言会命中我自己的散文而非代码,从而永远为真(或永远为假)。
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                if isinstance(body[0].value.value, str):
                    body.pop(0)
                    if not body:
                        body.append(ast.Pass())
    return ast.unparse(tree)


class TestTheStripperItself:
    """上面所有断言都建立在 _strip_prose 真的把散文去掉了这个前提上。"""

    def test_docstrings_and_comments_are_gone(self):
        code = _strip_prose('"""模块 secret_keys 说明"""\nx = 1  # secret_keys 注释\n')
        assert "secret_keys" not in code
        assert "x = 1" in code

    def test_string_literals_in_code_survive(self):
        """只去 docstring,不去真正参与运算的字符串 —— 否则会漏掉真实的输出语句。"""
        code = _strip_prose('print("secret_keys")\n')
        assert "secret_keys" in code

    @pytest.mark.parametrize("path", ("scripts/verify_provider_apis.py", "core/routes/config.py"))
    def test_survives_the_real_files(self, path):
        assert _strip_prose((REPO_ROOT / path).read_text(encoding="utf-8"))
