"""
core/config_preflight.py — Galaxy Pre-flight Configuration Check  (PR-G3)
==========================================================================

Validates that all **critical** environment variables are present before the
Galaxy runtime starts.  When a required variable is absent the checker emits
an actionable hint and, in *fail_fast* mode, raises ``ConfigPreflightError``
so the process exits with a non-zero status instead of crashing later with a
less descriptive error.

Public API
----------
run_preflight(dry_run=False, fail_fast=True, mode="auto") -> PreflightReport
    Run all configured checks and return a report.  When *fail_fast* is True
    and at least one CRITICAL finding is present, raises ConfigPreflightError
    after printing the report.

    *mode* selects which check groups to run:
      "auto"        — infer from environment (gateway/android/ws/core/all)
      "gateway"     — galaxy_gateway process
      "android"     — Android-client-facing WS bridge
      "ws"          — WebSocket / signaling config
      "core"        — core runtime (LLM keys, auth)
      "all"         — every group

ConfigPreflightError
    Raised on critical failure when fail_fast=True.

Local configuration authority integration  (PR-3)
-------------------------------------------------
Preflight automatically loads ``runtime/secrets.env`` into the process
environment (without overwriting already-set env vars) before running checks.
This means secrets configured via the local unified authority are visible to
the preflight check exactly as if they had been exported in the shell.

The canonical local persistence targets are:
  - ``runtime/config.json``  — non-secret system configuration
  - ``runtime/secrets.env``  — secret values (API keys, tokens)

Environment variables that influence this module
------------------------------------------------
GALAXY_PREFLIGHT_MODE      Override the mode when running as __main__.
GALAXY_PREFLIGHT_FAIL_FAST Set to "0"/"false" to disable fail-fast.
GALAXY_SECRET_BACKEND      "env" (default) | "vault" | "kms" — selects the
                            credentials back-end used by CredentialVault.
"""

from __future__ import annotations

import logging
import os
import sys
import textwrap
from dataclasses import dataclass, field, replace
from enum import Enum
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger("Galaxy.ConfigPreflight")


# ---------------------------------------------------------------------------
# Local configuration authority loader  (PR-3)
# ---------------------------------------------------------------------------


def _load_runtime_secrets_into_env() -> List[str]:
    """
    Load ``runtime/secrets.env`` into ``os.environ`` (without overwriting).

    Returns the list of key names that were loaded from the file so that the
    preflight report can indicate their source.

    This function is called once at the start of ``run_preflight``.  It is
    idempotent and never raises — errors are logged/printed but do not block
    startup.
    """
    _secrets_path = Path(__file__).parent.parent / "runtime" / "secrets.env"
    loaded: List[str] = []
    if not _secrets_path.exists():
        return loaded
    try:
        with open(_secrets_path, encoding="utf-8") as fh:
            for raw_line in fh:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip()
                if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
                    val = val[1:-1]
                if key and val and key not in os.environ:
                    os.environ[key] = val
                    loaded.append(key)
    except OSError:
        pass  # non-fatal; the env-check below will report missing vars
    return loaded


# ---------------------------------------------------------------------------
# Severity levels
# ---------------------------------------------------------------------------


class Severity(str, Enum):
    CRITICAL = "CRITICAL"  # Must be set; startup should be blocked
    WARNING = "WARNING"  # Strongly recommended; feature will be degraded
    INFO = "INFO"  # Informational; defaults exist


# ---------------------------------------------------------------------------
# Check descriptor
# ---------------------------------------------------------------------------


@dataclass
class EnvCheck:
    """Describes a single environment-variable requirement."""

    var: str
    severity: Severity
    description: str
    hint: str
    groups: List[str]  # which preflight groups this belongs to
    allow_placeholder: bool = True  # treat "your_*_here" as missing


# ---------------------------------------------------------------------------
# Registry of checks
# ---------------------------------------------------------------------------
#
# Groups:
#   core     — LLM keys, auth, token — needed by the main Galaxy server
#   gateway  — galaxy_gateway process
#   android  — Android WS / device bridge
#   ws       — WebSocket / WebRTC / signaling
#   vault    — Secret-vault back-end

