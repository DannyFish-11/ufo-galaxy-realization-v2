#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Galaxy — Port Registry Validation Script
=========================================

Validates:
  1. Port uniqueness across all nodes in unified_ports.yaml
  2. Every node directory in nodes/ is represented in unified_ports.yaml
  3. Every node in unified_ports.yaml is represented in deploy/compose/full.yml
  4. Infrastructure port conflicts with node ports are detected

Usage:
    python scripts/validate_ports.py              # full check, exit 1 on error
    python scripts/validate_ports.py --fix-hints  # also print suggested fixes
    python scripts/validate_ports.py --json       # machine-readable JSON output
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_yaml(path: Path) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError:
        print("[ERROR] PyYAML is required: pip install pyyaml", file=sys.stderr)
        sys.exit(2)
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _load_compose(path: Path) -> dict:
    """Load a docker-compose YAML file."""
    if not path.exists():
        return {}
    return _load_yaml(path)


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------


def extract_node_ports(ports_yaml: dict) -> Dict[str, int]:
    """Return {node_name: port} from unified_ports.yaml layers."""
    result: Dict[str, int] = {}
    for layer_val in ports_yaml.values():
        if not isinstance(layer_val, dict):
            continue
        nodes = layer_val.get("nodes", {})
        if not isinstance(nodes, dict):
            continue
        for node_name, node_cfg in nodes.items():
            if isinstance(node_cfg, dict) and "port" in node_cfg:
                result[node_name] = int(node_cfg["port"])
    return result


def extract_infra_ports(ports_yaml: dict) -> Dict[str, int]:
    """Return {service_name: port} from infrastructure section."""
    result: Dict[str, int] = {}
    infra = ports_yaml.get("infrastructure", {})
    services = infra.get("services", infra)
    if not isinstance(services, dict):
        return result
    for svc_name, svc_cfg in services.items():
        if isinstance(svc_cfg, dict) and "port" in svc_cfg:
            result[svc_name] = int(svc_cfg["port"])
    return result


def extract_surface_aliases(ports_yaml: dict) -> Dict[str, str]:
    """Return ``{service: the_service_it_shares_a_surface_with}``.

    ``same_surface_as`` 声明的是"这两条记的是**同一个服务面**，只是部署形态不同"，
    而不是"两个服务抢同一个端口"。目前唯一一条是 ``gateway → unified_launcher``：
    同一份 API 网关表面，桌面单进程由 ``launcher/services.py`` 起、容器由
    ``galaxy-gateway`` 起，任何一次部署只会有其中一条在跑。

    在此之前这件事只写在中文描述里，:func:`check_port_uniqueness` 看不见，于是把它
    判成 PORT CONFLICT —— 在 main 上长期红着，而每个来查的人都得把整条部署链重走
    一遍才能确认它不是缺陷。
    """
    out: Dict[str, str] = {}
    infra = ports_yaml.get("infrastructure", {})
    services = infra.get("services", infra)
    if not isinstance(services, dict):
        return out
    for svc_name, svc_cfg in services.items():
        if isinstance(svc_cfg, dict) and svc_cfg.get("same_surface_as"):
            out[svc_name] = str(svc_cfg["same_surface_as"])
    return out


def check_surface_aliases(
    infra_ports: Dict[str, int],
    aliases: Dict[str, str],
) -> List[str]:
    """声明了同一服务面的两条，端口**必须相等**。

    这才是把声明变成判据的那一半:不加这条，``same_surface_as`` 就只是一张让人
    闭嘴的豁免票。加上之后，将来谁把其中一个挪走而忘了另一个，立刻红 —— 比原来
    那条"端口不许重复"更严，因为它管的是**必须一致**。
    """
    errors: List[str] = []
    for svc, target in aliases.items():
        if target not in infra_ports:
            errors.append(f"SURFACE ALIAS: '{svc}' 声明 same_surface_as '{target}'，但后者不在基础设施端口表里")
            continue
        if infra_ports.get(svc) != infra_ports[target]:
            errors.append(
                f"SURFACE ALIAS MISMATCH: '{svc}' (port {infra_ports.get(svc)}) 声明与 "
                f"'{target}' (port {infra_ports[target]}) 是同一个服务面，端口却不一致 —— "
                "同一个面就该是同一个口，改一个必须同时改另一个"
            )
    return errors


