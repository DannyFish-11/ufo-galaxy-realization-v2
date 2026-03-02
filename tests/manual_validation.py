#!/usr/bin/env python3
"""
Manual validation script for unified command endpoint
Tests the endpoint integration with the rest of the system
"""

import sys
import os

# Add project root to Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from fastapi import FastAPI
from core.api_routes import create_api_routes

def test_endpoint_registration():
    """Test that endpoints are properly registered"""
    print("Testing endpoint registration...")
    
    # Create app and router
    app = FastAPI()
    router = create_api_routes()
    app.include_router(router)
    
    # Get all routes
    routes = [route for route in app.routes]
    route_paths = [route.path for route in routes]
    
    print(f"\nTotal routes: {len(routes)}")
    
    # Check for unified command endpoints
    expected_endpoints = [
        "/api/v1/command",
        "/api/v1/command/{request_id}/status"
    ]
    
    print("\nChecking for unified command endpoints:")
    for endpoint in expected_endpoints:
        if endpoint in route_paths:
            print(f"  ✅ {endpoint}")
        else:
            print(f"  ❌ {endpoint} NOT FOUND")
            return False
    
    # Show all v1 endpoints
    print("\nAll /api/v1 endpoints:")
    v1_endpoints = sorted([p for p in route_paths if p.startswith("/api/v1")])
    for endpoint in v1_endpoints:
        print(f"  - {endpoint}")
    
    return True

def test_models():
    """Test that models are properly defined"""
    print("\n" + "="*70)
    print("Testing Pydantic models...")
    
    from core.api_routes import (
        CommandStatus,
        UnifiedCommandRequest,
        UnifiedCommandResponse,
        TargetResult
    )
    
    # Test CommandStatus enum
    print("\nCommandStatus enum values:")
    for status in CommandStatus:
        print(f"  - {status.value}")
    
    # Test creating a request
    print("\nCreating UnifiedCommandRequest:")
    request = UnifiedCommandRequest(
        command="test_command",
        targets=["device_1", "device_2"],
        params={"key": "value"},
        mode="sync",
        timeout=30
    )
    print(f"  ✅ Request created: {request.command} -> {request.targets}")
    
    # Test creating a target result
    print("\nCreating TargetResult:")
    result = TargetResult(
        status=CommandStatus.DONE,
        output={"result": "success"},
        error=None,
        started_at="2026-02-12T10:00:00Z",
        completed_at="2026-02-12T10:00:05Z"
    )
    print(f"  ✅ Result created: {result.status}")
    
    return True

def test_auth_module():
    """Test authentication module"""
    print("\n" + "="*70)
    print("Testing authentication module...")
    
    from core.auth import verify_api_token, verify_device_id
    
    # Save original token
    original_token = os.environ.get("UFO_API_TOKEN")
    
    # Test dev mode (no token)
    if "UFO_API_TOKEN" in os.environ:
        del os.environ["UFO_API_TOKEN"]
    
    print("\nDev mode (no token set):")
    result = verify_api_token("any-token")
    print(f"  verify_api_token('any-token'): {result}")
    assert result == True, "Dev mode should allow any token"
    print("  ✅ Dev mode works correctly")
    
    # Test with token
    os.environ["UFO_API_TOKEN"] = "test-token-123"
    print("\nWith token set:")
    result = verify_api_token("test-token-123")
    print(f"  verify_api_token('test-token-123'): {result}")
    assert result == True, "Should accept correct token"
    
    result = verify_api_token("wrong-token")
    print(f"  verify_api_token('wrong-token'): {result}")
    assert result == False, "Should reject wrong token"
    print("  ✅ Token validation works correctly")
    
    # Test device ID validation
    print("\nDevice ID validation:")
    assert verify_device_id("device-001") == True
    print("  ✅ Valid device ID accepted")
    assert verify_device_id("") == False
    print("  ✅ Empty device ID rejected")
    assert verify_device_id("ab") == False
    print("  ✅ Short device ID rejected")
    
    # Restore original token
    if original_token is not None:
        os.environ["UFO_API_TOKEN"] = original_token
    elif "UFO_API_TOKEN" in os.environ:
        del os.environ["UFO_API_TOKEN"]
    
    return True

def main():
    """Run all validation tests"""
    print("="*70)
    print("Unified Command Endpoint - Manual Validation")
    print("="*70)
    
    tests = [
        ("Endpoint Registration", test_endpoint_registration),
        ("Pydantic Models", test_models),
        ("Authentication Module", test_auth_module),
    ]
    
    results = {}
    for name, test_func in tests:
        try:
            print("\n" + "="*70)
            results[name] = test_func()
            if results[name]:
                print(f"\n✅ {name}: PASSED")
            else:
                print(f"\n❌ {name}: FAILED")
        except Exception as e:
            print(f"\n❌ {name}: ERROR - {e}")
            import traceback
            traceback.print_exc()
            results[name] = False
    
    # Summary
    print("\n" + "="*70)
    print("VALIDATION SUMMARY")
    print("="*70)
    
    for name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{name}: {status}")
    
    all_passed = all(results.values())
    print("\n" + "="*70)
    if all_passed:
        print("✅ ALL VALIDATIONS PASSED")
    else:
        print("❌ SOME VALIDATIONS FAILED")
    print("="*70)
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
