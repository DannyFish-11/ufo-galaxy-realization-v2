import os
import sys

def test_mcp_alignment():
    print("=== UFO Galaxy 24 MCP Alignment Verification ===")
    
    # 1. 检查关键节点代码是否包含新功能
    print("\n[1] Checking Node 14 (YouTube/FFmpeg)...")
    with open("nodes/Node_14_FFmpeg/main.py", "r") as f:
        content = f.read()
        if "youtube_download" in content and "youtube_info" in content:
            print("✅ Node 14: YouTube tools integrated.")
        else:
            print("❌ Node 14: YouTube tools missing.")

    print("\n[2] Checking Node 13 (Arxiv/SQLite)...")
    with open("nodes/Node_13_SQLite/main.py", "r") as f:
        content = f.read()
        if "search_arxiv" in content and "download_paper" in content:
            print("✅ Node 13: Arxiv tools integrated.")
        else:
            print("❌ Node 13: Arxiv tools missing.")

    # 2. 检查 podman-compose.yml 端口映射
    print("\n[3] Checking podman-compose.yml Port Alignment...")
    expected_ports = {
        "mcp-oneapi": "3000",
        "mcp-tasker": "3002",
        "mcp-search": "3003",
        "mcp-youtube": "3004",
        "mcp-classifier": "3005",
        "mcp-monitoring": "19999",
        "mcp-qdrant": "6333",
        "mcp-ocr": "5001",
        "mcp-ui-analyzer": "4723",
        "mcp-filesystem": "8001",
        "mcp-github-tools": "8002",
        "mcp-memory": "8003",
        "mcp-notion": "8004",
        "mcp-playwright": "8005",
        "mcp-slack": "8006",
        "mcp-sqlite": "8007",
        "mcp-brave": "8008",
        "mcp-docker": "8009",
        "mcp-github-official": "8010",
        "mcp-thinking": "8011",
        "mcp-ffmpeg": "8012",
        "mcp-arxiv": "8013",
        "mcp-terminal": "8014",
        "mcp-weather": "8015"
    }
    
    with open("podman-compose.yml", "r") as f:
        compose_content = f.read()
        for service, port in expected_ports.items():
            if f"{service}:" in compose_content and f'"{port}:{port}"' in compose_content:
                print(f"✅ {service}: Port {port} aligned.")
            else:
                # 尝试不带引号的匹配
                if f"{service}:" in compose_content and f'{port}:{port}' in compose_content:
                    print(f"✅ {service}: Port {port} aligned.")
                else:
                    print(f"❌ {service}: Port {port} NOT aligned.")

    print("\n=== Verification Complete ===")

if __name__ == "__main__":
    test_mcp_alignment()
