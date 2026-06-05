#!/usr/bin/env python3
"""
Galaxy 本地模型后台下载脚本
================================
支持 MobileVLM 和 SeeClick 模型的后台下载。

用法:
    # 下载所有缺失模型
    python download_models.py

    # 下载指定模型
    python download_models.py --model mobilevlm
    python download_models.py --model seeclick

    # 查看模型状态
    python download_models.py --status

    # 指定下载目录
    python download_models.py --dir ./models
"""

import argparse
import hashlib
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional, Dict

# Force UTF-8 on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    os.environ["PYTHONIOENCODING"] = "utf-8:replace"

# Setup logging with UTF-8 support
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ModelDownload")


# ── Model Configuration ──

MODELS = {
    "mobilevlm": {
        "name": "MobileVLM V2-1.7B (GGUF Q4)",
        "description": "On-device vision-language model for image understanding",
        "url": "https://huggingface.co/ZiangWu/MobileVLM_V2-1.7B-GGUF/resolve/main/ggml-model-q4_k.gguf",
        "filename": "ggml-model-q4_k.gguf",
        "sha256": "15d4bd09293404831902c23dd898aa2cc7b4b223b6c39a64e330601ef72d99db",
        "size_mb": 1.0,
    },
    "seeclick": {
        "name": "SeeClick (NCNN param)",
        "description": "GUI element detection model parameter file",
        "url": "https://huggingface.co/cckevinn/SeeClick/resolve/main/ncnn/seeclick.ncnn.param",
        "filename": "seeclick.ncnn.param",
        "sha256": None,
        "size_mb": 0.003,
    },
    "seeclick_bin": {
        "name": "SeeClick (NCNN bin)",
        "description": "GUI element detection model weights",
        "url": "https://huggingface.co/cckevinn/SeeClick/resolve/main/ncnn/seeclick.ncnn.bin",
        "filename": "seeclick.ncnn.bin",
        "sha256": None,
        "size_mb": 8.5,
    },
}

CHECKSUMS_FILE = ".checksums.json"


# ── Utility Functions ──

