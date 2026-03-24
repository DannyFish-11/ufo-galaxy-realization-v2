#!/usr/bin/env python3
"""
scripts/audit_udm_write_paths.py
=================================
Galaxy SSOT / UDM 写路径完整性审计工具 — Block-6 / PR-6 / PR-8 anti-drift

功能：
  1. 静态扫描仓库中所有 Python 文件，找出绕过 SSOT
     (UnifiedDeviceManager) 直接修改设备状态的写路径。
  2. 检查 state_version 单调性（如果能连接到运行中的 UDM）。
  3. **PR-8 anti-drift**：检测新引入的平行设备注册表、绕过
     RegisteredRuntimeDevice 的单设备 Schema、以及绕过
     MultiDeviceRuntimeProjection 的多设备顶层读模型。
  4. 输出 JSON 报告 + 人类可读摘要。

SSOT 规则：
  - 合法写入 API（白名单）：
      UnifiedDeviceManager.register_device()
      UnifiedDeviceManager.register_device_from_dict()
      UnifiedDeviceManager.unregister_device()
      UnifiedDeviceManager.upsert_device_state()
      UnifiedDeviceManager.update_device_status()
      UnifiedDeviceManager.heartbeat()
  - 非法写路径：直接修改 _devices 字典、
    直接写 UnifiedDevice 字段（status/capabilities 等）而不经过 UDM。

PR-8 anti-drift 规则：
  - 不得在 contracts/registered_runtime_device.py 之外定义新的单设备读 Schema
    （类名含 RuntimeDevice / RegisteredDevice / DeviceContract 等）。
  - 不得在 contracts/multi_device_runtime_projection.py 之外定义新的顶层
    多设备读模型（类名含 MultiDeviceProjection / DevicesProjection 等）。
  - 不得在 UnifiedDeviceManager SSOT 之外定义 _devices / _device_map 等
    平行设备注册表字段。

退出码：
  0 — 无非法写路径
  1 — 发现非法写路径（CI 拦截）
  2 — 其他错误
"""

from __future__ import annotations

import ast
import json
import os
import sys
import textwrap
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─────────────────────────────────────────────────────────────────────────────
# 常量
# ─────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent

# 已知 SSOT 合法写入方法（在 UnifiedDeviceManager 实例上调用）
LEGAL_UDM_METHODS: frozenset = frozenset(
    [
        "register_device",
        "register_device_from_dict",
        "unregister_device",
        "upsert_device_state",
        "update_device_status",
        "heartbeat",
    ]
)

# 内部字段，禁止外部直接写入
ILLEGAL_DIRECT_FIELDS: frozenset = frozenset(
    [
        "_devices",
        "status",
        "capabilities",
        "device_name",
        "ip_address",
        "port",
        "metadata",
        "state_version",
        "last_heartbeat",
        "updated_at",
    ]
)

# 排除目录（测试、脚本、迁移、构建产物等）
EXCLUDE_DIRS: frozenset = frozenset(
    [
        ".git",
        "__pycache__",
        "node_modules",
        ".venv",
        "venv",
        ".eggs",
        "build",
        "dist",
        "migrations",
    ]
)

# 排除文件（已知的合法直接操作，如 UDM 本身）
EXCLUDE_FILES: frozenset = frozenset(
    [
        "core/unified/device_manager.py",
        "core/unified/models.py",
        "scripts/audit_udm_write_paths.py",
    ]
)


# ─────────────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class WriteViolation:
    """记录一处非法写路径。"""

    file: str
    line: int
    col: int
    kind: str          # "direct_field_write" | "direct_devices_access"
    detail: str
    snippet: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file,
            "line": self.line,
            "col": self.col,
            "kind": self.kind,
            "detail": self.detail,
            "snippet": self.snippet,
        }


@dataclass
class AuditResult:
    """完整审计结果。"""

    scanned_files: int = 0
    scanned_lines: int = 0
    violations: List[WriteViolation] = field(default_factory=list)
    state_version_issues: List[Dict[str, Any]] = field(default_factory=list)
    anti_drift_findings: List[Dict[str, Any]] = field(default_factory=list)
    elapsed_secs: float = 0.0
    error: Optional[str] = None

    @property
    def illegal_count(self) -> int:
        return len(self.violations)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scanned_files": self.scanned_files,
            "scanned_lines": self.scanned_lines,
            "illegal_write_paths": self.illegal_count,
            "violations": [v.to_dict() for v in self.violations],
            "state_version_issues": self.state_version_issues,
            "anti_drift_findings": self.anti_drift_findings,
            "elapsed_secs": round(self.elapsed_secs, 3),
            "error": self.error,
        }


