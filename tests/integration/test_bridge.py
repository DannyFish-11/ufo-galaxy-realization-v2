# ---------------------------------------------------------------------------
# CANONICAL LOCATION: tests/integration/test_bridge.py
# Relocated from enhancements/bridges/test_bridge.py
#
# NOTE: This is a manual bridge compatibility test.  It is marked ``manual``
# so that it is skipped in standard CI runs.  Run explicitly with:
#   pytest tests/integration/test_bridge.py -m manual
# ---------------------------------------------------------------------------
"""
Galaxy Bridge 兼容性测试

测试桥接器的基本功能，无需实际运行两个系统
"""

import pytest

import asyncio
import sys
from pathlib import Path

# The bridge module lives in enhancements/bridges/
_BRIDGES_DIR = (
    Path(__file__).resolve().parent.parent.parent / "enhancements" / "bridges"
)
sys.path.insert(0, str(_BRIDGES_DIR))

try:
    from galaxy_bridge import GalaxyBridge
except ImportError as _e:
    pytest.skip(f"galaxy_bridge module not available: {_e}", allow_module_level=True)

async def test_initialization():
    """测试初始化"""
    print("测试 1: 初始化桥接器")
    print("-" * 80)
    
    bridge = GalaxyBridge()
    await bridge.initialize()
    
    print(f"✅ 初始化完成")
    print(f"   galaxy 可用: {bridge.galaxy_available}")
    print(f"   微软 UFO 可用: {bridge.microsoft_ufo_available}")
    
    return bridge

async def test_error_handling(bridge):
    """测试错误处理"""
    print("\n测试 2: 错误处理（系统不可用时）")
    print("-" * 80)
    
    # 强制设置为不可用
    bridge.galaxy_available = False
    bridge.microsoft_ufo_available = False
    
    result = await bridge.unified_vision_analysis(
        image_path="/test/image.png",
        query="测试查询"
    )
    
    if "error" in result:
        print(f"✅ 错误处理正常: {result['error']}")
    else:
        print(f"❌ 错误处理失败")

async def main():
    """运行所有测试"""
    print("=" * 80)
    print("Galaxy Bridge 兼容性测试")
    print("=" * 80)
    
    bridge = await test_initialization()
    await test_error_handling(bridge)
    
    print("\n" + "=" * 80)
    print("测试完成")
    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())


# ---------------------------------------------------------------------------
# Pytest-compatible wrapper (skipped in standard CI; run with -m manual)
# ---------------------------------------------------------------------------

@pytest.mark.manual
@pytest.mark.skip(reason="Requires enhancements/bridges/galaxy_bridge module — run manually")
def test_bridge_compatibility_suite():
    """Wraps the manual Galaxy Bridge compatibility test for discoverability."""
    import asyncio
    asyncio.run(main())
