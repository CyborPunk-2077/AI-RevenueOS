import os

path = r"D:\PAISA HAI TO\AI-RevenueOS\AI-RevenueOS\backend\src\application\leads\lifecycle_ops.py"

with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Fix mypy errors for update()
content = content.replace("LeadSourceEvent.__table__.update()", "update(LeadSourceEvent)")
content = content.replace("LeadDuplicateCandidate.__table__.update()", "update(LeadDuplicateCandidate)")

# Ensure update is imported (it is, from sqlalchemy import func, select)
# I'll replace "from sqlalchemy import func, select" with "from sqlalchemy import func, select, update"
if "from sqlalchemy import func, select, update" not in content:
    content = content.replace("from sqlalchemy import func, select", "from sqlalchemy import func, select, update")

# 2. Fix unused actor_id
content = content.replace(
    "async def deduplicate(\n    *, tenant_id: UUID, actor_id: UUID, lead_id: UUID, persist: bool = True",
    "async def deduplicate(\n    *, tenant_id: UUID, actor_id: UUID, lead_id: UUID, persist: bool = True"
)
# Actually, I'll just change "actor_id: UUID" to "_actor_id: UUID" where deduplicate is defined.
# Let's be safe:
content = content.replace(
    "async def deduplicate(\n    *, tenant_id: UUID, actor_id: UUID, lead_id: UUID",
    "async def deduplicate(\n    *, tenant_id: UUID, _actor_id: UUID, lead_id: UUID"
)

with open(path, "w", encoding="utf-8") as f:
    f.write(content)

print("Fixed lifecycle_ops.py")
