#!/usr/bin/env python
"""
Institutional F&O Terminal Test Runner
Allows running unit tests (fast & offline) or full integration tests (live website checks).
"""
import sys
import unittest
import os

def run_tests():
    print("=" * 60)
    print("         FNO_BHAV AUTOMATED TEST SUITE RUNNER")
    print("=" * 60)
    
    # Check if user wants to run live integration tests
    # Default is offline (fast mocks) to protect from rate-limits/external dependency failures in standard pipelines
    run_live = len(sys.argv) > 1 and sys.argv[1].lower() in ["--live", "live", "-l"]
    
    if not run_live:
        print("[*] Running FAST OFFLINE UNIT TESTS (Mocked network requests)...")
        print("[*] (To run live integration tests against the live NSE website, run: python run_tests.py --live)\n")
        os.environ["SKIP_LIVE_TESTS"] = "1"
    else:
        print("[*] Running LIVE INTEGRATION TESTS (Connecting to live NSE Website)...")
        print("[!] Note: This relies on live internet connectivity and active NSE servers.\n")
        if "SKIP_LIVE_TESTS" in os.environ:
            del os.environ["SKIP_LIVE_TESTS"]

    # Discover and run tests
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir="tests", pattern="test_*.py")
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    print("\n" + "=" * 60)
    if result.wasSuccessful():
        print(" SUCCESS: All automated test cases passed successfully!")
        sys.exit(0)
    else:
        print(" FAILURE: Some test cases failed. Please review the output above.")
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