def get_node_directories() -> List[str]:
    """Return list of Node_XX directory names under nodes/."""
    nodes_dir = PROJECT_ROOT / "nodes"
    if not nodes_dir.exists():
        return []
    return [
        d.name
        for d in sorted(nodes_dir.iterdir())
        if d.is_dir() and d.name.startswith("Node_") and (d / "main.py").exists()
    ]


def get_compose_services(compose: dict) -> Dict[str, int]:
    """Return {service_name: host_port} from a docker-compose file."""
    result: Dict[str, int] = {}
    for svc_name, svc_cfg in (compose.get("services") or {}).items():
        if not isinstance(svc_cfg, dict):
            continue
        for port_spec in svc_cfg.get("ports") or []:
            spec = str(port_spec)
            # Handle "8000:8000" or "0.0.0.0:8000:8000"
            parts = spec.split(":")
            try:
                result[svc_name] = int(parts[-2]) if len(parts) >= 2 else int(parts[0])
                break  # use first port mapping
            except (ValueError, IndexError):
                continue
    return result


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------


def check_port_uniqueness(
    node_ports: Dict[str, int],
    infra_ports: Dict[str, int],
    aliases: Optional[Dict[str, str]] = None,
) -> List[str]:
    """Detect duplicate port assignments.

    ``aliases``(见 :func:`extract_surface_aliases`)里声明过"同一个服务面"的那些
    条目跳过 —— 它们端口相同是**要求**，不是冲突。它们之间是否真的一致由
    :func:`check_surface_aliases` 单独判，所以这里跳过不会放过任何东西。
    """
    errors: List[str] = []
    seen: Dict[int, str] = {}
    aliased = set(aliases or {})

    all_ports = {**{f"node:{k}": v for k, v in node_ports.items()}, **{f"infra:{k}": v for k, v in infra_ports.items()}}

    for label, port in sorted(all_ports.items(), key=lambda x: x[1]):
        if label.startswith("infra:") and label.split(":", 1)[1] in aliased:
            continue
        if port in seen:
            errors.append(f"PORT CONFLICT: port {port} assigned to both '{seen[port]}' and '{label}'")
        else:
            seen[port] = label

    return errors


def check_nodes_in_yaml(
    node_dirs: List[str],
    node_ports: Dict[str, int],
) -> List[str]:
    """Detect node directories that are not listed in unified_ports.yaml."""
    errors: List[str] = []
    for node_name in node_dirs:
        if node_name not in node_ports:
            errors.append(
                f"MISSING IN YAML: '{node_name}' exists in nodes/ but has no " f"entry in config/unified_ports.yaml"
            )
    return errors


def check_nodes_in_compose(
    node_ports: Dict[str, int],
    compose_services: Dict[str, int],
    compose_path: str,
) -> List[str]:
    """Detect nodes that appear in unified_ports.yaml but not in the full compose."""
    errors: List[str] = []
    # Build a set of ports already declared in compose
    compose_port_set = set(compose_services.values())
    for node_name, port in node_ports.items():
        if port not in compose_port_set:
            errors.append(
                f"MISSING IN COMPOSE ({compose_path}): '{node_name}' (port {port}) "
                f"not found in any compose service port mapping"
            )
    return errors


