# AI Trading OS - Background Task Manager
"""
Runs long-running operations (like agent pipelines) in background threads
and exposes task status via a simple in-memory store.

Usage:
    from backend.task_manager import TaskManager

    task_id = TaskManager.start(analyze_fn)
    status = TaskManager.get(task_id)  # {"status": "running"|"done"|"error", "result": ...}
"""

from __future__ import annotations

import uuid
import threading
import traceback
from typing import Any, Callable, Optional

_store: dict[str, dict] = {}
_lock = threading.Lock()


class TaskManager:

    @staticmethod
    def start(fn: Callable[[], Any]) -> str:
        """Start a background task. Returns a task_id."""
        task_id = uuid.uuid4().hex[:12]

        with _lock:
            _store[task_id] = {"status": "running", "result": None, "error": None}

        def _run():
            try:
                import asyncio
                # If fn is a coroutine, run it
                if asyncio.iscoroutine(fn) or asyncio.iscoroutinefunction(fn):
                    # Run in a new event loop in this thread
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(fn())
                    loop.close()
                else:
                    result = fn()
                with _lock:
                    _store[task_id] = {"status": "done", "result": result, "error": None}
            except Exception as e:
                with _lock:
                    _store[task_id] = {
                        "status": "error",
                        "result": None,
                        "error": f"{e}\n{traceback.format_exc()}",
                    }

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        return task_id

    @staticmethod
    def get(task_id: str) -> Optional[dict]:
        """Get task status. Returns None if task not found."""
        with _lock:
            return _store.get(task_id)

    @staticmethod
    def cleanup(older_than_seconds: int = 300):
        """Remove completed tasks older than N seconds."""
        import time
        with _lock:
            # Simple cleanup: remove all done/error tasks
            to_delete = [
                tid for tid, v in _store.items()
                if v["status"] in ("done", "error")
            ]
            for tid in to_delete[-50:]:  # Keep last 50
                pass  # Keep history for now; implement TTL later
