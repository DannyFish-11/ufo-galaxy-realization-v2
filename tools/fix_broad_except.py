#!/usr/bin/env python3
"""
Galaxy V2 — Broad Except 批量修复工具
========================================

自动扫描并修复 `except Exception: pass` 等静默吞异常的模式，
添加日志记录，使异常不再被静默忽略。

用法:
    python tools/fix_broad_except.py core/  # 扫描 core/ 目录
    python tools/fix_broad_except.py --fix core/openclawd.py  # 修复单个文件
    python tools/fix_broad_except.py --dry-run nodes/  # 只扫描不修改
"""

from __future__ import annotations

import argparse
import ast
import logging
import os
import re
import sys
from pathlib import Path

logger = logging.getLogger("fix_broad_except")

# Patterns to fix
PASS_PATTERN = re.compile(r'^(\s*)except\s+(\w+\s+as\s+\w+\s*:\s*)?pass\s*$', re.MULTILINE)
RETURN_NONE_PATTERN = re.compile(
    r'^(\s*)except\s+(\w+)(?:\s+as\s+(\w+))?:\s*\n\s*return\s+None\s*$',
    re.MULTILINE,
)

EXCLUDED_DIRS = {'__pycache__', '.git', 'node_modules', 'external', 'deploy', 'dist', 'build'}


def find_logger_name(source: str) -> str:
    """Detect logger variable name used in the file."""
    if '_logger' in source:
        return '_logger'
    if 'logger' in source:
        return 'logger'
    if '_LOGGER' in source:
        return '_LOGGER'
    if 'LOGGER' in source:
        return 'LOGGER'
    if 'logging' in source:
        return 'logging'
    return 'logger'


def get_indent(line: str) -> str:
    """Get leading whitespace."""
    return line[:len(line) - len(line.lstrip())]


def fix_file(filepath: str, dry_run: bool = False) -> int:
    """Fix broad except patterns in a single file. Returns number of fixes."""
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
    except Exception as exc:
        logger.error("Cannot read %s: %s", filepath, exc)
        return 0

    # Validate syntax before modifying
    try:
        ast.parse(source)
    except SyntaxError:
        logger.warning("Skipping %s: syntax error", filepath)
        return 0

    lines = source.split('\n')
    logger_name = find_logger_name(source)
    fixes = 0
    new_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Pattern 1: except Exception: pass
        if stripped == 'except Exception:' or stripped.startswith('except Exception as '):
            # Check if next line is pass
            indent = get_indent(line)
            if i + 1 < len(lines) and lines[i + 1].strip() == 'pass':
                # Generate a meaningful variable name
                if 'as' in stripped:
                    var_name = stripped.split('as')[1].strip().rstrip(':')
                else:
                    var_name = 'exc'
                    line = f"{indent}except Exception as {var_name}:"

                new_lines.append(line)
                new_lines.append(f"{indent}    {logger_name}.warning(\"Exception suppressed: %s\", {var_name})")
                i += 2  # Skip original pass line
                fixes += 1
                continue

        new_lines.append(line)
        i += 1

    if fixes > 0 and not dry_run:
        # Validate modified syntax
        new_source = '\n'.join(new_lines)
        try:
            ast.parse(new_source)
        except SyntaxError as exc:
            logger.error("Syntax error after fix in %s: %s", filepath, exc)
            return 0

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(new_source)
        logger.info("Fixed %d broad except(s) in %s", fixes, filepath)

    elif fixes > 0 and dry_run:
        logger.info("[DRY-RUN] Would fix %d broad except(s) in %s", fixes, filepath)

    return fixes


def scan_directory(directory: str, dry_run: bool = False) -> tuple[int, int]:
    """Scan directory for broad except patterns. Returns (files_scanned, fixes_made)."""
    files_scanned = 0
    total_fixes = 0

    for root, dirs, files in os.walk(directory):
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
        for f in files:
            if not f.endswith('.py'):
                continue
            filepath = os.path.join(root, f)
            if os.path.getsize(filepath) > 500 * 1024:
                continue
            files_scanned += 1
            fixes = fix_file(filepath, dry_run)
            total_fixes += fixes

    return files_scanned, total_fixes


def main():
    parser = argparse.ArgumentParser(description="Fix broad except patterns in Galaxy V2")
    parser.add_argument('path', help='File or directory to scan/fix')
    parser.add_argument('--dry-run', action='store_true', help='Scan without modifying')
    parser.add_argument('--verbose', '-v', action='store_true', help='Verbose output')
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format='%(levelname)s: %(message)s',
    )

    if not os.path.exists(args.path):
        logger.error("Path not found: %s", args.path)
        sys.exit(1)

    if os.path.isfile(args.path):
        fixes = fix_file(args.path, args.dry_run)
        print(f"\n{'Scanned' if args.dry_run else 'Fixed'} {fixes} broad except(s) in {args.path}")
    else:
        files, fixes = scan_directory(args.path, args.dry_run)
        action = "Would fix" if args.dry_run else "Fixed"
        print(f"\n{action} {fixes} broad except(s) across {files} files in {args.path}")


if __name__ == '__main__':
    main()
