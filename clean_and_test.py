"""Clean DB and run M4 test."""
import os
import subprocess

os.chdir(r'C:\Users\VERGIO\Documents\code_apps\django-projects\hotel-booking')

# Remove stale SQLite test DB
try:
    os.remove('db.sqlite3')
    print("Removed db.sqlite3")
except FileNotFoundError:
    print("No db.sqlite3 to remove")

# Run migrations
result = subprocess.run(
    ['.venv\\Scripts\\python.exe', 'manage.py', 'migrate', '--settings=config.settings.test', '--verbosity=1'],
    capture_output=True, text=True
)
print("STDOUT:", result.stdout[-500:] if result.stdout else "")
print("STDERR:", result.stderr[-500:] if result.stderr else "")
print("RC:", result.returncode)

if result.returncode == 0:
    # Run single test
    result2 = subprocess.run(
        ['.venv\\Scripts\\python.exe', '-m', 'pytest',
         'tests/unit/policies/test_lifecycle.py::TestPolicyLifecycle::test_create_draft',
         '-v', '--tb=short'],
        capture_output=True, text=True
    )
    print("TEST OUT:", result2.stdout[-1000:] if result2.stdout else "")
    print("TEST ERR:", result2.stderr[-500:] if result2.stderr else "")
    print("TEST RC:", result2.returncode)