def check_infra_vs_node_conflicts(
    node_ports: Dict[str, int],
    infra_ports: Dict[str, int],
) -> List[str]:
    """Report infra ports that collide with node ports (same port, different keys)."""
    errors: List[str] = []
    node_by_port: Dict[int, str] = {v: k for k, v in node_ports.items()}
    for svc_name, port in infra_ports.items():
        if port in node_by_port:
            errors.append(
                f"INFRA-NODE CONFLICT: infrastructure service '{svc_name}' (port {port}) "
                f"conflicts with node '{node_by_port[port]}'"
            )
    return errors


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Galaxy port registry and compose coverage.")
    parser.add_argument(
        "--fix-hints", action="store_true", help="Print suggested port assignments for missing entries."
    )
    parser.add_argument("--json", action="store_true", help="Output results as JSON.")
    parser.add_argument(
        "--compose",
        default="deploy/compose/full.yml",
        help="Docker Compose file to check against (default: deploy/compose/full.yml).",
    )
    args = parser.parse_args()

    ports_yaml_path = PROJECT_ROOT / "config" / "unified_ports.yaml"
    compose_path = PROJECT_ROOT / args.compose

    # ── Load data ──────────────────────────────────────────────
    if not ports_yaml_path.exists():
        print(f"[ERROR] {ports_yaml_path} not found", file=sys.stderr)
        return 2

    ports_yaml = _load_yaml(ports_yaml_path)
    node_ports = extract_node_ports(ports_yaml)
    infra_ports = extract_infra_ports(ports_yaml)
    node_dirs = get_node_directories()
    compose = _load_compose(compose_path)
    compose_services = get_compose_services(compose)

    # ── Run checks ─────────────────────────────────────────────
    all_errors: List[str] = []
    all_warnings: List[str] = []

    surface_aliases = extract_surface_aliases(ports_yaml)
    all_errors += check_port_uniqueness(node_ports, infra_ports, surface_aliases)
    all_errors += check_surface_aliases(infra_ports, surface_aliases)
    all_errors += check_nodes_in_yaml(node_dirs, node_ports)
    all_errors += check_infra_vs_node_conflicts(node_ports, infra_ports)

    if compose_services:
        all_errors += check_nodes_in_compose(node_ports, compose_services, args.compose)
    else:
        all_warnings.append(f"COMPOSE NOT FOUND or empty: '{compose_path}' — skipping compose coverage check")

    # ── Output ─────────────────────────────────────────────────
    summary = {
        "nodes_in_yaml": len(node_ports),
        "node_directories": len(node_dirs),
        "infra_services": len(infra_ports),
        "compose_services": len(compose_services),
        "errors": all_errors,
        "warnings": all_warnings,
        "status": "PASS" if not all_errors else "FAIL",
    }

    if args.json:
        print(json.dumps(summary, indent=2))
    else:
        print("=" * 70)
        print("Galaxy Port Registry Validation")
        print("=" * 70)
        print(f"  unified_ports.yaml nodes : {summary['nodes_in_yaml']}")
        print(f"  nodes/ directories       : {summary['node_directories']}")
        print(f"  infrastructure services  : {summary['infra_services']}")
        print(f"  compose services checked : {summary['compose_services']}")
        print()

        if all_warnings:
            print("WARNINGS:")
            for w in all_warnings:
                print(f"  ⚠  {w}")
            print()

        if all_errors:
            print(f"ERRORS ({len(all_errors)}):")
            for e in all_errors:
                print(f"  ✗  {e}")
            print()
        else:
            print("  ✓  No issues found.")
            print()

        if args.fix_hints and all_errors:
            _print_fix_hints(node_ports, infra_ports, node_dirs)

        print(f"Result: {summary['status']}")
        print("=" * 70)

    return 0 if not all_errors else 1


def _print_fix_hints(
    node_ports: Dict[str, int],
    infra_ports: Dict[str, int],
    node_dirs: List[str],
) -> None:
    """Print suggested port assignments for missing nodes."""
    used_ports = set(node_ports.values()) | set(infra_ports.values())
    missing = [d for d in node_dirs if d not in node_ports]
    if not missing:
        return

    print("FIX HINTS — suggested port assignments for missing nodes:")
    next_port = 8200  # start in the 8200-8298 range (8299 is assigned to unified_launcher)
    for node_name in missing:
        while next_port in used_ports:
            next_port += 1
        print(f"  {node_name}: {next_port}")
        used_ports.add(next_port)
        next_port += 1
    print()


if __name__ == "__main__":
    sys.exit(main())
