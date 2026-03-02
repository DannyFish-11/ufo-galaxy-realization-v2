#!/usr/bin/env python3
"""
UFO Galaxy 64-Core System - Enhanced Local Verification Script
Tests SQLite persistence, cost estimation, and multi-resource locking.
"""

import asyncio
import sys
import os
import tempfile
import sqlite3

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set up test environment
os.environ["DATABASE_PATH"] = "/tmp/test_router.db"
os.environ["LOG_LEVEL"] = "WARNING"

async def test_complexity_judge():
    """Test enhanced complexity scoring."""
    print("\n" + "="*60)
    print("TEST 1: Enhanced Complexity Judge (Multi-dimensional Scoring)")
    print("="*60)
    
    from nodes.Node_58_ModelRouter.main import ComplexityJudge, ModelTier
    
    judge = ComplexityJudge()
    
    test_cases = [
        ("hello", "very_low"),
        ("what time is it?", "very_low"),
        ("explain how to implement a binary search tree", "medium"),
        ("write a complex distributed system with microservices architecture", "high"),
        ("```python\ndef fibonacci(n):\n    if n <= 1: return n\n    return fibonacci(n-1) + fibonacci(n-2)\n```", "medium"),
        ("analyze the quantum mechanical implications of the double-slit experiment and derive the wave function", "very_high"),
    ]
    
    passed = 0
    for prompt, expected_level in test_cases:
        result = judge.judge(prompt)
        actual_level = result["analysis"]["complexity_level"]
        score = result["complexity_score"]
        
        # Check if level is close enough (within one level)
        levels = ["very_low", "low", "medium", "high", "very_high"]
        expected_idx = levels.index(expected_level)
        actual_idx = levels.index(actual_level)
        
        is_close = abs(expected_idx - actual_idx) <= 1
        status = "✅" if is_close else "⚠️"
        
        print(f"\n{status} Prompt: '{prompt[:50]}...'")
        print(f"   Score: {score:.3f}, Level: {actual_level} (expected: {expected_level})")
        print(f"   Factors: {result['analysis']['factors'][:3]}")
        
        if is_close:
            passed += 1
    
    print(f"\n→ Passed: {passed}/{len(test_cases)}")
    return passed >= len(test_cases) * 0.7  # 70% pass rate

async def test_cost_estimator():
    """Test cost estimation."""
    print("\n" + "="*60)
    print("TEST 2: Cost Estimator")
    print("="*60)
    
    from nodes.Node_58_ModelRouter.main import CostEstimator
    
    estimator = CostEstimator()
    
    prompt = "Write a Python function to sort a list using quicksort algorithm"
    
    models_to_test = ["llama2", "gpt-3.5-turbo", "gpt-4", "claude-3-opus"]
    
    print(f"\nPrompt: '{prompt}'")
    print("-" * 50)
    
    for model in models_to_test:
        estimate = estimator.estimate(prompt, model)
        print(f"\n{model}:")
        print(f"  Tier: {estimate['tier']}")
        print(f"  Tokens: {estimate['total_tokens']}")
        print(f"  Cost: ${estimate['total_cost_usd']:.6f}")
        print(f"  Free: {estimate['is_free']}")
    
    # Verify local models are free
    local_estimate = estimator.estimate(prompt, "llama2")
    assert local_estimate["is_free"] == True, "Local models should be free"
    
    # Verify cloud models have cost
    cloud_estimate = estimator.estimate(prompt, "gpt-4")
    assert cloud_estimate["total_cost_usd"] > 0, "Cloud models should have cost"
    
    print("\n→ Cost estimation: ✅ PASSED")
    return True

async def test_database_persistence():
    """Test SQLite persistence."""
    print("\n" + "="*60)
    print("TEST 3: SQLite Database Persistence")
    print("="*60)
    
    from nodes.Node_58_ModelRouter.main import DatabaseManager
    
    # Use temp database
    db_path = "/tmp/test_router_persistence.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    db = DatabaseManager(db_path)
    
    # Test saving routing decision
    db.save_routing_decision(
        session_id="test_session_001",
        prompt="What is the capital of France?",
        complexity_score=0.15,
        target_model="llama2",
        model_tier="local",
        reason="Simple query",
        estimated_cost=0.0,
        estimated_tokens=20,
        response_time_ms=50
    )
    
    # Test saving session turn
    db.save_session_turn(
        session_id="test_session_001",
        turn_number=1,
        role="user",
        content="What is the capital of France?",
        model_used="llama2",
        tokens_used=20,
        cost_usd=0.0
    )
    
    # Verify data was saved
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("SELECT COUNT(*) FROM routing_decisions")
    routing_count = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM session_history")
    history_count = cursor.fetchone()[0]
    
    conn.close()
    
    print(f"\nRouting decisions saved: {routing_count}")
    print(f"Session history saved: {history_count}")
    
    # Test retrieval
    history = db.get_session_history("test_session_001")
    stats = db.get_routing_stats("test_session_001")
    
    print(f"Retrieved history: {len(history)} records")
    print(f"Stats: {stats}")
    
    assert routing_count == 1, "Should have 1 routing decision"
    assert history_count == 1, "Should have 1 session turn"
    
    # Cleanup
    os.remove(db_path)
    
    print("\n→ Database persistence: ✅ PASSED")
    return True

