#!/usr/bin/env python3
"""
Master test runner for Evotel RPA integration
Runs all tests in sequence to validate the integration
"""
import sys
import os
import subprocess
import argparse
from pathlib import Path

def check_prerequisites():
    """Check if all prerequisites are met"""
    print("=" * 60)
    print("PREREQUISITE CHECK")
    print("=" * 60)
    
    issues = []
    
    # Check directory structure
    required_files = [
        "automations/__init__.py",
        "automations/evotel/__init__.py", 
        "automations/evotel/validation.py",
        "orchestrator.py",
        "worker.py",
        "config.py"
    ]
    
    for file_path in required_files:
        if not Path(file_path).exists():
            issues.append(f"Missing file: {file_path}")
        else:
            print(f"✓ Found: {file_path}")
    
    # Check environment file
    if not Path(".env").exists():
        issues.append("Missing .env file - create one with Evotel credentials")
    else:
        print("✓ Found: .env")
    
    # Check chromedriver
    try:
        from config import Config
        if not Path(Config.CHROMEDRIVER_PATH).exists():
            issues.append(f"ChromeDriver not found at: {Config.CHROMEDRIVER_PATH}")
        else:
            print(f"✓ Found ChromeDriver: {Config.CHROMEDRIVER_PATH}")
    except ImportError:
        issues.append("Cannot import config module")
    
    # Check Python packages
    required_packages = [
        "selenium", "requests", "pydantic", "fastapi", 
        "uvicorn", "pyotp", "tenacity", "pathlib"
    ]
    
    for package in required_packages:
        try:
            __import__(package)
            print(f"✓ Package available: {package}")
        except ImportError:
            issues.append(f"Missing Python package: {package}")
    
    if issues:
        print("\n" + "=" * 60)
        print("PREREQUISITE ISSUES FOUND:")
        print("=" * 60)
        for issue in issues:
            print(f"✗ {issue}")
        print("\nPlease fix these issues before running tests.")
        return False
    else:
        print("\n✓ All prerequisites met!")
        return True

def run_test(test_name, test_script):
    """Run a single test script"""
    print(f"\n{'=' * 60}")
    print(f"RUNNING: {test_name}")
    print("=" * 60)
    
    try:
        result = subprocess.run(
            [sys.executable, test_script],
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )
        
        if result.returncode == 0:
            print(f"✓ {test_name} PASSED")
            print("STDOUT:")
            print(result.stdout)
            return True
        else:
            print(f"✗ {test_name} FAILED")
            print("STDOUT:")
            print(result.stdout)
            print("STDERR:")
            print(result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print(f"✗ {test_name} TIMED OUT")
        return False
    except Exception as e:
        print(f"✗ {test_name} ERROR: {e}")
        return False

def main():
    """Main test execution"""
    parser = argparse.ArgumentParser(description="Test Evotel RPA integration")
    parser.add_argument("--skip-prereq", action="store_true", 
                       help="Skip prerequisite check")
    parser.add_argument("--test", choices=["direct", "worker", "e2e", "all"],
                       default="all", help="Which test to run")
    
    args = parser.parse_args()
    
    print("=" * 60)
    print("EVOTEL RPA INTEGRATION TEST SUITE")
    print("=" * 60)
    
    # Check prerequisites
    if not args.skip_prereq:
        if not check_prerequisites():
            return False
    
    # Define test scenarios
    tests = []
    
    if args.test in ["direct", "all"]:
        tests.append(("Direct Module Test", "test_direct_module.py"))
    
    if args.test in ["worker", "all"]:
        tests.append(("Worker Integration Test", "test_worker_integration.py"))
    
    if args.test in ["e2e", "all"]:
        tests.append(("End-to-End Test", "test_e2e_integration.py"))
    
    # Create test files if they don't exist
    test_files = {
        "test_direct_module.py": "direct_test",
        "test_worker_integration.py": "worker_test", 
        "test_e2e_integration.py": "e2e_test"
    }
    
    # Run tests
    passed = 0
    total = len(tests)
    
    for test_name, test_script in tests:
        if run_test(test_name, test_script):
            passed += 1
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    print(f"Tests passed: {passed}/{total}")
    
    if passed == total:
        print("✓ ALL TESTS PASSED!")
        print("✓ Evotel integration is working correctly")
        print("\nYour Evotel validation module is ready for production use.")
        return True
    else:
        print("✗ SOME TESTS FAILED")
        print("\nCheck the test output above for details.")
        print("\nCommon issues:")
        print("- Incorrect Evotel credentials in .env file")
        print("- ChromeDriver not found or wrong version") 
        print("- Missing Python packages")
        print("- Evotel portal is down or changed")
        print("- Network connectivity issues")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)