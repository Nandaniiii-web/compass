"""
Compass — Deterministic Dynamic Scheduling Engine.

Provides pure Python interval arithmetic for packing tasks into calendar time slots.
Guarantees 0% LLM hallucination in time calculations, working hour boundaries,
inter-task buffers, and deadline satisfaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
import logging

logger = logging.getLogger("compass.scheduler")

PRIORITY_WEIGHTS: Dict[str, int] = {
    "urgent": 4,
    "high": 3,
    "medium": 2,
    "low": 1,
}


def _ensure_utc(dt: datetime | str | date) -> datetime:
    """Normalize input datetime to UTC timezone-aware datetime."""
    if isinstance(dt, str):
        # Handle ISO strings
        clean_str = dt.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(clean_str)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except Exception:
            # Fallback to date parsing
            d = date.fromisoformat(clean_str[:10])
            return datetime.combine(d, time.min, tzinfo=timezone.utc)
    elif isinstance(dt, date) and not isinstance(dt, datetime):
        return datetime.combine(dt, time.min, tzinfo=timezone.utc)
    elif isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    raise ValueError(f"Cannot convert {type(dt)} to UTC datetime")


def _parse_time_str(t_val: str | time) -> time:
    """Parse HH:MM:SS or HH:MM string to datetime.time."""
    if isinstance(t_val, time):
        return t_val
    parts = str(t_val).split(":")
    h = int(parts[0])
    m = int(parts[1]) if len(parts) > 1 else 0
    s = int(parts[2]) if len(parts) > 2 else 0
    return time(hour=h, minute=m, second=s)


@dataclass
class TimeWindow:
    """A contiguous interval of available or busy time."""
    start: datetime
    end: datetime
    label: Optional[str] = None
    is_busy: bool = False

    def __post_init__(self) -> None:
        self.start = _ensure_utc(self.start)
        self.end = _ensure_utc(self.end)
        if self.end < self.start:
            raise ValueError(f"Window end ({self.end}) cannot precede start ({self.start})")

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() // 60)


def merge_overlapping_intervals(intervals: Sequence[TimeWindow]) -> List[TimeWindow]:
    """Merge overlapping or contiguous busy intervals."""
    if not intervals:
        return []

    sorted_intervals = sorted(intervals, key=lambda w: w.start)
    merged: List[TimeWindow] = [sorted_intervals[0]]

    for current in sorted_intervals[1:]:
        prev = merged[-1]
        if current.start <= prev.end:
            # Overlap or contiguous -> extend previous
            merged[-1] = TimeWindow(
                start=prev.start,
                end=max(prev.end, current.end),
                label=prev.label or current.label,
                is_busy=prev.is_busy or current.is_busy,
            )
        else:
            merged.append(current)

    return merged


def get_available_windows(
    busy_intervals: Sequence[TimeWindow | Dict[str, Any]],
    search_start: datetime | str,
    search_end: datetime | str,
    work_start_time: str | time = "09:00:00",
    work_end_time: str | time = "18:00:00",
    work_days: Optional[Sequence[int]] = None,
    buffer_minutes: int = 15,
) -> List[TimeWindow]:
    """Calculate free working-hour windows by subtracting busy intervals from daily working hours.

    Args:
        busy_intervals: External events or existing fixed tasks.
        search_start: Start of scheduling horizon.
        search_end: End of scheduling horizon.
        work_start_time: Daily start of working hours (default 09:00).
        work_end_time: Daily end of working hours (default 18:00).
        work_days: Allowed weekdays (1=Mon, 7=Sun). Default Monday-Friday [1,2,3,4,5].
        buffer_minutes: Safety buffer around busy events (default 15m).

    Returns:
        List of available TimeWindow intervals within working hours.
    """
    start_utc = _ensure_utc(search_start)
    end_utc = _ensure_utc(search_end)
    w_start = _parse_time_str(work_start_time)
    w_end = _parse_time_str(work_end_time)
    allowed_days = set(work_days if work_days is not None else [1, 2, 3, 4, 5])

    # Convert raw dicts or objects into TimeWindow instances with buffer expansion
    normalized_busy: List[TimeWindow] = []
    buf_td = timedelta(minutes=buffer_minutes)

    for item in busy_intervals:
        if isinstance(item, TimeWindow):
            b_start = item.start - buf_td
            b_end = item.end + buf_td
            label = item.label
        elif isinstance(item, dict):
            b_start = _ensure_utc(item.get("start") or item.get("scheduled_start")) - buf_td
            b_end = _ensure_utc(item.get("end") or item.get("scheduled_end")) + buf_td
            label = item.get("title") or item.get("label")
        else:
            continue

        if b_end > b_start:
            normalized_busy.append(TimeWindow(start=b_start, end=b_end, label=label, is_busy=True))

    merged_busy = merge_overlapping_intervals(normalized_busy)

    # Walk day-by-day across search horizon
    available: List[TimeWindow] = []
    current_day = start_utc.date()
    end_day = end_utc.date()

    while current_day <= end_day:
        if current_day.isoweekday() in allowed_days:
            day_work_start = datetime.combine(current_day, w_start, tzinfo=timezone.utc)
            day_work_end = datetime.combine(current_day, w_end, tzinfo=timezone.utc)

            # Clip to search horizon
            effective_start = max(day_work_start, start_utc)
            effective_end = min(day_work_end, end_utc)

            if effective_end > effective_start:
                # Subtract busy blocks from [effective_start, effective_end]
                cursor = effective_start
                for busy in merged_busy:
                    if busy.end <= cursor:
                        continue
                    if busy.start >= effective_end:
                        break

                    if busy.start > cursor:
                        free_end = min(busy.start, effective_end)
                        if free_end > cursor:
                            available.append(TimeWindow(start=cursor, end=free_end, is_busy=False))
                    cursor = max(cursor, busy.end)

                if cursor < effective_end:
                    available.append(TimeWindow(start=cursor, end=effective_end, is_busy=False))

        current_day += timedelta(days=1)

    # Filter out windows shorter than buffer/15 mins
    return [w for w in available if w.duration_minutes >= max(15, buffer_minutes)]


def allocate_task_slots(
    tasks: Sequence[Dict[str, Any]],
    available_windows: Sequence[TimeWindow],
    buffer_minutes: int = 15,
    strategy: str = "priority_first",
    dependencies: Optional[Mapping[int, Sequence[int]]] = None,
    existing_scheduled_map: Optional[Dict[int, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Deterministically allocate tasks into available time windows.

    Tasks are prioritized by:
      1. Topological dependency prerequisites (parents must finish before children start)
      2. Priority weight (urgent > high > medium > low)
      3. Due date (earlier deadlines first)
      4. Duration (fitting tasks efficiently)

    Ensures:
      - No overlapping allocations.
      - Each task is placed after all prerequisite tasks have completed + buffer.
      - Each task is placed within its deadline (`scheduled_end <= due_date 23:59:59 UTC`).
      - Preserves `buffer_minutes` between consecutive scheduled slots.
      - Returns both scheduled slots and any unassigned tasks with rationale.
    """
    if not tasks:
        return {
            "scheduled": [],
            "unassigned": [],
            "conflicts": [],
            "summary": "No tasks provided for scheduling.",
        }

    # Normalize dependencies map
    dep_map: Dict[int, List[int]] = {}
    if dependencies:
        for k, v in dependencies.items():
            dep_map[int(k)] = [int(x) for x in v]
    for t in tasks:
        tid = t.get("id")
        if tid is not None and t.get("depends_on"):
            dep_map.setdefault(int(tid), []).extend([int(x) for x in t["depends_on"]])

    # Map of already scheduled tasks (from previous state or prior batches)
    scheduled_map: Dict[int, Dict[str, Any]] = {}
    if existing_scheduled_map:
        for k, v in existing_scheduled_map.items():
            scheduled_map[int(k)] = {
                "scheduled_start": _ensure_utc(v["scheduled_start"]),
                "scheduled_end": _ensure_utc(v["scheduled_end"]),
            }

    # Sort key for tasks that are ready
    def sort_key(t: Dict[str, Any]) -> Tuple[int, datetime, int]:
        prio = str(t.get("priority", "medium")).lower()
        prio_rank = -PRIORITY_WEIGHTS.get(prio, 2)  # Higher priority comes first

        due = t.get("due_date")
        if due:
            if isinstance(due, (datetime, date)):
                due_dt = _ensure_utc(due)
            else:
                due_dt = _ensure_utc(str(due))
        else:
            due_dt = datetime.max.replace(tzinfo=timezone.utc)

        duration = int(t.get("duration_minutes") or 60)
        return (prio_rank, due_dt, duration)

    remaining_tasks = list(tasks)
    # Make mutable list of free windows: list of [start, end]
    free_blocks: List[List[datetime]] = [[w.start, w.end] for w in available_windows]

    scheduled: List[Dict[str, Any]] = []
    unassigned: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []

    buf_delta = timedelta(minutes=buffer_minutes)

    while remaining_tasks:
        # Find all ready tasks (all prerequisites in scheduled_map)
        ready_tasks = []
        for t in remaining_tasks:
            tid = t.get("id")
            prereqs = dep_map.get(int(tid), []) if tid is not None else []
            if all(p in scheduled_map for p in prereqs):
                ready_tasks.append(t)

        if not ready_tasks:
            # Deadlock or unfulfilled prerequisite among remaining tasks
            for t in remaining_tasks:
                unassigned.append({
                    "task_id": t.get("id"),
                    "title": t.get("title"),
                    "priority": t.get("priority", "medium"),
                    "duration_minutes": int(t.get("duration_minutes") or 60),
                    "due_date": str(t.get("due_date")) if t.get("due_date") else None,
                    "reason": "Prerequisite dependencies not satisfied or could not be scheduled.",
                })
            break

        # Pick the highest priority ready task
        task = min(ready_tasks, key=sort_key)
        remaining_tasks.remove(task)

        duration_min = int(task.get("duration_minutes") or 60)
        needed_delta = timedelta(minutes=duration_min)

        # Parse due date deadline if present
        due_limit: Optional[datetime] = None
        if task.get("due_date"):
            raw_due = task["due_date"]
            if isinstance(raw_due, str):
                d_obj = date.fromisoformat(raw_due[:10])
                due_limit = datetime.combine(d_obj, time(23, 59, 59), tzinfo=timezone.utc)
            elif isinstance(raw_due, date) and not isinstance(raw_due, datetime):
                due_limit = datetime.combine(raw_due, time(23, 59, 59), tzinfo=timezone.utc)
            elif isinstance(raw_due, datetime):
                due_limit = _ensure_utc(raw_due)

        # Determine earliest allowed start based on prerequisites
        tid = task.get("id")
        prereqs = dep_map.get(int(tid), []) if tid is not None else []
        if prereqs:
            earliest_allowed_start = max(scheduled_map[p]["scheduled_end"] + buf_delta for p in prereqs)
        else:
            earliest_allowed_start = datetime.min.replace(tzinfo=timezone.utc)

        placed = False
        for i, block in enumerate(free_blocks):
            b_start, b_end = block[0], block[1]
            slot_start = max(b_start, earliest_allowed_start)
            slot_end = slot_start + needed_delta

            if slot_end > b_end:
                continue

            # Check if placement violates due date
            if due_limit and slot_end > due_limit:
                conflicts.append({
                    "task_id": task.get("id"),
                    "title": task.get("title"),
                    "due_date": str(task.get("due_date")),
                    "earliest_available": slot_start.isoformat(),
                    "issue": "Cannot be scheduled before deadline with current calendar load.",
                })
                break

            # Slot fits! Record assignment
            scheduled.append({
                "task_id": task.get("id"),
                "title": task.get("title"),
                "domain": task.get("domain", "general"),
                "priority": task.get("priority", "medium"),
                "duration_minutes": duration_min,
                "scheduled_start": slot_start.isoformat(),
                "scheduled_end": slot_end.isoformat(),
            })

            if tid is not None:
                scheduled_map[int(tid)] = {
                    "scheduled_start": slot_start,
                    "scheduled_end": slot_end,
                }

            # Update free blocks: split before and after
            new_pieces: List[List[datetime]] = []
            if slot_start > b_start and (slot_start - b_start).total_seconds() >= max(15, buffer_minutes) * 60:
                new_pieces.append([b_start, slot_start])

            after_start = slot_end + buf_delta
            if after_start < b_end and (b_end - after_start).total_seconds() >= max(15, buffer_minutes) * 60:
                new_pieces.append([after_start, b_end])

            free_blocks[i:i + 1] = new_pieces
            placed = True
            break

        if not placed and not any(c.get("task_id") == task.get("id") for c in conflicts):
            unassigned.append({
                "task_id": task.get("id"),
                "title": task.get("title"),
                "priority": task.get("priority", "medium"),
                "duration_minutes": duration_min,
                "due_date": str(task.get("due_date")) if task.get("due_date") else None,
                "reason": "Insufficient free time windows within working hours or before deadline.",
            })

    summary_text = (
        f"Scheduled {len(scheduled)} tasks successfully ({len(unassigned)} unassigned, "
        f"{len(conflicts)} deadline conflicts)."
    )

    return {
        "scheduled": scheduled,
        "unassigned": unassigned,
        "conflicts": conflicts,
        "summary": summary_text,
    }