_CHECKS: List[EnvCheck] = [
    # ── Core: LLM (at least one required; all WARNING) ───────────────────
    EnvCheck(
        var="OPENAI_API_KEY",
        severity=Severity.WARNING,
        description="OpenAI 的密钥,用来调它家的大模型。",
        hint="在 .env 里写 OPENAI_API_KEY=sk-…(至少要有一家大模型的密钥,智能体才跑得起来)。",
        groups=["core", "all"],
    ),
    EnvCheck(
        var="ANTHROPIC_API_KEY",
        severity=Severity.WARNING,
        description="Anthropic Claude 的密钥(已经填了 OpenAI 的话,这个可不填)。",
        hint="在 .env 里写 ANTHROPIC_API_KEY=sk-ant-… 就能用 Claude(GALAXY_LLM_PROVIDER=anthropic 时必须有)。",
        groups=["core", "all"],
    ),
    # ── Core: auth / security ────────────────────────────────────────────
    EnvCheck(
        var="GALAXY_API_TOKEN",
        severity=Severity.CRITICAL,
        description="访问口令。REST 与 WebSocket 接口靠它认人。",
        hint=(
            '在 .env 里写 GALAXY_API_TOKEN=$(python3 -c "import secrets;print(secrets.token_urlsafe(32))"),'
            "再加 GALAXY_AUTH_ENABLED=true 才真正生效。\n"
            "另有 GALAXY_REQUIRE_API_TOKEN=true:即使没开鉴权,缺口令也算阻断(预发环境用)。"
            "不设它、又关着鉴权的话,任何人都能命令这套接口。"
        ),
        groups=["core", "gateway", "all"],
    ),
    # ── Core: secret back-end ────────────────────────────────────────────
    EnvCheck(
        var="SECRETVAULT_MASTER_KEY",
        severity=Severity.WARNING,
        description="密钥保险箱(Node_03 SecretVault)的主密钥。",
        hint=(
            "在 .env 里写 SECRETVAULT_MASTER_KEY=$(python3 -c 'from cryptography.fernet import Fernet;"
            "print(Fernet.generate_key().decode())')(GALAXY_SECRET_BACKEND=vault 时必须有)。"
        ),
        groups=["vault", "all"],
    ),
    # ── Gateway ──────────────────────────────────────────────────────────
    # ── System mode / fabric baseline (canonical config contract) ────────
    EnvCheck(
        var="GALAXY_SYSTEM_MODE",
        severity=Severity.INFO,
        description="系统运行模式(默认 desktop-local:只在这一台机器上跑)。",
        hint=(
            "desktop-local = 单机(默认);desktop-cross-device = 打开跨设备编织层。" "细节见 docs/SYSTEM_MODE_CONFIG.md。"
        ),
        groups=["core", "gateway", "all"],
    ),
    EnvCheck(
        var="GALAXY_NATS_ENABLED",
        severity=Severity.INFO,
        description="要不要开 NATS 消息总线(默认跟着 GALAXY_SYSTEM_MODE 走)。",
        hint="填 true 可以不管模式强行打开(默认:单机关、跨设备开)。",
        groups=["gateway", "all"],
    ),
    EnvCheck(
        var="GALAXY_FABRIC_STRICT",
        severity=Severity.INFO,
        description="编织层依赖缺失时是否直接判启动失败(默认 false)。",
        hint=("只有在 desktop-cross-device 且 NATS 非有不可时才填 true;" "保持 false(默认)则缺了就降级运行。"),
        groups=["gateway", "all"],
    ),
    EnvCheck(
        var="GALAXY_NETWORK_MODE",
        severity=Severity.INFO,
        description="联网方式:local | lan | tailscale | relay(默认 local)。",
        hint="local = 只本机(默认);lan = 只局域网;tailscale = 走 Tailscale;relay = 走公网中继服务器。",
        groups=["gateway", "all"],
    ),
    EnvCheck(
        var="GALAXY_CROSS_DEVICE_ENABLED",
        severity=Severity.INFO,
        description="要不要把任务路由到别的设备上(默认跟着 GALAXY_SYSTEM_MODE 走)。",
        hint=(
            "填 true/false 可以强行指定(false = 只用本机,最保险的默认);"
            "设了 GALAXY_SYSTEM_MODE 的话会自动跟着它推导。"
        ),
        groups=["gateway", "all"],
    ),
    # ── WebSocket / signaling ────────────────────────────────────────────
    EnvCheck(
        var="GALAXY_SIGNALING_TIMEOUT_S",
        severity=Severity.INFO,
        description="WebRTC 建立连接的等待上限,单位秒(默认 30)。",
        hint="填正整数秒(默认 30;网络慢的话调到 60)。",
        groups=["ws", "all"],
    ),
    # ── Android bridge ───────────────────────────────────────────────────
    EnvCheck(
        var="GALAXY_AUTH_ENABLED",
        severity=Severity.WARNING,
        description="是否对所有接口强制校验访问口令(默认 false)。",
        hint="正式环境填 true(同时要有 GALAXY_API_TOKEN);不开的话安卓端是免认证连进来的。",
        groups=["android", "gateway", "all"],
    ),
    # ── TLS ─────────────────────────────────────────────────────────────
    EnvCheck(
        var="GALAXY_TLS_CERT",
        severity=Severity.INFO,
        description="TLS 证书文件路径(和 GALAXY_TLS_KEY 一起填就启用 HTTPS)。",
        hint=(
            "要 HTTPS 就写 GALAXY_TLS_CERT=/path/cert.pem 加 GALAXY_TLS_KEY=/path/key.pem;"
            "留空 = 明文 HTTP(只适合本机开发)。"
        ),
        groups=["gateway", "ws", "all"],
    ),
    # ── NATS (optional) ──────────────────────────────────────────────────
    EnvCheck(
        var="GALAXY_NATS_URL",
        severity=Severity.INFO,
        description="NATS 控制面地址(默认 nats://localhost:4222)。",
        hint="填 nats://localhost:4222 就用 NATS 控制面;不填就是不用,相关链路空转。",
        groups=["gateway", "all"],
    ),
    # ── Runtime bridge (optional) ────────────────────────────────────────
    EnvCheck(
        var="GALAXY_RUNTIME_URL",
        severity=Severity.INFO,
        description="Galaxy 智能体运行时的地址(给 AgentBridge 用)。",
        hint="跑了智能体运行时就填 http://localhost:8200;不填就是不用这座桥。",
        groups=["gateway", "all"],
    ),
]


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


