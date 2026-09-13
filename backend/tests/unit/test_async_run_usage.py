"""
Regression check for the "Event loop is closed" bug class.

Celery worker tasks that touch async DB/HTTP clients MUST go through
app.worker.async_run.run_async(), which resets the loop-bound singletons
(Prometheus httpx client, Redis pool, AnomalyMonitor) and disposes the
SQLAlchemy engine pool before/after each asyncio.run(). A task that calls
asyncio.run() directly leaves connections bound to its own event loop; the
next task on that same Celery worker fork then crashes trying to reuse or
dispose them ("Event loop is closed" / "attached to a different loop").

Found live 2026-09-13 in embedding.py (embed_incident_task /
backfill_missing_embeddings_task used bare asyncio.run()) while running the
kind lab against a real CrashLoopBackOff.
"""
import ast
from pathlib import Path

TASKS_DIR = Path(__file__).parents[2] / "app" / "worker" / "tasks"


def _bare_asyncio_run_calls(path: Path) -> list[int]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    lines = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "run"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "asyncio"
        ):
            lines.append(node.lineno)
    return lines


def test_worker_tasks_use_run_async_not_bare_asyncio_run():
    """No file under app/worker/tasks/ may call asyncio.run() directly.

    Exceptions carved out deliberately (each is a short-lived, isolated loop
    that does not touch the shared engine/prometheus/redis singletons across
    tasks): analysis.py's SoftTimeLimitExceeded cleanup path.
    """
    allowed = {
        ("analysis.py", 125),  # 5s-capped cleanup after a hard timeout, see comment there
    }

    offenders = []
    for path in sorted(TASKS_DIR.glob("*.py")):
        for lineno in _bare_asyncio_run_calls(path):
            if (path.name, lineno) not in allowed:
                offenders.append(f"{path.name}:{lineno}")

    assert not offenders, (
        "Found bare asyncio.run() outside async_run.run_async() in worker "
        f"tasks: {offenders}. Use run_async() instead so the loop-bound "
        "singletons and engine pool get reset — see async_run.py docstring."
    )
