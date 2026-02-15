#!/usr/bin/env python3
"""
UFO Galaxy End-to-End Test Mission
DeepSeek Audited Architecture Verification

Tests:
1. Simple query -> Local model routing
2. Complex query -> Cloud model routing
3. Hardware screenshot -> Full onion path
4. Security rule enforcement
5. Concurrent request handling
"""

import asyncio
import httpx
import json
import time
from typing import Dict, List
from dataclasses import dataclass
from datetime import datetime

# =============================================================================
# Configuration
# =============================================================================

STATE_MACHINE_URL = "http://localhost:8000"
TRANSFORMER_URL = "http://localhost:8050"
MODEL_ROUTER_URL = "http://localhost:8058"

# =============================================================================
# Test Cases
# =============================================================================

@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float
    details: Dict
    error: str = None

class TestMission:
    """End-to-end test mission runner."""
    
    def __init__(self):
        self.results: List[TestResult] = []
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def run_all(self) -> bool:
        """Run all test missions."""
        print("""
╔═══════════════════════════════════════════════════════════╗
║         UFO Galaxy Test Mission                           ║
║         End-to-End Architecture Verification              ║
╚═══════════════════════════════════════════════════════════╝
        """)
        
        tests = [
            self.test_1_health_check,
            self.test_2_simple_query_routing,
            self.test_3_complex_query_routing,
            self.test_4_hardware_screenshot,
            self.test_5_lock_management,
            self.test_6_concurrent_requests,
        ]
        
        for i, test in enumerate(tests, 1):
            print(f"\n{'='*60}")
            print(f"Test {i}/{len(tests)}: {test.__name__}")
            print(f"{'='*60}")
            
            try:
                result = await test()
                self.results.append(result)
                
                if result.passed:
                    print(f"✅ PASSED ({result.duration_ms:.1f}ms)")
                else:
                    print(f"❌ FAILED: {result.error}")
                    
            except Exception as e:
                print(f"❌ EXCEPTION: {e}")
                self.results.append(TestResult(
                    name=test.__name__,
                    passed=False,
                    duration_ms=0,
                    details={},
                    error=str(e)
                ))
        
        # Print summary
        self._print_summary()
        
        return all(r.passed for r in self.results)
    
    async def test_1_health_check(self) -> TestResult:
        """Test 1: Verify all services are healthy."""
        start = time.time()
        details = {}
        
        services = [
            ("State Machine", STATE_MACHINE_URL),
            ("Transformer", TRANSFORMER_URL),
            ("Model Router", MODEL_ROUTER_URL),
        ]
        
        all_healthy = True
        for name, url in services:
            try:
                response = await self.client.get(f"{url}/health")
                health = response.json()
                details[name] = health
                
                if health.get("status") != "healthy":
                    all_healthy = False
                    print(f"   ⚠️  {name}: {health.get('status', 'unknown')}")
                else:
                    print(f"   ✅ {name}: healthy")
                    
            except Exception as e:
                details[name] = {"error": str(e)}
                all_healthy = False
                print(f"   ❌ {name}: {e}")
        
        duration = (time.time() - start) * 1000
        
        return TestResult(
            name="Health Check",
            passed=all_healthy,
            duration_ms=duration,
            details=details,
            error=None if all_healthy else "Some services unhealthy"
        )
    
    async def test_2_simple_query_routing(self) -> TestResult:
        """Test 2: Simple query should route to local model."""
        start = time.time()
        
        # Simple query
        prompt = "What time is it?"
        
        response = await self.client.post(
            f"{MODEL_ROUTER_URL}/route",
            json={"prompt": prompt, "prefer_local": False}
        )
        
        result = response.json()
        duration = (time.time() - start) * 1000
        
        print(f"   Prompt: '{prompt}'")
        print(f"   Selected: {result.get('selected_model')}")
        print(f"   Tier: {result.get('model_tier')}")
        print(f"   Complexity: {result.get('complexity_score')}")
        
        # Should route to local model for simple queries
        passed = result.get("model_tier") == "local"
        
        return TestResult(
            name="Simple Query Routing",
            passed=passed,
            duration_ms=duration,
            details=result,
            error=None if passed else f"Expected 'local', got '{result.get('model_tier')}'"
        )
    
    async def test_3_complex_query_routing(self) -> TestResult:
        """Test 3: Complex query should route to cloud model."""
        start = time.time()
        
        # Complex query
        prompt = """Analyze the quantum entanglement phenomenon in the context of 
        quantum computing. Explain the mathematical foundations including Bell states, 
        and discuss practical implementations in current quantum processors."""
        
        response = await self.client.post(
            f"{MODEL_ROUTER_URL}/route",
            json={"prompt": prompt, "prefer_local": False}
        )
        
        result = response.json()
        duration = (time.time() - start) * 1000
        
        print(f"   Prompt: '{prompt[:50]}...'")
        print(f"   Selected: {result.get('selected_model')}")
        print(f"   Tier: {result.get('model_tier')}")
        print(f"   Complexity: {result.get('complexity_score')}")
        
        # Should route to cloud model for complex queries
        passed = result.get("model_tier") in ["cloud_cheap", "cloud_smart", "cloud_premium"]
        
        return TestResult(
            name="Complex Query Routing",
            passed=passed,
            duration_ms=duration,
            details=result,
            error=None if passed else f"Expected cloud tier, got '{result.get('model_tier')}'"
        )
    
    async def test_4_hardware_screenshot(self) -> TestResult:
        """Test 4: Hardware screenshot through full onion path."""
        start = time.time()
        
        # Request screenshot through Node 50
        response = await self.client.post(
            f"{TRANSFORMER_URL}/execute",
            json={
                "action": "adb_screenshot",
                "target_node": "33",
                "params": {"device": "emulator-5554"},
                "source_node": "test_mission"
            }
        )
        
        result = response.json()
        duration = (time.time() - start) * 1000
        
        print(f"   Action: adb_screenshot")
        print(f"   Target: Node 33 (ADB)")
        print(f"   Success: {result.get('success')}")
        
        if result.get("execution_path"):
            print(f"   Execution Path:")
            for step in result.get("execution_path", []):
                print(f"      → {step}")
        
        passed = result.get("success", False)
        
        return TestResult(
            name="Hardware Screenshot",
            passed=passed,
            duration_ms=duration,
            details=result,
            error=None if passed else result.get("error", "Unknown error")
        )
    
    async def test_5_lock_management(self) -> TestResult:
        """Test 5: Hardware lock acquisition and release."""
        start = time.time()
        details = {}
        
        # Acquire lock
        print("   Acquiring lock...")
        response = await self.client.post(
            f"{STATE_MACHINE_URL}/lock/acquire",
            json={
                "node_id": "test_node",
                "resource_id": "test_resource",
                "timeout_seconds": 10,
                "reason": "Test mission"
            }
        )
        
        acquire_result = response.json()
        details["acquire"] = acquire_result
        
        if not acquire_result.get("success"):
            return TestResult(
                name="Lock Management",
                passed=False,
                duration_ms=(time.time() - start) * 1000,
                details=details,
                error="Failed to acquire lock"
            )
        
        token = acquire_result.get("token")
        print(f"   Lock acquired: {token[:16]}...")
        
        # Check active locks
        response = await self.client.get(f"{STATE_MACHINE_URL}/locks")
        locks = response.json()
        details["locks"] = locks
        print(f"   Active locks: {locks.get('count')}")
        
        # Release lock
        print("   Releasing lock...")
        response = await self.client.post(
            f"{STATE_MACHINE_URL}/lock/release",
            json={
                "node_id": "test_node",
                "resource_id": "test_resource",
                "token": token
            }
        )
        
        release_result = response.json()
        details["release"] = release_result
        
        duration = (time.time() - start) * 1000
        passed = release_result.get("success", False)
        
        print(f"   Lock released: {passed}")
        
        return TestResult(
            name="Lock Management",
            passed=passed,
            duration_ms=duration,
            details=details,
            error=None if passed else "Failed to release lock"
        )
    
    async def test_6_concurrent_requests(self) -> TestResult:
        """Test 6: Concurrent request handling."""
        start = time.time()
        
        # Create concurrent requests
        async def make_request(i: int):
            response = await self.client.post(
                f"{TRANSFORMER_URL}/execute",
                json={
                    "action": "adb_tap" if i % 2 == 0 else "adb_screenshot",
                    "target_node": "33",
                    "params": {"x": i * 100, "y": 200},
                    "source_node": f"concurrent_test_{i}"
                }
            )
            return response.json()
        
        # Run 5 concurrent requests
        print("   Sending 5 concurrent requests...")
        tasks = [make_request(i) for i in range(5)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        duration = (time.time() - start) * 1000
        
        # Count successes
        successes = sum(1 for r in results if isinstance(r, dict) and r.get("success"))
        total = len(results)
        success_rate = successes / total
        
        print(f"   Successful: {successes}/{total} ({success_rate*100:.0f}%)")
        
        # 80% success rate is acceptable (some may fail due to lock contention)
        passed = success_rate >= 0.8
        
        return TestResult(
            name="Concurrent Requests",
            passed=passed,
            duration_ms=duration,
            details={
                "total": total,
                "successes": successes,
                "success_rate": success_rate,
                "results": [str(r)[:100] for r in results]
            },
            error=None if passed else f"Success rate {success_rate*100:.0f}% below 80%"
        )
    
    def _print_summary(self):
        """Print test summary."""
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        
        for result in self.results:
            status = "✅" if result.passed else "❌"
            print(f"{status} {result.name}: {result.duration_ms:.1f}ms")
            if not result.passed and result.error:
                print(f"   Error: {result.error}")
        
        print("\n" + "-"*60)
        print(f"Total: {passed}/{total} tests passed ({passed/total*100:.0f}%)")
        
        if passed == total:
            print("\n🎉 ALL TESTS PASSED! UFO Galaxy architecture verified!")
        else:
            print(f"\n⚠️  {total - passed} test(s) failed")
        
        print("="*60)

# =============================================================================
# Main
# =============================================================================

async def main():
    mission = TestMission()
    success = await mission.run_all()
    return 0 if success else 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    exit(exit_code)