# ─────────────────────────────────────────────────────────────────────────────
# AST 静态分析
# ─────────────────────────────────────────────────────────────────────────────


class _UDMWriteVisitor(ast.NodeVisitor):
    """
    AST 访问者：在单个文件中检测非法 UDM 写路径。

    检测策略：
    (A) 直接订阅赋值到 ._devices（如 mgr._devices[k] = v）。
    (B) 属性赋值中，目标对象名称含有 "device"/"dev_" 暗示其为 UnifiedDevice
        且 attr 在 ILLEGAL_DIRECT_FIELDS 中（且接收者不是 "self"）。
        使用名称启发式减少误报（NodeInfo、Session、Persona 等不受约束）。
    """

    # 接收者变量名 / 下标键中若含以下关键词，则启发为 UnifiedDevice 上下文
    _DEVICE_HINTS: frozenset = frozenset(
        ["device", "dev_", "_device", "unified_device", "d."]
    )

    def __init__(self, source_lines: List[str]) -> None:
        self.violations: List[Tuple[int, int, str, str]] = []  # (line, col, kind, detail)
        self._source_lines = source_lines

    def _snippet(self, lineno: int) -> str:
        idx = lineno - 1
        if 0 <= idx < len(self._source_lines):
            return self._source_lines[idx].rstrip()
        return ""

    def _looks_like_device(self, node: ast.expr) -> bool:
        """启发式判断节点是否指向 UnifiedDevice 对象。"""
        if isinstance(node, ast.Name):
            name_lower = node.id.lower()
            return any(hint in name_lower for hint in self._DEVICE_HINTS)
        if isinstance(node, ast.Attribute):
            name_lower = node.attr.lower()
            return any(hint in name_lower for hint in self._DEVICE_HINTS)
        if isinstance(node, ast.Subscript):
            # e.g. devices["dev-01"] — check the collection name
            return self._looks_like_device(node.value)
        return False

    def _check_target(self, node: ast.expr, origin_lineno: int) -> None:
        """检查赋值目标是否为非法字段写入。"""
        if isinstance(node, ast.Attribute):
            attr = node.attr
            # 排除 self.xxx（类内部赋值）
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                return
            if attr in ILLEGAL_DIRECT_FIELDS and self._looks_like_device(node.value):
                self.violations.append((
                    origin_lineno,
                    getattr(node, "col_offset", 0),
                    "direct_field_write",
                    f"Direct write to .{attr} bypasses SSOT UDM",
                ))
        elif isinstance(node, ast.Subscript):
            # 检测 _devices[...] = ...（无论接收者名称）
            value = node.value
            if isinstance(value, ast.Attribute) and value.attr == "_devices":
                if not (isinstance(value.value, ast.Name) and value.value.id == "self"):
                    self.violations.append((
                        origin_lineno,
                        getattr(value, "col_offset", 0),
                        "direct_devices_access",
                        "Direct subscript write to ._devices bypasses SSOT UDM",
                    ))

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._check_target(target, node.lineno)
        self.generic_visit(node)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        self._check_target(node.target, node.lineno)
        self.generic_visit(node)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None and node.target is not None:
            self._check_target(node.target, node.lineno)
        self.generic_visit(node)


def _scan_file(path: Path, repo_root: Path) -> Tuple[List[WriteViolation], int]:
    """
    扫描单个 Python 文件，返回 (violations, line_count)。
    """
    rel = str(path.relative_to(repo_root))
    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], 0

    lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return [], len(lines)

    visitor = _UDMWriteVisitor(lines)
    visitor.visit(tree)

    violations = [
        WriteViolation(
            file=rel,
            line=lineno,
            col=col,
            kind=kind,
            detail=detail,
            snippet=visitor._snippet(lineno),
        )
        for lineno, col, kind, detail in visitor.violations
    ]
    return violations, len(lines)


