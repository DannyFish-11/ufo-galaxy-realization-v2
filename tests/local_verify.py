#!/usr/bin/env python3
"""
UFO Galaxy Local Verification
Tests the core logic without Podman/Docker

This script:
1. Starts core nodes as local processes
2. Runs integration tests
3. Verifies the architecture works
"""

import asyncio
import subprocess
import sys
import time
import signal
import os
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

import httpx

# =============================================================================
# Configuration
# =============================================================================

NODES = [
    {"name": "Node_00_StateMachine", "port": 8000, "critical": True},
    {"name": "Node_68_Security", "port": 8068, "critical": True},
    {"name": "Node_50_Transformer", "port": 8050, "critical": True},
    {"name": "Node_58_ModelRouter", "port": 8058, "critical": True},
    {"name": "Node_33_ADB", "port": 8033, "critical": False},
]

processes = []

# =============================================================================
# Process Management
# =============================================================================

def start_node(node: dict) -> subprocess.Popen:
    """Start a node as a subprocess."""
    name = node["name"]
    port = node["port"]
    
    node_dir = Path(__file__).parent.parent / "nodes" / name
    main_py = node_dir / "main.py"
    
    if not main_py.exists():
        print(f"⚠️  {name}: main.py not found")
        return None
    
    env = os.environ.copy()
    env["STATE_MACHINE_URL"] = "http://localhost:8000"
    env["SECURITY_URL"] = "http://localhost:8068"
    env["TRANSFORMER_URL"] = "http://localhost:8050"
    env["USE_MOCK_DRIVERS"] = "true"
    env["LOG_LEVEL"] = "WARNING"
    
    process = subprocess.Popen(
        [sys.executable, str(main_py)],
        cwd=str(node_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    return process

def stop_all():
    """Stop all running processes."""
    for p in processes:
        if p and p.poll() is None:
            p.terminate()
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()

def signal_handler(sig, frame):
    """Handle Ctrl+C."""
    print("\n🛑 Stopping all nodes...")
    stop_all()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# =============================================================================
# Tests
# =============================================================================

async def wait_for_health(url: str, timeout: int = 10) -> bool:
    """Wait for a service to become healthy."""
    async with httpx.AsyncClient() as client:
        start = time.time()
        while time.time() - start < timeout:
            try:
                response = await client.get(f"{url}/health", timeout=2.0)
                if response.status_code == 200:
                    return True
            except Exception:
                pass
            await asyncio.sleep(0.5)
    return False

async def run_tests():
    """Run integration tests."""
    print("\n" + "="*60)
    print("🧪 Running Integration Tests")
    print("="*60)
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        tests_passed = 0
        tests_total = 0
        
        # Test 1: State Machine Health
        tests_total += 1
        print("\n📋 Test 1: State Machine Health")
        try:
            response = await client.get("http://localhost:8000/health")
            if response.status_code == 200:
                print("   ✅ State Machine is healthy")
                tests_passed += 1
            else:
                print(f"   ❌ Unexpected status: {response.status_code}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 2: Lock Acquisition
        tests_total += 1
        print("\n📋 Test 2: Lock Acquisition")
        try:
            response = await client.post(
                "http://localhost:8000/lock/acquire",
                json={
                    "node_id": "test",
                    "resource_id": "test_resource",
                    "timeout_seconds": 10
                }
            )
            result = response.json()
            if result.get("success"):
                print(f"   ✅ Lock acquired: {result.get('token', '')[:16]}...")
                tests_passed += 1
                
                # Release lock
                await client.post(
                    "http://localhost:8000/lock/release",
                    json={
                        "node_id": "test",
                        "resource_id": "test_resource",
                        "token": result.get("token")
                    }
                )
            else:
                print(f"   ❌ Failed: {result.get('message')}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 3: Model Routing - Simple Query
        tests_total += 1
        print("\n📋 Test 3: Model Routing - Simple Query")
        try:
            response = await client.post(
                "http://localhost:8058/route",
                json={"prompt": "What time is it?"}
            )
            result = response.json()
            tier = result.get("model_tier")
            print(f"   Prompt: 'What time is it?'")
            print(f"   Selected: {result.get('selected_model')}")
            print(f"   Tier: {tier}")
            if tier == "local":
                print("   ✅ Correctly routed to local model")
                tests_passed += 1
            else:
                print(f"   ⚠️  Expected 'local', got '{tier}'")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 4: Model Routing - Complex Query
        tests_total += 1
        print("\n📋 Test 4: Model Routing - Complex Query")
        try:
            response = await client.post(
                "http://localhost:8058/route",
                json={"prompt": "Explain quantum entanglement and its mathematical foundations in detail"}
            )
            result = response.json()
            tier = result.get("model_tier")
            print(f"   Prompt: 'Explain quantum entanglement...'")
            print(f"   Selected: {result.get('selected_model')}")
            print(f"   Tier: {tier}")
            if tier in ["cloud_cheap", "cloud_smart", "cloud_premium"]:
                print("   ✅ Correctly routed to cloud model")
                tests_passed += 1
            else:
                print(f"   ⚠️  Expected cloud tier, got '{tier}'")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 5: Hardware Gateway
        tests_total += 1
        print("\n📋 Test 5: Hardware Gateway (Node 50)")
        try:
            response = await client.post(
                "http://localhost:8050/execute",
                json={
                    "action": "adb_screenshot",
                    "target_node": "33",
                    "params": {},
                    "source_node": "test"
                }
            )
            result = response.json()
            if result.get("success"):
                print("   ✅ Hardware request processed")
                print(f"   Execution path: {len(result.get('execution_path', []))} steps")
                tests_passed += 1
            else:
                print(f"   ❌ Failed: {result.get('error')}")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Test 6: Concurrent Requests
        tests_total += 1
        print("\n📋 Test 6: Concurrent Requests")
        try:
            async def make_request(i):
                return await client.post(
                    "http://localhost:8050/execute",
                    json={
                        "action": "adb_tap",
                        "target_node": "33",
                        "params": {"x": i*100, "y": 200},
                        "source_node": f"concurrent_{i}"
                    }
                )
            
            tasks = [make_request(i) for i in range(5)]
            responses = await asyncio.gather(*tasks, return_exceptions=True)
            
            successes = sum(1 for r in responses 
                          if not isinstance(r, Exception) and r.json().get("success"))
            
            print(f"   Concurrent requests: 5")
            print(f"   Successful: {successes}")
            
            if successes >= 3:  # 60% success rate (some failures expected due to lock contention)
                print("   ✅ Concurrent handling OK (some lock contention expected)")
                tests_passed += 1
            else:
                print(f"   ⚠️  Low success rate: {successes}/5")
        except Exception as e:
            print(f"   ❌ Error: {e}")
        
        # Summary
        print("\n" + "="*60)
        print(f"📊 Results: {tests_passed}/{tests_total} tests passed")
        print("="*60)
        
        return tests_passed == tests_total

# =============================================================================
# Main
# =============================================================================

async def main():
    print("""
╔═══════════════════════════════════════════════════════════╗
║         UFO Galaxy Local Verification                     ║
║         Testing without Podman/Docker                     ║
╚═══════════════════════════════════════════════════════════╝
    """)
    
    # Start nodes
    print("🚀 Starting nodes...")
    
    for node in NODES:
        name = node["name"]
        port = node["port"]
        
        print(f"   Starting {name} on port {port}...")
        process = start_node(node)
        
        if process:
            processes.append(process)
            
            # Wait for health
            healthy = await wait_for_health(f"http://localhost:{port}")
            
            if healthy:
                print(f"   ✅ {name} is ready")
            else:
                print(f"   ⚠️  {name} health check timeout")
                if node["critical"]:
                    print(f"   ❌ Critical node failed, aborting")
                    stop_all()
                    return 1
        else:
            if node["critical"]:
                print(f"   ❌ Critical node {name} failed to start")
                stop_all()
                return 1
    
    print("\n✅ All nodes started")
    
    # Run tests
    try:
        success = await run_tests()
    except Exception as e:
        print(f"\n❌ Test error: {e}")
        success = False
    
    # Cleanup
    print("\n🛑 Stopping nodes...")
    stop_all()
    
    if success:
        print("\n🎉 All tests passed! Architecture verified.")
        print("   Ready for Podman deployment.")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check the output above.")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
