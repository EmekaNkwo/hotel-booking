#!/usr/bin/env python
"""Final verification script for M3 Step 3 - Single-Entry-Point Enforcement.

This script runs all required verification steps and reports results.
"""

import os
import sys
import subprocess
import django

# Setup Django
sys.path.insert(0, 'c:\\Users\\VERGIO\\Documents\\code_apps\\django-projects\\hotel-booking')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.local')
django.setup()


def run_command(cmd, description):
    """Run a command and return success status."""
    print(f"\n🔍 {description}")
    print(f"📋 Command: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, cwd='c:\\Users\\VERGIO\\Documents\\code_apps\\django-projects\\hotel-booking')
        if result.returncode == 0:
            print(f"✅ SUCCESS")
            return True, result.stdout
        else:
            print(f"❌ FAILED (exit code {result.returncode})")
            print(f"📝 Output: {result.stdout}")
            print(f"📝 Error: {result.stderr}")
            return False, result.stderr
    except Exception as e:
        print(f"❌ EXCEPTION: {e}")
        return False, str(e)


def run_tests(test_path, description):
    """Run pytest on a specific test path."""
    cmd = f"python -m pytest {test_path} -v"
    return run_command(cmd, description)


def main():
    """Run all verification steps."""
    print("🚀 Starting M3 Step 3 Final Verification")
    print("=" * 60)

    results = {}

    # 1. M3 Step 3 Test Suite
    print("\n📊 STEP 1: M3 Step 3 Test Suite")
    print("-" * 40)

    step3_tests = [
        ("tests/unit/rooms/test_state_machine.py", "State machine tests"),
        ("tests/unit/rooms/test_enforcement_final.py", "Enforcement tests"),
        ("tests/unit/rooms/test_dependency_direction.py", "Dependency direction tests"),
    ]

    for test_path, desc in step3_tests:
        success, output = run_tests(test_path, desc)
        results[f"step3_{test_path.replace('/', '_')}"] = success

    # 2. Full Unit/API Suite
    print("\n📊 STEP 2: Full Unit/API Suite")
    print("-" * 40)
    success, output = run_command("python -m pytest tests/unit/ tests/api/ -v", "Full test suite")
    results["full_test_suite"] = success

    # 3. PostgreSQL Integration Suite
    print("\n📊 STEP 3: PostgreSQL Integration Suite")
    print("-" * 40)
    success, output = run_command("python -m pytest tests/integration/ -v", "PostgreSQL integration tests")
    results["postgres_integration"] = success

    # 4. Ruff Linting
    print("\n📊 STEP 4: Ruff Linting")
    print("-" * 40)
    success, output = run_command("python -m ruff check apps/rooms/ apps/shared/workflows/ tests/unit/rooms/", "Ruff linting")
    results["ruff_linting"] = success

    # 5. Django System Check
    print("\n📊 STEP 5: Django System Check")
    print("-" * 40)
    success, output = run_command("python manage.py check", "Django system check")
    results["django_check"] = success

    # 6. Migration Check
    print("\n📊 STEP 6: Migration Check")
    print("-" * 40)
    success, output = run_command("python manage.py makemigrations --check --dry-run", "Migration check")
    results["migration_check"] = success

    # 7. Final Summary
    print("\n📊 FINAL SUMMARY")
    print("=" * 60)

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    print(f"✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total - passed}/{total}")

    if passed == total:
        print("\n🎉 ALL VERIFICATIONS PASSED!")
        print("\n📝 Next step: Commit the verified Step 3 implementation")
        return 0
    else:
        print("\n❌ SOME VERIFICATIONS FAILED")
        print("\n📝 Failed steps:")
        for step, success in results.items():
            if not success:
                print(f"  - {step}")
        return 1


if __name__ == "__main__":
    sys.exit(main())