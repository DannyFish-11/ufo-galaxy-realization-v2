"""
UFO Galaxy Cross-Device Collaboration Examples
跨设备协同示例
"""

import asyncio
import httpx
import json
from typing import Dict, Any

# ============================================================================
# Configuration
# ============================================================================

PC_AGENT_URL = "http://localhost:8004"  # Node 04 Enhanced Router
ANDROID_AGENT_URL = "http://192.168.1.100:8004"  # Android Sub-Agent (需要替换为实际 IP)
MQTT_BROKER = "mqtt://localhost:1883"

# ============================================================================
# Example 1: PC 触发安卓拍照
# ============================================================================

async def example_pc_trigger_android_camera():
    """
    PC 主 Agent 触发安卓子 Agent 打开相机拍照
    """
    print("=" * 60)
    print("Example 1: PC → Android Camera")
    print("=" * 60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # PC 发送任务到安卓
        response = await client.post(
            f"{ANDROID_AGENT_URL}/tools/invoke",
            json={
                "task_description": "打开相机并拍照",
                "context": {
                    "source": "pc_agent",
                    "save_path": "/sdcard/DCIM/ufo_photo.jpg"
                }
            }
        )
        
        result = response.json()
        print(f"Android Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        
        if result.get("success"):
            print("✅ 安卓相机已触发")
        else:
            print("❌ 触发失败")

# ============================================================================
# Example 2: 安卓触发 PC 工具
# ============================================================================

async def example_android_trigger_pc_tool():
    """
    安卓子 Agent 触发 PC 主 Agent 打开 OpenCode 编辑文件
    """
    print("=" * 60)
    print("Example 2: Android → PC OpenCode")
    print("=" * 60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 安卓发送任务到 PC
        response = await client.post(
            f"{PC_AGENT_URL}/tools/invoke",
            json={
                "task_description": "用 OpenCode 打开项目文件",
                "context": {
                    "source": "android_agent",
                    "file_path": "C:\\Projects\\ufo-galaxy\\README.md"
                }
            }
        )
        
        result = response.json()
        print(f"PC Response: {json.dumps(result, indent=2, ensure_ascii=False)}")
        
        if result.get("success"):
            print("✅ PC 工具已启动")
        else:
            print("❌ 启动失败")

# ============================================================================
# Example 3: 文件传输 (PC → Android)
# ============================================================================

async def example_file_transfer_pc_to_android():
    """
    从 PC 传输文件到安卓设备
    """
    print("=" * 60)
    print("Example 3: File Transfer PC → Android")
    print("=" * 60)
    
    # 这里需要通过 Node 33 (ADB) 或 Node 40 (SFTP) 实现
    async with httpx.AsyncClient(timeout=30.0) as client:
        # 调用 PC 的 Node 33
        response = await client.post(
            "http://localhost:8033/adb/push",
            json={
                "local_path": "C:\\temp\\test.txt",
                "remote_path": "/sdcard/Download/test.txt",
                "device_id": "your_device_serial"
            }
        )
        
        result = response.json()
        print(f"Transfer Result: {json.dumps(result, indent=2, ensure_ascii=False)}")

# ============================================================================
# Example 4: 协同任务流 (PC + Android)
# ============================================================================

async def example_collaborative_workflow():
    """
    协同任务流：
    1. PC 生成代码
    2. 传输到安卓
    3. 安卓在 Termux 中运行
    4. 结果返回 PC
    """
    print("=" * 60)
    print("Example 4: Collaborative Workflow")
    print("=" * 60)
    
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: PC 生成 Python 脚本
        print("\n[Step 1] PC 生成 Python 脚本...")
        code_gen_response = await client.post(
            f"{PC_AGENT_URL}/tools/invoke",
            json={
                "task_description": "生成一个简单的 Python 脚本，输出 Hello UFO Galaxy",
                "context": {"output_format": "python"}
            }
        )
        
        code_result = code_gen_response.json()
        print(f"代码生成结果: {code_result.get('ai_reasoning', {}).get('selected_tool')}")
        
        # Step 2: 传输到安卓
        print("\n[Step 2] 传输脚本到安卓...")
        # 这里简化处理，实际需要通过 ADB 或 MQTT
        script_content = "print('Hello UFO Galaxy')"
        
        # Step 3: 安卓在 Termux 中运行
        print("\n[Step 3] 安卓执行脚本...")
        exec_response = await client.post(
            f"{ANDROID_AGENT_URL}/tools/invoke",
            json={
                "task_description": "在 Termux 中运行 Python 脚本",
                "context": {
                    "script": script_content,
                    "interpreter": "python"
                }
            }
        )
        
        exec_result = exec_response.json()
        print(f"执行结果: {json.dumps(exec_result, indent=2, ensure_ascii=False)}")
        
        # Step 4: 结果已自动返回
        print("\n✅ 协同任务流完成")

# ============================================================================
# Example 5: 智能工具选择对比 (PC vs Android)
# ============================================================================

async def example_tool_selection_comparison():
    """
    对比 PC 和安卓在相同任务下的工具选择
    """
    print("=" * 60)
    print("Example 5: Tool Selection Comparison")
    print("=" * 60)
    
    task = "编辑一个文本文件"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        # PC 的选择
        print("\n[PC Agent] 处理任务...")
        pc_response = await client.post(
            f"{PC_AGENT_URL}/tools/invoke",
            json={"task_description": task}
        )
        pc_result = pc_response.json()
        pc_tool = pc_result.get("ai_reasoning", {}).get("selected_tool", "N/A")
        print(f"PC 选择: {pc_tool}")
        
        # 安卓的选择
        print("\n[Android Agent] 处理任务...")
        android_response = await client.post(
            f"{ANDROID_AGENT_URL}/tools/invoke",
            json={"task_description": task}
        )
        android_result = android_response.json()
        android_tool = android_result.get("selected_tool", "N/A")
        print(f"Android 选择: {android_tool}")
        
        print("\n对比:")
        print(f"  PC:      {pc_tool}")
        print(f"  Android: {android_tool}")

# ============================================================================
# Main
# ============================================================================

async def main():
    print("\n🛸 UFO Galaxy Cross-Device Collaboration Examples\n")
    
    examples = [
        ("PC 触发安卓拍照", example_pc_trigger_android_camera),
        ("安卓触发 PC 工具", example_android_trigger_pc_tool),
        ("文件传输 PC → Android", example_file_transfer_pc_to_android),
        ("协同任务流", example_collaborative_workflow),
        ("工具选择对比", example_tool_selection_comparison),
    ]
    
    print("可用示例:")
    for i, (name, _) in enumerate(examples, 1):
        print(f"  {i}. {name}")
    
    print("\n运行所有示例? (y/n): ", end="")
    choice = input().strip().lower()
    
    if choice == 'y':
        for name, func in examples:
            try:
                await func()
                await asyncio.sleep(2)
            except Exception as e:
                print(f"❌ {name} 失败: {e}")
    else:
        print("\n请选择要运行的示例 (1-5): ", end="")
        num = int(input().strip())
        if 1 <= num <= len(examples):
            name, func = examples[num - 1]
            try:
                await func()
            except Exception as e:
                print(f"❌ {name} 失败: {e}")

if __name__ == "__main__":
    asyncio.run(main())
