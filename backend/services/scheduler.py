"""
Compass — Deterministic Dynamic Scheduling Engine.

Provides pure Python interval arithmetic for packing tasks into calendar time slots.
Guarantees 0% LLM hallucination in time calculations, working hour boundaries,
inter-task buffers, and deadline satisfaction.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
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
) -> Dict[str, Any]:
    """Deterministically allocate tasks into available time windows.

    Tasks are prioritized by:
      1. Priority weight (urgent > high > medium > low)
      2. Due date (earlier deadlines first)
      3. Duration (fitting tasks efficiently)

    Ensures:
      - No overlapping allocations.
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

    # Sort tasks according to scheduling strategy
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

    sorted_tasks = sorted(tasks, key=sort_key)

    # Make mutable list of free windows: list of [start, end]
    free_blocks: List[List[datetime]] = [[w.start, w.end] for w in available_windows]

    scheduled: List[Dict[str, Any]] = []
    unassigned: List[Dict[str, Any]] = []
    conflicts: List[Dict[str, Any]] = []

    buf_delta = timedelta(minutes=buffer_minutes)

    for task in sorted_tasks:
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

        placed = False
        for i, block in enumerate(free_blocks):
            b_start, b_end = block[0], block[1]
            if (b_end - b_start) < needed_delta:
                continue

            slot_start = b_start
            slot_end = slot_start + needed_delta

            # Check if this placement violates due date
            if due_limit and slot_end > due_limit:
                # Cannot place here or anywhere later for this task
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

            # Consume the slot + buffer from this free block
            new_start = slot_end + buf_delta
            if new_start < b_end:
                free_blocks[i] = [new_start, b_end]
            else:
                free_blocks.pop(i)

            placed = True
            break

        if not placed:
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


def detect_schedule_conflicts(
    scheduled_tasks: Sequence[Dict[str, Any]],
    external_events: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Scan scheduled tasks and external calendar events for overlaps or deadline violations."""
    conflicts: List[Dict[str, Any]] = []

    # Check internal overlaps
    items: List[Tuple[datetime, datetime, Dict[str, Any], str]] = []
    for st in scheduled_tasks:
        start = _ensure_utc(st["scheduled_start"])
        end = _ensure_utc(st["scheduled_end"])
        items.append((start, end, st, "task"))

    if external_events:
        for ev in external_events:
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

    return conflicts