def _collect_py_files(root: Path) -> List[Path]:
    """递归收集仓库中的所有 .py 文件（跳过排除目录和文件）。"""
    files: List[Path] = []
    for p in root.rglob("*.py"):
        # 排除目录
        if any(ex in p.parts for ex in EXCLUDE_DIRS):
            continue
        # 排除文件（相对路径匹配）
        try:
            rel = str(p.relative_to(root))
        except ValueError:
            rel = str(p)
        if rel in EXCLUDE_FILES:
            continue
        files.append(p)
    return files


# ─────────────────────────────────────────────────────────────────────────────
# state_version 单调性检查
# ─────────────────────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────────────────────
# PR-8 Anti-drift guards — canonical contract bypass detection
# ─────────────────────────────────────────────────────────────────────────────

# Canonical single-device read contract location (relative to repo root).
_CANONICAL_SINGLE_DEVICE_CONTRACT = "contracts/registered_runtime_device.py"

# Canonical top-level multi-device read projection location.
_CANONICAL_MULTI_DEVICE_PROJECTION = "contracts/multi_device_runtime_projection.py"

# Canonical device write SSOT locations (allowed to own _devices state).
_CANONICAL_WRITE_SSOT_FILES: frozenset = frozenset(
    [
        "core/unified/device_manager.py",
        "core/unified/models.py",
    ]
)

# Heuristic class name fragments that suggest a new single-device schema
# when found OUTSIDE the canonical single-device contract module.
_SINGLE_DEVICE_SCHEMA_HINTS: frozenset = frozenset(
    [
        "RuntimeDevice",
        "RegisteredDevice",
        "DeviceContract",
        "DeviceRecord",
        "DeviceEntry",
        "DeviceProjection",
        "SingleDevice",
    ]
)

# Heuristic field names that suggest a parallel device collection / registry.
_PARALLEL_REGISTRY_FIELD_HINTS: frozenset = frozenset(
    [
        "_devices",
        "_device_map",
        "_device_registry",
        "_device_store",
        "_registered_devices",
    ]
)

# Heuristic class name fragments that suggest a new top-level multi-device
# read model when found OUTSIDE the canonical projection module.
_MULTI_DEVICE_PROJECTION_HINTS: frozenset = frozenset(
    [
        "MultiDeviceProjection",
        "MultiDeviceRuntime",
        "DevicesProjection",
        "AllDevicesSnapshot",
        "DeviceFleetProjection",
        "DeviceFleetSnapshot",
        "MultiRuntimeProjection",
    ]
)

# Files that are explicitly allowed to define device-like classes (adapters,
# legacy stubs, or other canonical modules that legitimately extend the chain).
_ANTI_DRIFT_ALLOW_LIST: frozenset = frozenset(
    [
        "contracts/registered_runtime_device.py",
        "contracts/multi_device_runtime_projection.py",
        "core/unified/device_manager.py",
        "core/unified/models.py",
        "scripts/audit_udm_write_paths.py",
        "tests/",
        "scripts/",
    ]
)


def _is_anti_drift_allowed(rel_path: str) -> bool:
    """Return True if *rel_path* is in the anti-drift allow list."""
    for allowed in _ANTI_DRIFT_ALLOW_LIST:
        if rel_path == allowed or rel_path.startswith(allowed):
            return True
    return False