@dataclass
class Finding:
    check: EnvCheck
    present: bool
    value_hint: str = ""  # safe summary of the value (never the actual secret)


@dataclass
class PreflightReport:
    findings: List[Finding] = field(default_factory=list)
    mode: str = "all"

    # ── helpers ──────────────────────────────────────────────────────────

    @property
    def criticals(self) -> List[Finding]:
        return [f for f in self.findings if not f.present and f.check.severity == Severity.CRITICAL]

    @property
    def warnings(self) -> List[Finding]:
        return [f for f in self.findings if not f.present and f.check.severity == Severity.WARNING]

    @property
    def passed(self) -> List[Finding]:
        return [f for f in self.findings if f.present]

    @property
    def ok(self) -> bool:
        """True only when there are no CRITICAL findings."""
        return len(self.criticals) == 0

    # ── display ──────────────────────────────────────────────────────────

    def format(self, verbose: bool = True) -> str:
        # 颜色/字体与启动界面其余部分统一:走 core.cli_render 的 _use_color() 门闸
        # + core.ascii_art.Colors 同一套配色(标题 CYAN 粗体、✗ 红、⚠ 黄、✓ 绿、
        # 变量名粗体、描述与提示 DIM)。非 TTY / 不支持色彩时自动退化为纯文本
        # (故 assertIn 一类测试不受影响)。任何导入失败都安全回退为无色。
        try:
            from core import cli_render as _r
            from core.ascii_art import CONTENT_INDENT as _INDENT
            from core.ascii_art import ICON_COL as _ICON_COL
            from core.ascii_art import Colors as _Co
            from core.ascii_art import display_width as _display_width
            from core.ascii_art import pad_display as _pad

            _use = _r._use_color()
        except Exception:  # noqa: BLE001 — 渲染增强失败绝不影响预检本身
            _use = False
            _INDENT, _ICON_COL = 2, 2

            def _display_width(text: str) -> int:  # type: ignore[misc]
                return len(text)

            def _pad(text: str, width: int) -> str:  # type: ignore[misc]
                return text + " " * max(0, width - len(text))

            class _Co:  # type: ignore
                BOLD = CYAN = DIM = GREEN = YELLOW = RED = ENDC = ""

        def _c(t: str, color: str) -> str:
            return f"{color}{t}{_Co.ENDC}" if _use else t

        def _row(icon: str, text: str, color: str) -> str:
            """一行"图标 + 说明",列位与 ``cli_render.phase`` 完全一致。

            此前这里是手写的 ``"  " + "✓  ..."``(图标后两个空格),于是本块的对勾
            落在第 5 列,而启动界面其余每一行的对勾都在第 4 列 —— 同一屏里两条对勾列。
            现在图标一律 ``pad_display(icon, ICON_COL)``,跟着几何常量走。
            """
            return " " * _INDENT + _c(_pad(icon, _ICON_COL), color) + text

        # 盒子标题按盒宽【居中计算】,不再手写空格——真机复现过标题行内宽 57、
        # 上下边框内宽 58,导致标题右侧 ║ 比边框的 ╗ 缩进一格(整个白框歪一行)。
        # 盒宽 58 与启动 banner(core.ascii_art)一致,两个白框从此完全对齐。
        _box_inner = 58
        _title = "Galaxy 启动前配置检查"
        _title_w = _display_width(_title)
        _gap = max(0, _box_inner - _title_w)
        _left = _gap // 2
        _right = _gap - _left
        _summary = (
            " " * _INDENT + f"{_c('运行模式', _Co.DIM)} {self.mode}   "
            f"{_c('通过', _Co.DIM)} {_c(str(len(self.passed)), _Co.GREEN)}  "
            f"{_c('提醒', _Co.DIM)} {_c(str(len(self.warnings)), _Co.YELLOW)}  "
            f"{_c('阻断', _Co.DIM)} {_c(str(len(self.criticals)), _Co.RED)}"
            f"   {_c(f'共 {len(self.findings)} 项判据', _Co.DIM)}"
        )
        lines: List[str] = [
            "",
            _c("╔" + "═" * _box_inner + "╗", _Co.CYAN),
            _c("║" + " " * _left, _Co.CYAN) + _c(_title, _Co.BOLD + _Co.CYAN) + _c(" " * _right + "║", _Co.CYAN),
            _c("╚" + "═" * _box_inner + "╝", _Co.CYAN),
            _summary,
            "",
        ]

        # 符号与 core.cli_render 统一(✓/⚠/✗,均为 1 显示格),不再混用 emoji
        # ✅/⚠️/❌(带变体选择符、多数终端渲染成 2 格),避免整个克隆界面对号列
        # 因图标宽度不一而错位。每条:`• VAR — 描述`(变量名与描述并作一行,省一行),
        # 提示首行带 💡、续行只缩进不再重复 💡,条目间不留空行 → 更紧凑。
        def _emit_section(icon: str, header: str, color: str, findings: List["Finding"]) -> None:
            lines.append(_row(icon, _c(header, color), color))
            lines.append(" " * _INDENT + _c("─" * 56, _Co.DIM))
            for f in findings:
                _desc = _c("— " + f.check.description, _Co.DIM)
                lines.append(_row("•", f"{_c(f.check.var, _Co.BOLD)} {_desc}", color))
                hint_lines = f.check.hint.splitlines()
                for i, hint_line in enumerate(hint_lines):
                    prefix = "怎么办: " if i == 0 else "        "
                    lines.append(" " * (_INDENT + _ICON_COL) + _c(prefix + hint_line.strip(), _Co.DIM))

        if self.criticals:
            _emit_section("✗", "这些没配好,起不来 —— 必须先补上", _Co.RED, self.criticals)
        if self.warnings and verbose:
            _emit_section("⚠", "这些没配也能启动,但对应功能用不了", _Co.YELLOW, self.warnings)
        if self.ok:
            lines.append(_row("✓", _c("关键项都齐了,不挡启动。", _Co.GREEN), _Co.GREEN))

        lines.append("")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Error
