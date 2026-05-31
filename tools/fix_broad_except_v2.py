#!/usr/bin/env python3
"""
Galaxy V2 — Broad Except 批量修复工具 v2
============================================

覆盖模式:
  1. except Exception: pass → except Exception as exc: logger.debug(...)
  2. except Exception: x = default → 同上，保留 fallback 赋值
  3. except Exception as e: pass → 保留变量，添加日志

用法:
    python tools/fix_broad_except_v2.py --fix core/
    python tools/fix_broad_except_v2.py --dry-run core/openclawd.py
"""

from __future__ import annotations

import argparse
import ast
import logging
import os
import re
import sys

logger = logging.getLogger("fix_broad_except_v2")

EXCLUDED_DIRS = {'__pycache__', '.git', 'node_modules', 'external', 'deploy', 'dist', 'build'}

# Regex patterns
RE_EXCEPT_PASS = re.compile(r'^(\s*)except\s+Exception\s*:\s*$', re.MULTILINE)
RE_EXCEPT_AS_PASS = re.compile(r'^(\s*)except\s+Exception\s+as\s+(\w+)\s*:\s*$', re.MULTILINE)


def find_logger_name(lines):
    """Detect logger variable name."""
    source = '\n'.join(lines)
    if '_logger' in source:
        return '_logger'
    if 'logger' in source:
        return 'logger'
    if '_LOGGER' in source:
        return '_LOGGER'
    if 'LOGGER' in source:
        return 'LOGGER'
    return 'logger'


def fix_file(filepath, dry_run=True):
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
        lines = source.split('\n')
    except Exception:
        return 0

    try:
        ast.parse(source)
    except SyntaxError:
        return 0

    logger_name = find_logger_name(lines)
    new_lines = []
    i = 0
    fixes = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Pattern 1: except Exception: (with variable or without)
        if stripped.startswith('except Exception'):
            indent = line[:len(line) - len(line.lstrip())]
            base_indent = indent + '    '

            # Check if 'as var' exists
            var_match = re.match(r'except\s+Exception\s+as\s+(\w+)\s*:', stripped)
            if var_match:
                var_name = var_match.group(1)
            else:
                var_name = 'exc'
                # Need to add 'as var_name'
                line = f"{indent}except Exception as {var_name}:"

            if i + 1 < len(lines):
                next_line = lines[i + 1]
                next_stripped = next_line.strip()
                next_indent = next_line[:len(next_line) - len(next_line.lstrip())]

                # Sub-pattern 1a: pass
                if next_stripped == 'pass':
                    new_lines.append(line)
                    new_lines.append(f"{base_indent}{logger_name}.debug(\"Suppressed: %s\", {var_name})")
                    i += 2
                    fixes += 1
                    continue

                # Sub-pattern 1b: single-line fallback assignment (no inner try/return/if)
                if (next_stripped and
                    not next_stripped.startswith('#') and
                    not next_stripped.startswith('"""') and
                    not next_stripped.startswith("'''") and
                    not next_stripped.startswith('try:') and
                    not next_stripped.startswith('if ') and
                    not next_stripped.startswith('for ') and
                    not next_stripped.startswith('while ') and
                    not next_stripped.startswith('return') and
                    not next_stripped.startswith('raise') and
                    not next_stripped.startswith('logger') and
                    not next_stripped.startswith('print') and
                    not next_stripped.startswith('emit') and
                    not next_stripped.startswith('pass') and
                    '=' in next_stripped and
                    len(next_stripped) < 120):

                    new_lines.append(line)
                    new_lines.append(f"{base_indent}{logger_name}.debug(\"Fallback triggered: %s\", {var_name})")
                    new_lines.append(next_line)
                    i += 2
                    fixes += 1
                    continue

        new_lines.append(line)
        i += 1

    if fixes > 0 and not dry_run:
        new_source = '\n'.join(new_lines)
        try:
            ast.parse(new_source)
        except SyntaxError as exc:
            logger.error("Syntax error in %s: %s", filepath, exc)
            return 0
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_source)
        logger.info("Fixed %d in %s", fixes, filepath)
    elif fixes > 0:
        logger.info("[DRY-RUN] Would fix %d in %s", fixes, filepath)

    return fixes


def scan_directory(directory, dry_run=True):
    total_files = 0
    total_fixes = 0
    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for f in files:
            if f.endswith('.py'):
                fp = os.path.join(root, f)
                if os.path.getsize(fp) < 500 * 1024:
                    total_files += 1
                    total_fixes += fix_file(fp, dry_run)
    return total_files, total_fixes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('path')
    parser.add_argument('--fix', action='store_true')
    parser.add_argument('-v', action='store_true')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.v else logging.INFO,
        format='%(levelname)s: %(message)s',
    )

    if not os.path.exists(args.path):
        print(f"Not found: {args.path}")
        sys.exit(1)

    dry_run = not args.fix
    if os.path.isfile(args.path):
        fixes = fix_file(args.path, dry_run)
        print(f"{'Would fix' if dry_run else 'Fixed'} {fixes} in {args.path}")
    else:
        files, fixes = scan_directory(args.path, dry_run)
        print(f"{'Would fix' if dry_run else 'Fixed'} {fixes} across {files} files")


if __name__ == '__main__':
    main()