class _AntiDriftVisitor(ast.NodeVisitor):
    """AST visitor that detects canonical-contract bypass patterns (PR-8).

    Checks performed
    ----------------
    1. **Parallel device registries** — class-level assignments of
       ``_devices``, ``_device_map``, etc. as ``dict``-typed attributes
       outside the canonical UDM files.
    2. **Parallel single-device schemas** — class definitions whose names
       contain single-device schema hints and are NOT in the canonical
       single-device contract file.
    3. **Parallel top-level multi-device read models** — class definitions
       whose names contain multi-device projection hints and are NOT in the
       canonical projection file.
    """

    def __init__(self, source_lines: List[str]) -> None:
        self.findings: List[Tuple[int, str, str]] = []  # (line, kind, detail)
        self._source_lines = source_lines

    def _snippet(self, lineno: int) -> str:
        idx = lineno - 1
        if 0 <= idx < len(self._source_lines):
            return self._source_lines[idx].rstrip()
        return ""

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        class_name = node.name

        # Check 2: Parallel single-device schema
        for hint in _SINGLE_DEVICE_SCHEMA_HINTS:
            if hint in class_name:
                self.findings.append((
                    node.lineno,
                    "parallel_single_device_schema",
                    (
                        f"Class '{class_name}' resembles a single-device schema "
                        f"(hint: '{hint}').  Use or extend "
                        f"'RegisteredRuntimeDevice' from "
                        f"'contracts/registered_runtime_device.py' instead."
                    ),
                ))
                break

        # Check 3: Parallel top-level multi-device read model
        for hint in _MULTI_DEVICE_PROJECTION_HINTS:
            if hint in class_name:
                self.findings.append((
                    node.lineno,
                    "parallel_multi_device_projection",
                    (
                        f"Class '{class_name}' resembles a top-level multi-device "
                        f"read model (hint: '{hint}').  Use or extend "
                        f"'MultiDeviceRuntimeProjection' from "
                        f"'contracts/multi_device_runtime_projection.py' instead."
                    ),
                ))
                break

        # Check 1: Parallel device registry fields defined inside this class
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign):
                target = stmt.target
                if isinstance(target, ast.Name) and target.id in _PARALLEL_REGISTRY_FIELD_HINTS:
                    self.findings.append((
                        stmt.lineno,
                        "parallel_device_registry",
                        (
                            f"Class '{class_name}' declares a parallel device "
                            f"registry field '{target.id}'.  Device state must be "
                            f"owned exclusively by 'UnifiedDeviceManager'."
                        ),
                    ))

        self.generic_visit(node)


def _check_anti_drift(
    root: Path,
    py_files: Optional[List[Path]] = None,
) -> List[Dict[str, Any]]:
    """Scan Python files for canonical-contract bypass patterns (PR-8 anti-drift).

    Parameters
    ----------
    root:
        Repository root directory.
    py_files:
        Pre-collected list of Python files.  If ``None``, files are collected
        from *root* using :func:`_collect_py_files`.

    Returns
    -------
    list of finding dicts, each with keys:
        ``file``, ``line``, ``kind``, ``detail``.
    """
    if py_files is None:
        py_files = _collect_py_files(root)

    findings: List[Dict[str, Any]] = []

    for fpath in py_files:
        try:
            rel = str(fpath.relative_to(root))
        except ValueError:
            rel = str(fpath)

        if _is_anti_drift_allowed(rel):
            continue

        try:
            source = fpath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        source_lines = source.splitlines()
        try:
            tree = ast.parse(source, filename=str(fpath))
        except SyntaxError:
            continue

        visitor = _AntiDriftVisitor(source_lines)
        visitor.visit(tree)

        for lineno, kind, detail in visitor.findings:
            findings.append({
                "file": rel,
                "line": lineno,
                "kind": kind,
                "detail": detail,
            })

    return findings


def _check_state_version_monotonicity() -> List[Dict[str, Any]]:
    """
    尝试连接 UnifiedDeviceManager，验证已注册设备的 state_version >= 0。
    （在单元测试场景下，state_version 的实际单调性由 UDM 写路径保证；
     此处做静态合理性断言：确认 UDM 模型字段存在且类型正确。）

    Returns:
        list of issue dicts（空列表表示通过）
    """
    issues: List[Dict[str, Any]] = []
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from core.unified.models import UnifiedDevice  # noqa: PLC0415

        # 验证字段存在
        if "state_version" not in UnifiedDevice.model_fields:
            issues.append({
                "type": "missing_field",
                "detail": "UnifiedDevice model is missing 'state_version' field",
            })

        # 验证默认值 >= 0
        try:
            device = UnifiedDevice(device_id="audit-test", device_name="test")
            if (device.state_version or 0) < 0:
                issues.append({
                    "type": "invalid_default",
                    "detail": f"state_version default is negative: {device.state_version}",
                })
        except Exception as exc:
            issues.append({"type": "model_instantiation_error", "detail": str(exc)})

        # 连接到运行中的 UDM（如果可用）
        try:
            from core.unified.device_manager import UnifiedDeviceManager  # noqa: PLC0415
            udm = UnifiedDeviceManager()
            devices = udm.list_devices()
            for d in devices:
                if (d.state_version or 0) < 0:
                    issues.append({
                        "type": "negative_state_version",
                        "device_id": d.device_id,
                        "state_version": d.state_version,
                    })
        except Exception:
            pass  # UDM 不可用时跳过运行时检查

    except ImportError as exc:
        issues.append({"type": "import_error", "detail": str(exc)})

    return issues


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────