# ---------------------------------------------------------------------------


class ConfigPreflightError(RuntimeError):
    """Raised when CRITICAL env vars are missing and fail_fast=True."""

    def __init__(self, report: PreflightReport) -> None:
        self.report = report
        missing = ", ".join(f.check.var for f in report.criticals)
        super().__init__(
            f"Pre-flight check failed — missing critical env vars: {missing}\n"
            f"Run 'python -m core.config_preflight' or set the variables and retry."
        )


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

_FALSY = {"0", "false", "no", "off", "none", ""}
# Import placeholder prefixes from credential_vault to share the single source of truth.
# Fall back to a local copy if the import fails (e.g. during isolated testing).
try:
    from core.credential_vault import PLACEHOLDER_PREFIXES as _PLACEHOLDER_PREFIXES
except Exception as exc:
    logger.debug("Fallback triggered: %s", exc)
    _PLACEHOLDER_PREFIXES = ("your_", "your-", "change_me", "todo", "<", "example", "xxx")


def _is_set(var: str, allow_placeholder: bool = True) -> tuple[bool, str]:
    """Return (is_set, value_hint) for an env var."""
    raw = os.environ.get(var, "")
    if not raw:
        return False, ""
    if allow_placeholder and raw.lower().startswith(_PLACEHOLDER_PREFIXES):
        return False, f"(looks like a placeholder: {raw[:20]}…)"
    return True, "(set)"


