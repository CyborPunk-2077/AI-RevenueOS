import os
import subprocess

# 1. Fix callers for actor_id -> _actor_id
def replace_in_file(path, old, new):
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)

replace_in_file(
    r"D:\PAISA HAI TO\AI-RevenueOS\AI-RevenueOS\backend\src\api\v1\leads.py",
    "actor_id=principal.user.id,",
    "_actor_id=principal.user.id,"
)

replace_in_file(
    r"D:\PAISA HAI TO\AI-RevenueOS\AI-RevenueOS\backend\tests\e2e\test_lead_lifecycle_ops.py",
    "actor_id=uuid4()",
    "_actor_id=uuid4()"
)

# 2. Run ruff format and fix
subprocess.run([r"D:\PAISA HAI TO\AI-RevenueOS\.venv312\Scripts\python.exe", "-m", "ruff", "format"], cwd=r"D:\PAISA HAI TO\AI-RevenueOS\AI-RevenueOS\backend")
subprocess.run([r"D:\PAISA HAI TO\AI-RevenueOS\.venv312\Scripts\python.exe", "-m", "ruff", "check", "--fix"], cwd=r"D:\PAISA HAI TO\AI-RevenueOS\AI-RevenueOS\backend")

print("Fixed remaining backend issues.")