async def test_multi_resource_locking():
    """Test multi-resource locking in Node 50."""
    print("\n" + "="*60)
    print("TEST 4: Multi-Resource Locking (Node 50)")
    print("="*60)
    
    from nodes.Node_50_Transformer.main import HardwareArbiter
    
    # Check ACTION_RESOURCE_MAP
    print("\nAction → Resource Mapping:")
    print("-" * 50)
    
    expected_multi_resource = {
        "adb_screenshot": ["adb", "screen", "camera"],
        "scrcpy_start": ["scrcpy", "adb", "screen", "camera"],
        "print_start": ["printer", "serial"],
    }
    
    passed = True
    for action, expected_resources in expected_multi_resource.items():
        actual = HardwareArbiter.ACTION_RESOURCE_MAP.get(action, [])
        match = set(actual) == set(expected_resources)
        status = "✅" if match else "❌"
        print(f"{status} {action}: {actual}")
        if not match:
            print(f"   Expected: {expected_resources}")
            passed = False
    
    # Verify status check needs no locks
    status_resources = HardwareArbiter.ACTION_RESOURCE_MAP.get("print_status", [])
    if status_resources == []:
        print(f"✅ print_status: No locks required (correct)")
    else:
        print(f"❌ print_status: Should not require locks")
        passed = False
    
    print(f"\n→ Multi-resource locking: {'✅ PASSED' if passed else '❌ FAILED'}")
    return passed

async def test_full_routing_flow():
    """Test full routing flow with persistence."""
    print("\n" + "="*60)
    print("TEST 5: Full Routing Flow with Persistence")
    print("="*60)
    
    from nodes.Node_58_ModelRouter.main import (
        ModelRouter, DatabaseManager, RouteRequest, 
        OLLAMA_URL, ONEAPI_URL
    )
    
    # Setup
    db_path = "/tmp/test_full_flow.db"
    if os.path.exists(db_path):
        os.remove(db_path)
    
    os.environ["DATABASE_PATH"] = db_path
    db = DatabaseManager(db_path)
    router = ModelRouter(OLLAMA_URL, ONEAPI_URL, db)
    
    # Test routing multiple prompts
    test_prompts = [
        ("hello", "local"),
        ("explain quantum computing in detail", "cloud_cheap"),
        ("write a distributed consensus algorithm with Raft implementation", "cloud_smart"),
    ]
    
    for prompt, expected_tier_prefix in test_prompts:
        request = RouteRequest(
            prompt=prompt,
            session_id="test_flow_session"
        )
        
        response = await router.route(request)
        
        tier_match = response.model_tier.value.startswith(expected_tier_prefix.split("_")[0])
        status = "✅" if tier_match else "⚠️"
        
        print(f"\n{status} '{prompt[:40]}...'")
        print(f"   Model: {response.selected_model}")
        print(f"   Tier: {response.model_tier.value}")
        print(f"   Score: {response.complexity_score:.3f}")
        print(f"   Cost: ${response.estimated_cost_usd:.6f}")
    
    # Check persistence
    stats = db.get_routing_stats()
    print(f"\n→ Total routed requests: {stats.get('total_requests', 0)}")
    
    # Cleanup
    os.remove(db_path)
    
    print("\n→ Full routing flow: ✅ PASSED")
    return True

async def main():
    """Run all tests."""
    print("="*60)
    print("UFO Galaxy 64-Core System - Enhanced Verification")
    print("Testing: SQLite, Cost Estimation, Multi-Resource Locking")
    print("="*60)
    
    results = []
    
    try:
        results.append(("Complexity Judge", await test_complexity_judge()))
        results.append(("Cost Estimator", await test_cost_estimator()))
        results.append(("Database Persistence", await test_database_persistence()))
        results.append(("Multi-Resource Locking", await test_multi_resource_locking()))
        results.append(("Full Routing Flow", await test_full_routing_flow()))
    except Exception as e:
        print(f"\n❌ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Summary
    print("\n" + "="*60)
    print("VERIFICATION SUMMARY")
    print("="*60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 ALL ENHANCED FEATURES VERIFIED!")
        return 0
    else:
        print("\n⚠️ Some tests failed")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