def find_slipped_tasks(
    tasks: Sequence[Dict[str, Any]],
    current_time: Optional[datetime | str] = None,
) -> List[Dict[str, Any]]:
    """Detect tasks that were scheduled to end before current_time but are not marked 'done'."""
    now_utc = _ensure_utc(current_time) if current_time else datetime.now(timezone.utc)
    slipped: List[Dict[str, Any]] = []

    for t in tasks:
        status = str(t.get("status", "open")).lower().strip()
        if status in ("done", "completed", "closed"):
            continue

        sched_end = t.get("scheduled_end")
        if not sched_end:
            continue

        end_utc = _ensure_utc(sched_end)
        if end_utc < now_utc:
            slipped.append({
                **dict(t),
                "scheduled_end_utc": end_utc.isoformat(),
                "slip_minutes": max(0, int((now_utc - end_utc).total_seconds() // 60)),
            })

    return slipped


def replan_slipped_tasks(
    slipped_tasks: Sequence[Dict[str, Any]],
    all_tasks: Sequence[Dict[str, Any]],
    dependencies: Optional[Mapping[int, Sequence[int]]] = None,
    available_windows: Sequence[TimeWindow] = (),
    buffer_minutes: int = 15,
) -> Dict[str, Any]:
    """Re-scope and replan slipped tasks and all downstream dependents.

    Preserves all unaffected tasks untouched.
    """
    if not slipped_tasks:
        return {
            "slipped_task_ids": [],
            "affected_task_ids": [],
            "rescheduled": [],
            "unassigned": [],
            "conflicts": [],
            "summary": "No slipped tasks to replan.",
        }

    dep_map: Dict[int, List[int]] = {}
    if dependencies:
        for k, v in dependencies.items():
            dep_map[int(k)] = [int(x) for x in v]

    for t in all_tasks:
        tid = t.get("id")
        if tid is not None and t.get("depends_on"):
            dep_map.setdefault(int(tid), []).extend([int(x) for x in t["depends_on"]])

    # Build downstream map: parent -> list of children
    downstream_map: Dict[int, List[int]] = {}
    for child, parents in dep_map.items():
        for parent in parents:
            downstream_map.setdefault(parent, []).append(child)

    slipped_ids = {int(t["id"]) for t in slipped_tasks if t.get("id") is not None}
    affected_ids = set(slipped_ids)
    queue = list(slipped_ids)
    while queue:
        curr = queue.pop(0)
        for child_id in downstream_map.get(curr, []):
            if child_id not in affected_ids:
                affected_ids.add(child_id)
                queue.append(child_id)

    task_by_id = {int(t["id"]): t for t in all_tasks if t.get("id") is not None}
    for st in slipped_tasks:
        if st.get("id") is not None:
            task_by_id[int(st["id"])] = st

    tasks_to_replan = [task_by_id[tid] for tid in affected_ids if tid in task_by_id]

    # Preserved tasks that remain scheduled and fixed in place
    existing_scheduled: Dict[int, Dict[str, Any]] = {}
    for t in all_tasks:
        tid = t.get("id")
        if tid is not None and int(tid) not in affected_ids and t.get("scheduled_start") and t.get("scheduled_end"):
            existing_scheduled[int(tid)] = {
                "scheduled_start": _ensure_utc(t["scheduled_start"]),
                "scheduled_end": _ensure_utc(t["scheduled_end"]),
            }

    allocation = allocate_task_slots(
        tasks=tasks_to_replan,
        available_windows=available_windows,
        buffer_minutes=buffer_minutes,
        dependencies=dep_map,
        existing_scheduled_map=existing_scheduled,
    )

    downstream_count = max(0, len(affected_ids) - len(slipped_ids))
    return {
        "slipped_task_ids": sorted(list(slipped_ids)),
        "affected_task_ids": sorted(list(affected_ids)),
        "rescheduled": allocation["scheduled"],
        "unassigned": allocation["unassigned"],
        "conflicts": allocation["conflicts"],
        "summary": f"Replanned {len(allocation['scheduled'])} tasks ({len(slipped_ids)} slipped, {downstream_count} downstream dependents).",
    }


def detect_schedule_conflicts(
    scheduled_tasks: Sequence[Dict[str, Any]],
    external_events: Optional[Sequence[Dict[str, Any]]] = None,
    dependencies: Optional[Mapping[int, Sequence[int]]] = None,
    current_time: Optional[datetime | str] = None,
    buffer_minutes: int = 15,
) -> List[Dict[str, Any]]:
    """Scan scheduled tasks, dependencies, and external events for:
    1. Direct time overlaps (task-to-task or task-to-external).
    2. Dependency order/timing violations (task starts before prerequisite finishes + buffer).
    3. Deadline violations (task scheduled after due_date).
    4. Slipped deadlines (uncompleted task scheduled in the past).
    """
    conflicts: List[Dict[str, Any]] = []
    buf_delta = timedelta(minutes=buffer_minutes)
    now_utc = _ensure_utc(current_time) if current_time else datetime.now(timezone.utc)

    task_map: Dict[int, Dict[str, Any]] = {}
    for st in scheduled_tasks:
        tid = st.get("id") or st.get("task_id")
        if tid is not None:
            task_map[int(tid)] = st

    dep_map: Dict[int, List[int]] = {}
    if dependencies:
        for k, v in dependencies.items():
            dep_map[int(k)] = [int(x) for x in v]
    for st in scheduled_tasks:
        tid = st.get("id") or st.get("task_id")
        if tid is not None and st.get("depends_on"):
            dep_map.setdefault(int(tid), []).extend([int(x) for x in st["depends_on"]])

    # 1. Overlap detection
    items: List[Tuple[datetime, datetime, Dict[str, Any], str]] = []
    for st in scheduled_tasks:
        if st.get("scheduled_start") and st.get("scheduled_end"):
            start = _ensure_utc(st["scheduled_start"])
            end = _ensure_utc(st["scheduled_end"])
            items.append((start, end, st, "task"))

    if external_events:
        for ev in external_events:
            if (ev.get("start") or ev.get("scheduled_start")) and (ev.get("end") or ev.get("scheduled_end")):
                start = _ensure_utc(ev.get("start") or ev.get("scheduled_start"))
                end = _ensure_utc(ev.get("end") or ev.get("scheduled_end"))
                items.append((start, end, ev, "external"))

    items.sort(key=lambda x: x[0])

    for i in range(len(items)):
        start_a, end_a, data_a, type_a = items[i]
        for j in range(i + 1, len(items)):
            start_b, end_b, data_b, type_b = items[j]
            if start_b < end_a:
                conflicts.append({
                    "conflict_type": "overlap",
                    "event_a": {"type": type_a, "id": data_a.get("id") or data_a.get("task_id"), "title": data_a.get("title")},
                    "event_b": {"type": type_b, "id": data_b.get("id") or data_b.get("task_id"), "title": data_b.get("title")},
                    "overlap_window": {"start": start_b.isoformat(), "end": min(end_a, end_b).isoformat()},
                })
            else:
                break

    # 2. Dependency timing violations
    for child_id, prereq_ids in dep_map.items():
        child = task_map.get(child_id)
        if not child or not child.get("scheduled_start"):
            continue
        child_start = _ensure_utc(child["scheduled_start"])

        for pid in prereq_ids:
            parent = task_map.get(pid)
            if not parent:
                continue
            if not parent.get("scheduled_end"):
                conflicts.append({
                    "conflict_type": "dependency_violation",
                    "task_id": child_id,
                    "task_title": child.get("title"),
                    "prerequisite_id": pid,
                    "prerequisite_title": parent.get("title"),
                    "issue": f"Task '{child.get('title')}' is scheduled, but prerequisite '{parent.get('title')}' has no scheduled time.",
                })
                continue

            parent_end = _ensure_utc(parent["scheduled_end"])
            if child_start < (parent_end + buf_delta):
                conflicts.append({
                    "conflict_type": "dependency_violation",
                    "task_id": child_id,
                    "task_title": child.get("title"),
                    "prerequisite_id": pid,
                    "prerequisite_title": parent.get("title"),
                    "issue": f"Task '{child.get('title')}' starts at {child_start.isoformat()} before prerequisite '{parent.get('title')}' completes with buffer at {(parent_end + buf_delta).isoformat()}.",
                })

    # 3. Deadline violations
    for st in scheduled_tasks:
        if st.get("due_date") and st.get("scheduled_end"):
            sched_end = _ensure_utc(st["scheduled_end"])
            raw_due = st["due_date"]
            if isinstance(raw_due, str):
                d_obj = date.fromisoformat(raw_due[:10])
                due_limit = datetime.combine(d_obj, time(23, 59, 59), tzinfo=timezone.utc)
            elif isinstance(raw_due, date) and not isinstance(raw_due, datetime):
                due_limit = datetime.combine(raw_due, time(23, 59, 59), tzinfo=timezone.utc)
            else:
                due_limit = _ensure_utc(raw_due)

            if sched_end > due_limit:
                conflicts.append({
                    "conflict_type": "deadline_exceeded",
                    "task_id": st.get("id") or st.get("task_id"),
                    "title": st.get("title"),
                    "due_date": str(st["due_date"]),
                    "scheduled_end": sched_end.isoformat(),
                    "issue": f"Task '{st.get('title')}' finishes after its due date ({st.get('due_date')}).",
                })

    # 4. Slipped uncompleted tasks
    for st in scheduled_tasks:
        status = str(st.get("status", "open")).lower().strip()
        if status not in ("done", "completed", "closed") and st.get("scheduled_end"):
            sched_end = _ensure_utc(st["scheduled_end"])
            if sched_end < now_utc:
                conflicts.append({
                    "conflict_type": "slipped_deadline",
                    "task_id": st.get("id") or st.get("task_id"),
                    "title": st.get("title"),
                    "scheduled_end": sched_end.isoformat(),
                    "slip_minutes": int((now_utc - sched_end).total_seconds() // 60),
                    "issue": f"Task '{st.get('title')}' scheduled end was in the past ({sched_end.isoformat()}) but task remains {status}.",
                })

    return conflicts