def sha256_file(filepath: Path) -> str:
    """Compute SHA-256 hash of a file."""
    digest = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_checksums(models_dir: Path) -> Dict[str, str]:
    """Load persisted checksums."""
    checksums_file = models_dir / CHECKSUMS_FILE
    if not checksums_file.exists():
        return {}
    try:
        with open(checksums_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_checksums(models_dir: Path, checksums: Dict[str, str]):
    """Save checksums to disk."""
    checksums_file = models_dir / CHECKSUMS_FILE
    try:
        with open(checksums_file, "w", encoding="utf-8") as f:
            json.dump(checksums, f, indent=2)
    except Exception as e:
        logger.warning("Failed to save checksums: %s", e)


def format_size(bytes_size: int) -> str:
    """Format byte size to human readable."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} TB"


def download_file(url: str, dest: Path, expected_sha256: Optional[str] = None) -> bool:
    """Download a file with progress reporting."""
    try:
        import urllib.request
        import urllib.error

        logger.info("Downloading: %s", url)
        logger.info("Destination: %s", dest)

        req = urllib.request.Request(url, headers={
            "User-Agent": "Galaxy-ModelDownloader/1.0"
        })

        with urllib.request.urlopen(req, timeout=120) as response:
            total_size = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            last_report = 0

            with open(dest, "wb") as f:
                while True:
                    chunk = response.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Report progress every 5%
                    if total_size > 0:
                        pct = int(downloaded * 100 / total_size)
                        if pct >= last_report + 5:
                            logger.info("  Progress: %d%% (%s / %s)",
                                pct, format_size(downloaded), format_size(total_size))
                            last_report = pct

        logger.info("Download complete: %s (%s)", dest, format_size(downloaded))

        # Verify checksum
        if expected_sha256:
            actual_sha256 = sha256_file(dest)
            if actual_sha256.lower() != expected_sha256.lower():
                logger.error("Checksum mismatch!")
                logger.error("  Expected: %s", expected_sha256)
                logger.error("  Actual:   %s", actual_sha256)
                dest.unlink(missing_ok=True)
                return False
            logger.info("Checksum verified: OK")

        return True

    except urllib.error.HTTPError as e:
        logger.error("HTTP %d: %s", e.code, url)
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False
    except Exception as e:
        logger.error("Download failed: %s", e)
        if dest.exists():
            dest.unlink(missing_ok=True)
        return False


# ── Main Functions ──

def check_model_status(models_dir: Path) -> Dict[str, dict]:
    """Check status of all models."""
    checksums = load_checksums(models_dir)
    status = {}

    for model_id, config in MODELS.items():
        filepath = models_dir / config["filename"]
        if filepath.exists():
            file_size = filepath.stat().st_size
            sha256 = sha256_file(filepath)
            expected = config["sha256"] or checksums.get(model_id)
            verified = (expected is None) or (sha256.lower() == expected.lower())
            status[model_id] = {
                "name": config["name"],
                "status": "VERIFIED" if verified else "CORRUPTED",
                "size": format_size(file_size),
                "path": str(filepath),
            }
        else:
            status[model_id] = {
                "name": config["name"],
                "status": "MISSING",
                "size": f"~{config['size_mb']} MB (download)",
                "path": None,
            }

    return status


def print_status(models_dir: Path):
    """Print model status table."""
    print("\n" + "=" * 60)
    print("Galaxy 本地模型状态")
    print("=" * 60)

    status = check_model_status(models_dir)
    for model_id, info in status.items():
        icon = "✅" if info["status"] == "VERIFIED" else "❌" if info["status"] == "MISSING" else "⚠️"
        print(f"\n  {icon} {info['name']} [{model_id}]")
        print(f"     状态: {info['status']}")
        print(f"     大小: {info['size']}")
        if info["path"]:
            print(f"     路径: {info['path']}")

    print("\n" + "=" * 60)
    missing = sum(1 for s in status.values() if s["status"] == "MISSING")
    ready = sum(1 for s in status.values() if s["status"] == "VERIFIED")
    print(f"总计: {ready}/{len(status)} 模型就绪, {missing} 缺失")
    print("=" * 60 + "\n")


def download_model(model_id: str, models_dir: Path) -> bool:
    """Download a specific model."""
    if model_id not in MODELS:
        logger.error("Unknown model: %s", model_id)
        logger.info("Available: %s", ", ".join(MODELS.keys()))
        return False

    config = MODELS[model_id]
    filepath = models_dir / config["filename"]
    checksums = load_checksums(models_dir)

    # Check if already exists
    if filepath.exists():
        if config["sha256"]:
            actual = sha256_file(filepath)
            if actual.lower() == config["sha256"].lower():
                logger.info("✅ %s already downloaded and verified", config["name"])
                return True
        elif checksums.get(model_id):
            actual = sha256_file(filepath)
            if actual.lower() == checksums[model_id].lower():
                logger.info("✅ %s already downloaded and verified", config["name"])
                return True
        logger.info("⚠️ %s exists but checksum mismatch, re-downloading", config["name"])
        filepath.unlink()

    # Download
    models_dir.mkdir(parents=True, exist_ok=True)
    logger.info("📥 Starting download: %s", config["name"])
    logger.info("   Description: %s", config["description"])

    if download_file(config["url"], filepath, config["sha256"]):
        # Persist checksum for models without hardcoded SHA256
        if not config["sha256"]:
            actual = sha256_file(filepath)
            checksums[model_id] = actual
            save_checksums(models_dir, checksums)
            logger.info("  Persisted checksum for future verification")
        logger.info("✅ %s download complete!\n", config["name"])
        return True
    else:
        logger.error("❌ %s download failed\n", config["name"])
        return False


def download_all(models_dir: Path) -> bool:
    """Download all missing models."""
    print("\n🚀 Galaxy 本地模型批量下载")
    print("=" * 60)

    status = check_model_status(models_dir)
    missing = [mid for mid, s in status.items() if s["status"] == "MISSING"]

    if not missing:
        print("✅ 所有模型已就绪，无需下载！\n")
        return True

    print(f"发现 {len(missing)} 个缺失模型:\n")
    for mid in missing:
        print(f"  • {MODELS[mid]['name']} ({MODELS[mid]['size_mb']} MB)")

    print(f"\n下载目录: {models_dir}")
    confirm = input("\n开始下载? [Y/n]: ").strip().lower()
    if confirm and confirm not in ("y", "yes"):
        print("已取消")
        return False

    print()
    results = {}
    for model_id in missing:
        results[model_id] = download_model(model_id, models_dir)
        time.sleep(1)  # Brief pause between downloads

    print("\n" + "=" * 60)
    success = sum(1 for v in results.values() if v)
    print(f"下载完成: {success}/{len(results)} 成功")
    print("=" * 60 + "\n")

    return all(results.values())


def interactive_menu(models_dir: Path):
    """Interactive model download menu."""
    while True:
        print("\n" + "=" * 50)
        print("Galaxy 本地模型管理")
        print("=" * 50)
        print("  1. 查看模型状态")
        print("  2. 下载所有缺失模型")
        print("  3. 下载 MobileVLM")
        print("  4. 下载 SeeClick")
        print("  5. 退出")
        print("=" * 50)

        choice = input("选择 [1-5]: ").strip()

        if choice == "1":
            print_status(models_dir)
        elif choice == "2":
            download_all(models_dir)
        elif choice == "3":
            download_model("mobilevlm", models_dir)
            download_model("seeclick", models_dir)
            download_model("seeclick_bin", models_dir)
        elif choice == "4":
            download_model("seeclick", models_dir)
            download_model("seeclick_bin", models_dir)
        elif choice == "5":
            print("再见!")
            break
        else:
            print("无效选择，请重试")


# ── CLI Entry Point ──

def main():
    parser = argparse.ArgumentParser(
        description="Galaxy 本地模型后台下载工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python download_models.py                    # 交互式菜单
  python download_models.py --status           # 查看模型状态
  python download_models.py --all              # 下载所有缺失模型
  python download_models.py --model mobilevlm  # 下载指定模型
  python download_models.py --dir ./my_models  # 指定下载目录
        """
    )
    parser.add_argument("--model", choices=list(MODELS.keys()),
                        help="下载指定模型 (mobilevlm/seeclick/seeclick_bin)")
    parser.add_argument("--all", action="store_true",
                        help="下载所有缺失模型")
    parser.add_argument("--status", action="store_true",
                        help="查看模型状态")
    parser.add_argument("--dir", default=str(Path.home() / ".galaxy" / "models"),
                        help="模型下载目录 (默认: ~/.galaxy/models)")
    parser.add_argument("--yes", "-y", action="store_true",
                        help="自动确认，不提示")

    args = parser.parse_args()
    models_dir = Path(args.dir)

    if args.status:
        print_status(models_dir)
    elif args.model:
        download_model(args.model, models_dir)
    elif args.all:
        if args.yes:
            download_all(models_dir)
        else:
            interactive_menu(models_dir)
    else:
        # No args - show status + interactive menu
        print_status(models_dir)
        interactive_menu(models_dir)


if __name__ == "__main__":
    main()
