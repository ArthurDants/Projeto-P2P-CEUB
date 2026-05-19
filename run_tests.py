#!/usr/bin/env python3
import subprocess
import sys
import time

output_file = "test_results.txt"

with open(output_file, 'w') as f:
    f.write("=" * 80 + "\n")
    f.write(f"Test Run: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    f.write("=" * 80 + "\n\n")
    
    # Test 1: Task tests
    f.write("\n### Testing: tests/tasks/ ###\n")
    result = subprocess.run(
        [sys.executable, '-m', 'pytest', 'tests/tasks/', '-v', '--tb=short'],
        capture_output=True,
        text=True,
        timeout=30
    )
    f.write(f"Return code: {result.returncode}\n")
    f.write("STDOUT:\n")
    f.write(result.stdout)
    f.write("\nSTDERR:\n")
    f.write(result.stderr)
    
    # Test 2: E2E basic
    f.write("\n\n### Testing: tests/e2e/test_e2e_basic.py ###\n")
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', 'tests/e2e/test_e2e_basic.py', '-v', '--tb=short'],
            capture_output=True,
            text=True,
            timeout=30
        )
        f.write(f"Return code: {result.returncode}\n")
        f.write("STDOUT:\n")
        f.write(result.stdout[-2000:])  # Last 2000 chars
        f.write("\nSTDERR:\n")
        f.write(result.stderr[-1000:])  # Last 1000 chars
    except subprocess.TimeoutExpired:
        f.write("TIMEOUT after 30 seconds\n")
    except Exception as e:
        f.write(f"ERROR: {e}\n")
    
    # Test 3: Borrow flow
    f.write("\n\n### Testing: tests/e2e/test_borrow_flow.py ###\n")
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', 'tests/e2e/test_borrow_flow.py', '-v', '--tb=short'],
            capture_output=True,
            text=True,
            timeout=60
        )
        f.write(f"Return code: {result.returncode}\n")
        f.write("STDOUT:\n")
        f.write(result.stdout[-2000:])
        f.write("\nSTDERR:\n")
        f.write(result.stderr[-1000:])
    except subprocess.TimeoutExpired:
        f.write("TIMEOUT after 60 seconds\n")
    except Exception as e:
        f.write(f"ERROR: {e}\n")
    
    # Test 4: Borrow failure retry
    f.write("\n\n### Testing: tests/e2e/test_borrow_failure_retry.py ###\n")
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', 'tests/e2e/test_borrow_failure_retry.py', '-v', '--tb=short'],
            capture_output=True,
            text=True,
            timeout=60
        )
        f.write(f"Return code: {result.returncode}\n")
        f.write("STDOUT:\n")
        f.write(result.stdout[-2000:])
        f.write("\nSTDERR:\n")
        f.write(result.stderr[-1000:])
    except subprocess.TimeoutExpired:
        f.write("TIMEOUT after 60 seconds\n")
    except Exception as e:
        f.write(f"ERROR: {e}\n")
    
    # Test 5: Borrow pending
    f.write("\n\n### Testing: tests/e2e/test_borrow_pending.py ###\n")
    try:
        result = subprocess.run(
            [sys.executable, '-m', 'pytest', 'tests/e2e/test_borrow_pending.py', '-v', '--tb=short'],
            capture_output=True,
            text=True,
            timeout=60
        )
        f.write(f"Return code: {result.returncode}\n")
        f.write("STDOUT:\n")
        f.write(result.stdout[-2000:])
        f.write("\nSTDERR:\n")
        f.write(result.stderr[-1000:])
    except subprocess.TimeoutExpired:
        f.write("TIMEOUT after 60 seconds\n")
    except Exception as e:
        f.write(f"ERROR: {e}\n")

print(f"Test results written to {output_file}")