def _groups_for_mode(mode: str) -> List[str]:
    """Resolve the list of group names for a given mode string."""
    if mode == "all":
        return ["all", "core", "gateway", "android", "ws", "vault"]
    if mode == "auto":
        # Infer from process/env context
        groups = set(["core"])
        if os.environ.get("GALAXY_GATEWAY_MODE") or os.environ.get("GALAXY_TLS_CERT"):
            groups.add("gateway")
        if os.environ.get("GALAXY_ANDROID_WS_ENABLED") or os.environ.get("GALAXY_AUTH_ENABLED"):
            groups.add("android")
        if os.environ.get("GALAXY_SIGNALING_TIMEOUT_S") or os.environ.get("GALAXY_TURN_URLS"):
            groups.add("ws")
        if os.environ.get("GALAXY_SECRET_BACKEND", "env").lower() in ("vault", "kms"):
            groups.add("vault")
        return list(groups)
    return [mode, "core"]


def _api_token_missing_is_critical() -> bool:
    """CRITICAL only when Bearer auth is enforced or explicitly required."""
    auth = os.environ.get("GALAXY_AUTH_ENABLED", "").lower() in ("true", "1", "yes")
    require = os.environ.get("GALAXY_REQUIRE_API_TOKEN", "").lower() in ("true", "1", "yes")
    return auth or require


def _adjust_findings_for_token_policy(findings: List[Finding]) -> List[Finding]:
    """Downgrade missing GALAXY_API_TOKEN from CRITICAL to WARNING when auth is off."""
    out: List[Finding] = []
    for f in findings:
        if (
            f.check.var == "GALAXY_API_TOKEN"
            and not f.present
            and f.check.severity == Severity.CRITICAL
            and not _api_token_missing_is_critical()
        ):
            out.append(
                Finding(
                    check=replace(f.check, severity=Severity.WARNING),
                    present=f.present,
                    value_hint=f.value_hint,
                )
            )
        else:
            out.append(f)
    return out


def _build_protected_compat_ws_policy_finding() -> Optional[Finding]:
    """Return a CRITICAL finding only for protected-mode compat WS policy violations.

    Returns ``None`` when the compat ingress policy is not violated or when the
    policy helper cannot be imported/evaluated.
    """
    try:
        from core.api_routes import (
            PROTECTED_CORE_COMPAT_WS_OVERRIDE_ENV,
            get_core_compat_device_ingress_policy,
        )
    except ImportError:
        return None

    try:
        policy = get_core_compat_device_ingress_policy()
    except Exception as exc:
        logger.warning("Compat WS policy preflight probe failed: %s", exc)
        return None
    if not policy.get("blocked_by_protected_mode"):
        return None

    return Finding(
        check=EnvCheck(
            var="GALAXY_ENABLE_CORE_COMPAT_WS",
            severity=Severity.CRITICAL,
            description=("跨设备保护模式下,不显式放行就不能启用 core 兼容版 WebSocket 入口。"),
            hint=(
                "把 GALAXY_ENABLE_CORE_COMPAT_WS 去掉,正式/跨设备场景请走正规入口 "
                "/ws/device/{device_id}。\n"
                f"只有在明确受控的迁移/排障场景下,才设 {PROTECTED_CORE_COMPAT_WS_OVERRIDE_ENV}=true。"
            ),
            groups=["gateway", "android", "all"],
            allow_placeholder=False,
        ),
        present=False,
    )


