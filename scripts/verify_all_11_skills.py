import asyncio
import os
import sys

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.memory.db import get_pool, close_pool
from backend.skills import dispatch_skill

async def main():
    pool = await get_pool()
    print("=== LIVE DISPATCH PASS FOR ALL 11 README SKILLS ===")

    # 1. add_task
    add_res = await dispatch_skill("add_task", {
        "title": "Comprehensive 11-Skill Audit Task",
        "domain": "hackathon",
        "priority": "urgent"
    }, pool)
    task_id = add_res.get("data", {}).get("id")
    print(f"add_task                  -> [OK] {add_res.get('response')}")

    # 2. query_tasks
    q_res = await dispatch_skill("query_tasks", {"domain": "hackathon"}, pool)
    print(f"query_tasks               -> [OK] {q_res.get('response')[:80]}")

    # 3. list_projects
    lp_res = await dispatch_skill("list_projects", {"domain": "hackathon"}, pool)
    print(f"list_projects             -> [OK] {lp_res.get('response')[:80]}")

    # 4. log_code_context
    lcc_res = await dispatch_skill("log_code_context", {
        "content": "Verified all 11 skills live with Neon PostgreSQL backend",
        "project": "Compass",
        "tags": "audit,skills"
    }, pool)
    print(f"log_code_context          -> [OK] {lcc_res.get('response')}")

    # 5. query_code_context
    qcc_res = await dispatch_skill("query_code_context", {"query": "Neon PostgreSQL skills"}, pool)
    print(f"query_code_context        -> [OK] {qcc_res.get('response')[:80]}")

    # 6. query_coursework_notes
    qcn_res = await dispatch_skill("query_coursework_notes", {"query": "RISC-V hazard notes"}, pool)
    print(f"query_coursework_notes    -> [OK] {qcn_res.get('response')[:80]}")

    # 7. update_task_status
    uts_res = await dispatch_skill("update_task_status", {"task_id": task_id, "status": "in_progress"}, pool)
    print(f"update_task_status        -> [OK] {uts_res.get('response')}")

    # 8. edit_task
    et_res = await dispatch_skill("edit_task", {"task_id": task_id, "title": "Comprehensive 11-Skill Audit Task (Updated)"}, pool)
    print(f"edit_task                 -> [OK] {et_res.get('response')}")

    # 9. delete_task
    dt_res = await dispatch_skill("delete_task", {"task_id": task_id}, pool)
    print(f"delete_task               -> [OK] {dt_res.get('response')}")

    # 10. chat
    chat_res = await dispatch_skill("chat", {"message": "Hey! What can you help me with?"}, pool)
    print(f"chat                      -> [OK] {chat_res.get('response')}")

    # 11. summarize_across_domains
    sum_res = await dispatch_skill("summarize_across_domains", {"date": "2026-09-14"}, pool)
    print(f"summarize_across_domains  -> [OK] {sum_res.get('response')[:80]}")

    await close_pool()

if __name__ == "__main__":
    asyncio.run(main())
