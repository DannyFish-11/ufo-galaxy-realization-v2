#!/usr/bin/env python3
"""
Galaxy V2 — Async CancelledError 修复工具
===========================================

在 async 函数的 broad except 之前添加 CancelledError 保护：

    except asyncio.CancelledError:
        raise
    except Exception:
        ...

确保协程取消信号不被意外拦截。

用法：
    python tools/fix_cancelled_error.py --fix core/desktop_presence_runtime.py
    python tools/fix_cancelled_error.py --fix core/openclawd.py
    python tools/fix_cancelled_error.py --fix core/
"""

from __future__ import annotations

import argparse
import ast
import logging
import os
import sys

logger = logging.getLogger("fix_cancelled_error")

EXCLUDED_DIRS = {'__pycache__', '.git', 'node_modules', 'external', 'deploy', 'dist', 'build'}

def fix_file(filepath, dry_run=True):
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            source = f.read()
        lines = source.split('\n')
    except Exception:
        return 0

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0

    fixes = 0
    new_lines = []
    i = 0

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Find: except Exception: (in async context)
        if stripped.startswith('except Exception'):
            indent = line[:len(line) - len(line.lstrip())]
            inner_indent = indent + '    '

            # Check if this is inside an async function (heuristic: file has async def)
            if 'async def ' not in source:
                new_lines.append(line)
                i += 1
                continue

            # Check if CancelledError guard already exists
            if i > 0 and 'CancelledError' in lines[i-1]:
                new_lines.append(line)
                i += 1
                continue

            # Insert CancelledError guard before except Exception
            new_lines.append(f"{indent}except asyncio.CancelledError:")
            new_lines.append(f"{inner_indent}raise")
            new_lines.append(line)
            fixes += 1
            i += 1
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
        logger.info("Added %d CancelledError guards in %s", fixes, filepath)
    elif fixes > 0:
        logger.info("[DRY-RUN] Would add %d CancelledError guards in %s", fixes, filepath)

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
        print(f"{'Would add' if dry_run else 'Added'} {fixes} CancelledError guards")
    else:
        files, fixes = scan_directory(args.path, dry_run)
        print(f"{'Would add' if dry_run else 'Added'} {fixes} guards across {files} files")


if __name__ == '__main__':
    main()
