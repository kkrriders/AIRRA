#!/usr/bin/env python3
"""
Latency Spike Scenario Demo.

Demonstrates a database performance issue causing cascading latency.
Perfect for showing AIRRA's dependency analysis and query optimization insights.
"""
import asyncio
import sys
from pathlib import Path

backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(backend_path))

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich import box

from run_demo import run_scenario_demo

console = Console()

SCENARIO_ID = "latency_spike_database"

STORY = """
# 🐌 Database Latency Incident

## Background
Your payment service has been humming along nicely. Then you deployed v2.4.0
which added a "transaction history" feature for users to view past payments.

## What Happened?
2 hours after deployment, users start complaining: "The app is so slow!"
Your monitoring shows the API is responding, but everything takes 10+ seconds.

## The Root Cause
The new feature added a complex JOIN query across 3 tables:
```sql
SELECT * FROM transactions t
JOIN users u ON t.user_id = u.id
JOIN merchants m ON t.merchant_id = m.id
WHERE u.id = ? ORDER BY t.created_at DESC
```

**Problem**: No index on `transactions.user_id`. The database is doing a full table scan
for every request. With 10M transaction records, this takes 7+ seconds per query.

## The Symptoms
- 🔴 P95 API latency: **8.5s** (expected: 0.4s) → **6.5σ deviation**
- 🔴 P99 API latency: **12.3s** (expected: 0.8s) → **6.8σ deviation**
- 🔴 Database query duration: **7.2s** (expected: 0.05s) → **7.0σ deviation**
- 🔴 DB connections active: **98/100** (expected: 15) → **5.5σ deviation**
- 🔴 Request throughput: **450 req/s** (down from 800) → **-4.2σ** (traffic dropping!)

The connection pool is exhausted because every query holds a connection for 7+ seconds.

## What AIRRA Will Do
1. **Detect** the latency spike and correlate with database metrics
2. **Identify** the database as the bottleneck (not app code)
3. **Recommend** immediate actions: add missing index, tune connection pool, rollback
4. **Provide context**: Recent deployment 2h ago introduced new database queries

---

**Press Enter to watch AIRRA diagnose this tricky performance issue...**
"""


async def main():
    """Run latency spike demo with narrative."""
    console.clear()

    console.print(Panel(
        Markdown(STORY),
        title="[bold red]🐌 Slow Database Queries[/bold red]",
        border_style="red",
        box=box.DOUBLE,
    ))

    input()

    await run_scenario_demo(SCENARIO_ID, show_details=False)

    console.print()
    console.print(Panel.fit(
        "[bold cyan]📚 Learning Points[/bold cyan]\n\n"
        "1. **Dependency analysis**: AIRRA traced the problem to the database layer, not app code\n"
        "2. **Deployment correlation**: The issue started exactly when v2.4.0 was deployed\n"
        "3. **Cascading effects**: Slow queries → pool exhaustion → traffic drop\n"
        "4. **Multi-layer metrics**: App latency + DB query time + connection pool all told the story\n\n"
        "[dim]This scenario demonstrates AIRRA's ability to diagnose performance issues "
        "that span multiple system layers.[/dim]",
        border_style="cyan",
    ))
    console.print()


if __name__ == "__main__":
    asyncio.run(main())