def _augment_findings_with_compat_ws_policy(
    findings: List[Finding],
    groups: Sequence[str],
) -> List[Finding]:
    """Append protected-mode compat WS policy violations as CRITICAL findings."""
    if not any(group in {"gateway", "android", "all"} for group in groups):
        return findings

    policy_finding = _build_protected_compat_ws_policy_finding()
    if policy_finding is None:
        return findings
    return [*findings, policy_finding]


def run_preflight(
    dry_run: bool = False,
    fail_fast: bool = True,
    mode: str = "auto",
    checks: Optional[Sequence[EnvCheck]] = None,
    verbose: bool = True,
) -> PreflightReport:
    """
    Run the pre-flight configuration check.

    Parameters
    ----------
    dry_run:
        When True, print the report but never raise ConfigPreflightError.
        Useful for CI validation without blocking startup.
    fail_fast:
        When True (default) and there are CRITICAL findings, raise
        ConfigPreflightError after printing the report.
    mode:
        Which group of checks to run (see module docstring).
    checks:
        Override the default check registry (mainly for testing).
    verbose:
        Include WARNING details in the report output.

    Returns
    -------
    PreflightReport
    """
    _checks = list(checks) if checks is not None else _CHECKS
    groups = _groups_for_mode(mode)

    # Load runtime/secrets.env into env before checking (PR-3: local config authority)
    _load_runtime_secrets_into_env()

    findings: List[Finding] = []
    for check in _checks:
        if not any(g in groups for g in check.groups):
            continue
        present, hint = _is_set(check.var, check.allow_placeholder)
        findings.append(Finding(check=check, present=present, value_hint=hint))

    findings = _adjust_findings_for_token_policy(findings)
    findings = _augment_findings_with_compat_ws_policy(findings, groups)

    report = PreflightReport(findings=findings, mode=mode)

    if verbose or not report.ok:
        print(report.format(verbose=verbose), file=sys.stderr)

    if not dry_run and fail_fast and not report.ok:
        raise ConfigPreflightError(report)

    return report


# ---------------------------------------------------------------------------
# Convenience: check a single variable
# ---------------------------------------------------------------------------


def require_env(var: str, hint: str = "") -> str:
    """
    Return the value of *var* or raise a descriptive RuntimeError.

    Intended for inline use inside module-level code that needs a specific
    env var and wants a clear error message:

        secret = require_env(
            "SECRETVAULT_MASTER_KEY",
            "Generate with: python3 -c \\"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\\"",
        )
    """
    value = os.environ.get(var, "")
    if not value or value.lower().startswith(_PLACEHOLDER_PREFIXES):
        msg = f"Required environment variable '{var}' is not set."
        if hint:
            msg += f"\n  💡 {hint}"
        raise RuntimeError(msg)
    return value


# ---------------------------------------------------------------------------
# CLI entry-point
# ---------------------------------------------------------------------------


def _main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Galaxy pre-flight configuration check",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python -m core.config_preflight --mode all --dry-run
              python -m core.config_preflight --mode gateway
              python -m core.config_preflight --mode core --no-fail-fast
        """),
    )
    parser.add_argument(
        "--mode",
        default=os.environ.get("GALAXY_PREFLIGHT_MODE", "all"),
        choices=["auto", "all", "core", "gateway", "android", "ws", "vault"],
        help="Check group to validate (default: all)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=os.environ.get("GALAXY_PREFLIGHT_FAIL_FAST", "1").lower() in _FALSY,
        help="Print report but exit 0 even on CRITICAL failures",
    )
    parser.add_argument(
        "--no-fail-fast",
        dest="fail_fast",
        action="store_false",
        default=True,
        help="Return non-zero exit code but do not raise exception",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress WARNING details; only show CRITICAL issues",
    )

    args = parser.parse_args()

    try:
        report = run_preflight(
            dry_run=args.dry_run,
            fail_fast=False,  # we handle exit ourselves below
            mode=args.mode,
            verbose=not args.quiet,
        )
    except Exception as exc:  # pragma: no cover
        print(f"Unexpected error during preflight: {exc}", file=sys.stderr)
        sys.exit(2)

    if not report.ok and not args.dry_run:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":  # pragma: no cover
    _main()
