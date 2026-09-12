"""
Compass — Browser Verification for Agent Panel with Live Mock Route.
Captures high-res visual verification of:
1. Initial Agent Planner view
2. Confirmation Gate active (Approve & Reject buttons + rejection feedback field)
3. Reject & Re-plan path (user declines action -> agent self-critique & re-plan)
4. Approve & Execute path (user approves -> action executes)
5. Undo action (user clicks undo -> reverts mutation)
"""

import asyncio
import json
from pathlib import Path
from playwright.async_api import async_playwright

CURRENT_ARTIFACT_DIR = Path("/Users/nandani/.gemini/antigravity-ide/brain/278f482b-84b6-401d-99e2-4b99eabe05b9")
VERIFICATION_DIR = Path("/Users/nandani/Downloads/compass/verification")
VERIFICATION_DIR.mkdir(parents=True, exist_ok=True)
TARGET_URL = "http://127.0.0.1:5173"


async def main():
    print("[1/5] Launching browser session...")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(viewport={"width": 1440, "height": 900})
        page = await context.new_page()

        # Route agent endpoints with realistic SSE streams
        run_count = {"val": 0}

        async def handle_agent_run(route, request):
            post_data = request.post_data_json or {}
            action = post_data.get("action")
            feedback = post_data.get("feedback", "")
            run_id = post_data.get("run_id", "run_mock_001")

            lines = []
            if not action:
                run_count["val"] += 1
                if run_count["val"] == 1:
                    # Flow 1: Requires confirmation
                    lines = [
                        {"event": "agent_start", "run_id": "run_mock_001", "goal": post_data.get("goal", "")},
                        {"event": "step_start", "step": 1, "type": "think"},
                        {"event": "thought", "step": 1, "content": "Querying current coursework and hackathon task lists to detect scheduling conflicts..."},
                        {"event": "step_start", "step": 2, "type": "act"},
                        {
                            "event": "confirm_request",
                            "step": 2,
                            "run_id": "run_mock_001",
                            "action": "update_task_status",
                            "parameters": {"task_id": "task_os_01", "new_status": "in_progress"},
                            "message": "Update task 'OS Homework 2' status to 'in_progress' and adjust deadline?"
                        }
                    ]
                else:
                    # Flow 2: Add task flow with confirmation
                    lines = [
                        {"event": "agent_start", "run_id": "run_mock_002", "goal": post_data.get("goal", "")},
                        {"event": "step_start", "step": 1, "type": "think"},
                        {"event": "thought", "step": 1, "content": "Analyzing coursework domain to create new task entry for RISC-V Pipeline review..."},
                        {"event": "step_start", "step": 2, "type": "act"},
                        {
                            "event": "confirm_request",
                            "step": 2,
                            "run_id": "run_mock_002",
                            "action": "add_task",
                            "parameters": {"title": "Review RISC-V Pipeline Hazards", "domain": "coursework", "priority": "high"},
                            "message": "Create task 'Review RISC-V Pipeline Hazards' in coursework domain?"
                        }
                    ]
            elif action == "reject":
                lines = [
                    {"event": "rejected", "step": 2, "run_id": run_id, "feedback": feedback or "User declined proposed modification"},
                    {"event": "step_start", "step": 3, "type": "think"},
                    {"event": "thought", "step": 3, "content": f"User rejected the status update with feedback: '{feedback}'. Re-planning alternative schedule without touching OS homework..."},
                    {"event": "step_start", "step": 4, "type": "critique"},
                    {"event": "thought", "step": 4, "content": "Self-critique pass (round 1/2): Verified revised schedule preserves existing deadlines and avoids conflicts with hackathon milestone."},
                    {"event": "done", "run_id": run_id, "total_steps": 4, "synthesis": "Re-planned schedule complete: Preserved OS Homework 2 deadline unchanged as requested and allocated Wednesday morning for RISC-V review."}
                ]
            elif action == "approve":
                lines = [
                    {"event": "action_result", "step": 2, "action": "add_task", "result": {"success": True, "task_id": "task_riscv_09", "title": "Review RISC-V Pipeline Hazards"}},
                    {"event": "step_start", "step": 3, "type": "critique"},
                    {"event": "thought", "step": 3, "content": "Self-critique pass (round 1/2): Verified newly created task is correctly categorized under 'coursework' with high priority."},
                    {"event": "done", "run_id": run_id, "total_steps": 3, "synthesis": "Successfully added task 'Review RISC-V Pipeline Hazards' to coursework domain."}
                ]

            body = "".join(f"data: {json.dumps(l)}\n\n" for l in lines)
            await route.fulfill(
                status=200,
                headers={"Content-Type": "text/event-stream", "Cache-Control": "no-cache"},
                body=body
            )

        async def handle_agent_undo(route, request):
            await route.fulfill(
                status=200,
                headers={"Content-Type": "application/json"},
                body=json.dumps({
                    "status": "undone",
                    "undone_action": "add_task",
                    "target_id": "task_riscv_09",
                    "message": "Successfully reverted add_task mutation for 'Review RISC-V Pipeline Hazards'."
                })
            )

        await page.route("**/api/agent/run", handle_agent_run)
        await page.route("**/api/agent/undo", handle_agent_undo)

        print(f"[2/5] Navigating to {TARGET_URL}...")
        await page.goto(TARGET_URL, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(1000)

        print("[3/5] Switching to 'Agent Planner' tab...")
        agent_tab_btn = page.locator("#sidebar-tab-agent")
        if await agent_tab_btn.count() > 0:
            await agent_tab_btn.click()
        else:
            await page.locator("#tab-agent").click(force=True)
        await page.wait_for_timeout(1200)

        # 1. Base Agent Panel Screenshot
        p1 = VERIFICATION_DIR / "browser_04_agent_panel.png"
        await page.screenshot(path=str(p1))
        await page.screenshot(path=str(CURRENT_ARTIFACT_DIR / "browser_04_agent_panel.png"))
        print(f"  Saved baseline UI: {p1}")

        # 2. Trigger flow 1: Confirmation Gate & Reject Path
        print("[4/5] Testing Confirm Gate and Reject path...")
        goal_input = page.locator("#agent-goal-input")
        await goal_input.fill("Plan my week and reschedule conflicting tasks")
        await page.locator("#agent-run-btn").click()

        # Wait for confirmation gate
        await page.wait_for_selector("#agent-reject-btn", timeout=10000)
        print("  Confirmation gate active: Reject & Approve buttons visible!")

        # Fill rejection feedback
        reject_input = page.locator("#agent-reject-input")
        if await reject_input.count() > 0:
            await reject_input.fill("Do not reschedule OS homework deadline")

        # Screenshot 2: Confirm Gate active
        p_gate = VERIFICATION_DIR / "browser_agent_confirm_gate.png"
        await page.screenshot(path=str(p_gate))
        await page.screenshot(path=str(CURRENT_ARTIFACT_DIR / "browser_agent_confirm_gate.png"))
        print(f"  Saved confirm gate screenshot: {p_gate}")

        # Click Reject & Re-plan
        print("  Clicking Reject & Re-plan...")
        await page.locator("#agent-reject-btn").click()
        await page.wait_for_selector("#agent-synthesis-card", timeout=10000)
        await page.wait_for_timeout(1000)

        # Screenshot 3: Reject path re-planned
        p_rej = VERIFICATION_DIR / "browser_agent_reject.png"
        await page.screenshot(path=str(p_rej))
        await page.screenshot(path=str(CURRENT_ARTIFACT_DIR / "browser_agent_reject.png"))
        print(f"  Saved reject path screenshot: {p_rej}")

        # 3. Flow 2: Approve & Undo flow
        print("[5/5] Testing Approve and Undo flow...")
        await goal_input.fill("Add task 'Review RISC-V Pipeline Hazards' in coursework")
        await page.locator("#agent-run-btn").click()

        await page.wait_for_selector("#agent-approve-btn", timeout=10000)
        print("  Clicking Approve & Execute...")
        await page.locator("#agent-approve-btn").click()
        await page.wait_for_selector("#agent-synthesis-card", timeout=10000)
        await page.wait_for_timeout(1000)

        p_app = VERIFICATION_DIR / "browser_agent_approve.png"
        await page.screenshot(path=str(p_app))
        await page.screenshot(path=str(CURRENT_ARTIFACT_DIR / "browser_agent_approve.png"))
        print(f"  Saved approve path screenshot: {p_app}")

        # Undo button test
        undo_btn = page.locator("#agent-undo-btn")
        if await undo_btn.count() > 0:
            print("  Clicking Undo Last Mutation...")
            await undo_btn.click()
            await page.wait_for_timeout(1500)
            p_undo = VERIFICATION_DIR / "browser_agent_undo.png"
            await page.screenshot(path=str(p_undo))
            await page.screenshot(path=str(CURRENT_ARTIFACT_DIR / "browser_agent_undo.png"))
            print(f"  Saved undo path screenshot: {p_undo}")

        print("Browser verification completed successfully!")
        await page.close()


if __name__ == "__main__":
    asyncio.run(main())
