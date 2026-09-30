#!/usr/bin/env python3
"""按 config.yaml 已确认的档位预下载 L0/L1 模型(目标机器上运行)。

hardware.tier=unset 时拒绝执行(停点纪律:档位必须先经人类确认)。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.config import load_config  # noqa: E402


def main() -> int:
    cfg = load_config()
    tier = cfg.hardware.tier
    if tier == "unset":
        print("错误: hardware.tier=unset。先运行 scripts/detect_hardware.py,"
              "经人类确认后 --write <TIER>,再执行本脚本。", file=sys.stderr)
        return 2

    llm_model = cfg.llm.model_by_tier.get(tier)
    emb_model = cfg.embedder.model_by_tier.get(tier)
    if not llm_model or not emb_model:
        print(f"错误: config.yaml 中档位 {tier} 缺少 model_by_tier 映射", file=sys.stderr)
        return 2

    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        print("错误: 需要 huggingface_hub(uv sync --extra local-embed 会带上)", file=sys.stderr)
        return 2

    for repo in (llm_model, emb_model):
        print(f"下载 {repo} ...")
        path = snapshot_download(repo_id=repo)
        print(f"  -> {path}")
    print("完成。vLLM 与嵌入服务将从 HF 缓存加载。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
