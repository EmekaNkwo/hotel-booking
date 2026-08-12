#!/usr/bin/env python
"""M3 Step 3 verification script.

Runs all verification checks for the Room State Machine implementation.
"""

import os
import sys
import subprocess
from pathlib import Path


def run_command(cmd, description):
    """Run a command and return success status."""
    print(f"\n🔍 {description}")
    print(f"📋 {cmd}")
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent
        )
        if result.returncode == 0:
            print("✅ Success")
            return True
        else:
            print(f"❌ Failed (exit code {result.returncode})")
            if result.stdout:
                print(f"📄 stdout: {result.stdout}")
            if result.stderr:
                print(f"📄 stderr: {result.stderr}")
            return False
    except Exception as e:
        print(f"❌ Exception: {e}")
        return False


def main():
    """Run all verification checks."""
    print("🚀 M3 Step 3 Verification")
    print("=" * 50)

    checks = []

    # 1. Code quality checks
    print("\n🧹 Code Quality Checks")
    print("-" * 30)

    checks.append(run_command(
        ".venv/Scripts/python.exe -m ruff check apps/rooms/",
        "Ruff linting"
    ))

    checks.append(run_command(
        ".venv/Scripts/python.exe manage.py check",
        "Django system check"
    ))

    checks.append(run_command(
        ".venv/Scripts/python.exe manage.py makemigrations --check --dry-run",
        "Migration check"
    ))

    # 2. Unit tests
    print("\n🧪 Unit Tests")
    print("-" * 30)

    checks.append(run_command(
        ".venv/Scripts/python.exe manage.py test tests.unit.rooms.test_state_machine -v 2",
        "State machine unit tests"
    ))

    checks.append(run_command(
        ".venv/Scripts/python.exe manage.py test tests.unit.rooms.test_models -v 2",
        "Room model unit tests"
    ))

    # 3. Integration tests
    print("\n🔗 Integration Tests")
    print("-" * 30)

    checks.append(run_command(
        ".venv/Scripts/python.exe manage.py test tests.api.rooms -v 2",
        "Room API integration tests"
    ))

    # 4. Postgres integration
    print("\n🐘 Postgres Integration")
    print("-" * 30)

    checks.append(run_command(
        "pytest tests/integration/rooms/ -v",
        "Postgres integration tests"
    ))

    # 5. Test coverage
    print("\n📊 Test Coverage")
    print("-" * 30)

    checks.append(run_command(
        ".venv/Scripts/python.exe -m pytest --cov=apps/rooms --cov-report=term-missing tests/unit/rooms/ tests/api/rooms/",
        "Coverage report"
    ))

    # Summary
    print("\n📋 Verification Summary")
    print("=" * 50)

    passed = sum(checks)
    total = len(checks)

    print(f"✅ Passed: {passed}/{total}")
    print(f"❌ Failed: {total - passed}/{total}")

    if passed == total:
        print("\n🎉 All checks passed! M3 Step 3 is ready.")
        return 0
    else:
        print("\n⚠️  Some checks failed. Review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())