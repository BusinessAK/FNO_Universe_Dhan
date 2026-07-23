import os
import sys

# Ensure root directory is in sys.path so we can import the compilers
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from daily_compiler import main as daily_main
from equity_compiler import main as equity_main

def run_pipeline():
    print("=" * 80)
    print("  VANGUARD UNIFIED ORCHESTRATOR — F&O + CASH PIPELINE")
    print("=" * 80)
    
    # 1. Run F&O Compiler (daily_compiler.py)
    print("\n[*] Starting Phase 1: F&O Market Structure Compiler...")
    try:
        daily_main()
    except Exception as e:
        print(f"[!] F&O Compiler failed: {e}")
        return 1

    # 2. Run Cash Compiler (equity_compiler.py)
    print("\n[*] Starting Phase 2: Cash Market Equity Compiler...")
    try:
        equity_res = equity_main()
        if equity_res != 0:
            print(f"[!] Cash Compiler returned non-zero exit code: {equity_res}")
            return 1
    except Exception as e:
        print(f"[!] Cash Compiler failed: {e}")
        return 1

    print("\n" + "=" * 80)
    print("✅ UNIFIED PIPELINE COMPLETE: Both F&O and Cash segments successfully compiled.")
    print("=" * 80)
    
    # 3. Run Confluence Filter (Phase 2)
    print("\n[*] Starting Phase 3: Applying Strict Confluence Filter...")
    from vanguard.rules.unified_screener import run_confluence_filter
    try:
        run_confluence_filter()
    except Exception as e:
        print(f"[!] Confluence filter failed: {e}")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(run_pipeline())