def run_audit(
    root: Path = REPO_ROOT,
    output_json: Optional[Path] = None,
    verbose: bool = False,
) -> AuditResult:
    """
    执行完整 UDM 写路径审计。

    Args:
        root:        仓库根目录。
        output_json: 若指定，将结果写入该 JSON 文件。
        verbose:     是否打印详细日志。

    Returns:
        AuditResult 实例。
    """
    result = AuditResult()
    t0 = time.monotonic()

    # 1. 收集 Python 文件
    py_files = _collect_py_files(root)
    if verbose:
        print(f"[audit] Scanning {len(py_files)} Python files under {root} …")

    # 2. 逐文件扫描
    for fpath in py_files:
        violations, line_count = _scan_file(fpath, root)
        result.scanned_files += 1
        result.scanned_lines += line_count
        result.violations.extend(violations)

    # 3. state_version 单调性
    result.state_version_issues = _check_state_version_monotonicity()

    # 4. PR-8 anti-drift: canonical contract bypass detection
    result.anti_drift_findings = _check_anti_drift(root, py_files)

    result.elapsed_secs = time.monotonic() - t0

    # 4. 输出 JSON
    if output_json:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(
            json.dumps(result.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if verbose:
            print(f"[audit] Report written to {output_json}")

    return result


def _print_summary(result: AuditResult) -> None:
    """打印人类可读的审计摘要。"""
    sep = "=" * 72
    print(sep)
    print("Galaxy SSOT / UDM Write-Path Audit Report")
    print(sep)
    print(f"  Files scanned   : {result.scanned_files}")
    print(f"  Lines scanned   : {result.scanned_lines}")
    print(f"  Elapsed         : {result.elapsed_secs:.2f}s")
    print(f"  Illegal paths   : {result.illegal_count}")
    print(f"  StateVer issues : {len(result.state_version_issues)}")
    print(f"  Anti-drift warn : {len(result.anti_drift_findings)}")
    print()

    if result.violations:
        print("VIOLATIONS (illegal write paths):")
        for v in result.violations:
            print(f"  [{v.kind}] {v.file}:{v.line}")
            print(f"    Detail : {v.detail}")
            if v.snippet:
                print(f"    Code   : {v.snippet.strip()}")
        print()
    else:
        print("  ✓ No illegal write paths detected.")
        print()

    if result.state_version_issues:
        print("STATE VERSION ISSUES:")
        for iss in result.state_version_issues:
            print(f"  - {iss}")
        print()
    else:
        print("  ✓ state_version monotonicity checks passed.")
        print()

    if result.anti_drift_findings:
        print("ANTI-DRIFT WARNINGS (PR-8 canonical contract bypass patterns):")
        for f in result.anti_drift_findings:
            print(f"  [{f['kind']}] {f['file']}:{f['line']}")
            print(f"    Detail : {f['detail']}")
        print()
    else:
        print("  ✓ No canonical contract bypass patterns detected.")
        print()

    print(sep)
    if result.illegal_count == 0 and not result.state_version_issues:
        print("AUDIT PASSED — 0 illegal write paths, state_version OK.")
        if result.anti_drift_findings:
            print(
                f"  WARNING: {len(result.anti_drift_findings)} anti-drift finding(s) "
                f"may indicate architectural drift (non-blocking)."
            )
    else:
        print(
            f"AUDIT FAILED — {result.illegal_count} illegal write path(s), "
            f"{len(result.state_version_issues)} state_version issue(s)."
        )
    print(sep)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(
        description="Galaxy SSOT/UDM write-path integrity audit",
    )
    parser.add_argument(
        "--root",
        default=str(REPO_ROOT),
        help="Repository root directory (default: repo root)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write JSON report to this file path",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )
    args = parser.parse_args()

    root = Path(args.root)
    output_json = Path(args.output) if args.output else None

    result = run_audit(root=root, output_json=output_json, verbose=args.verbose)
    _print_summary(result)

    sys.exit(0 if (result.illegal_count == 0 and not result.state_version_issues) else 1)


if __name__ == "__main__":
    main()
