#!/usr/bin/env python3
"""
UFO Galaxy V2 - 系统验证脚本
验证所有核心功能是否正常工作
"""

import sys
import os
import asyncio

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def print_header(title):
    print(f"\n{'='*50}")
    print(f"  {title}")
    print(f"{'='*50}\n")

def print_result(name, success, error=None):
    if success:
        print(f"  ✅ {name}")
    else:
        print(f"  ❌ {name}")
        if error:
            print(f"     错误: {error}")

def test_imports():
    """测试核心模块导入"""
    print_header("1. 核心模块导入测试")
    
    tests = [
        ("core.node_registry", "NodeRegistry"),
        ("core.node_protocol", "Message"),
        ("core.node_communication", "UniversalCommunicator"),
        ("core.cache", "CacheManager"),
        ("core.monitoring", "MonitoringManager"),
        ("core.command_router", "CommandRouter"),
        ("core.safe_eval", "SafeEval"),
        ("core.secure_config", "SecureConfig"),
        ("core.capability_manager", "CapabilityManager"),
    ]
    
    errors = []
    for module_name, class_name in tests:
        try:
            module = __import__(module_name, fromlist=[class_name])
            getattr(module, class_name)
            print_result(f"{module_name}.{class_name}", True)
        except Exception as e:
            errors.append((module_name, str(e)))
            print_result(f"{module_name}.{class_name}", False, str(e))
    
    return len(errors) == 0

def test_nodes():
    """测试关键节点"""
    print_header("2. 关键节点测试")
    
    nodes = [
        ("nodes.Node_01_OneAPI.main", "app"),
        ("nodes.Node_04_Router.main", "GlobalRouter"),
    ]
    
    errors = []
    for module_name, attr in nodes:
        try:
            module = __import__(module_name, fromlist=[attr])
            getattr(module, attr)
            print_result(f"{module_name}.{attr}", True)
        except Exception as e:
            errors.append((module_name, str(e)))
            print_result(f"{module_name}.{attr}", False, str(e))
    
    return len(errors) == 0

async def test_async_components():
    """测试异步组件"""
    print_header("3. 异步组件测试")
    
    errors = []
    
    # 测试缓存
    try:
        from core.cache import get_cache
        cache = await get_cache()
        print_result(f"Cache (backend: {cache.backend_type})", True)
    except Exception as e:
        errors.append(("Cache", str(e)))
        print_result("Cache", False, str(e))
    
    # 测试监控
    try:
        from core.monitoring import get_monitoring_manager
        monitoring = get_monitoring_manager()
        print_result("MonitoringManager", True)
    except Exception as e:
        errors.append(("Monitoring", str(e)))
        print_result("MonitoringManager", False, str(e))
    
    # 测试配置
    try:
        from core.secure_config import get_config
        config = get_config()
        print_result("SecureConfig", True)
    except Exception as e:
        errors.append(("SecureConfig", str(e)))
        print_result("SecureConfig", False, str(e))
    
    return len(errors) == 0

def test_safe_eval():
    """测试安全表达式求值"""
    print_header("4. 安全表达式求值测试")
    
    try:
        from core.safe_eval import SafeEval
        
        evaluator = SafeEval()
        
        # 测试基本运算
        result = evaluator.eval("1 + 2 * 3")
        assert result == 7, f"Expected 7, got {result}"
        print_result("基本运算 (1 + 2 * 3 = 7)", True)
        
        # 测试变量
        result = evaluator.eval("x + y", {"x": 10, "y": 20})
        assert result == 30, f"Expected 30, got {result}"
        print_result("变量运算 (x + y = 30)", True)
        
        # 测试比较
        result = evaluator.eval("x > 5", {"x": 10})
        assert result == True, f"Expected True, got {result}"
        print_result("比较运算 (x > 5)", True)
        
        return True
    except Exception as e:
        print_result("SafeEval", False, str(e))
        return False

def test_config():
    """测试配置"""
    print_header("5. 配置测试")
    
    try:
        from core.secure_config import get_config, get_api_key
        
        config = get_config()
        print_result("配置加载", True)
        
        # 检查 API Key 配置
        openai_key = get_api_key("openai")
        if openai_key:
            print_result("OpenAI API Key 已配置", True)
        else:
            print_result("OpenAI API Key 未配置 (可选)", True)
        
        return True
    except Exception as e:
        print_result("配置测试", False, str(e))
        return False

def main():
    """主测试函数"""
    print("\n" + "="*50)
    print("  UFO Galaxy V2 系统验证")
    print("="*50)
    
    results = []
    
    # 同步测试
    results.append(("核心模块导入", test_imports()))
    results.append(("关键节点", test_nodes()))
    results.append(("安全表达式", test_safe_eval()))
    results.append(("配置", test_config()))
    
    # 异步测试
    results.append(("异步组件", asyncio.run(test_async_components())))
    
    # 总结
    print_header("测试总结")
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, success in results:
        print_result(name, success)
    
    print(f"\n通过: {passed}/{total}")
    
    if passed == total:
        print("\n✅ 所有测试通过！系统已就绪。")
        return 0
    else:
        print(f"\n⚠️  {total - passed} 个测试失败，请检查错误信息。")
        return 1

if __name__ == "__main__":
    sys.exit(main())
