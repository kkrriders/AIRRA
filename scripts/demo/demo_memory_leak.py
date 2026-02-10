#!/usr/bin/env python3
"""
Memory Leak Scenario Demo.

Demonstrates a realistic memory leak scenario with narrative commentary.
Perfect for presentations showing how AIRRA detects and diagnoses memory issues.
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

# Import the main demo runner
from run_demo import run_scenario_demo, get_scenario_details, console as main_console

console = Console()

SCENARIO_ID = "memory_leak_gradual"

# Narrative commentary
STORY = """
# 🧠 Memory Leak Incident Scenario

## Background
Your payment service has been running fine for weeks. But today, the on-call engineer
gets paged at 3 AM. Pods are OOM-killed and auto-restarting every few minutes.

## What Happened?
6 hours ago, you deployed version v2.3.1 which included:
- ✅ Redis connection pooling (for better performance)
- ✅ Refactored payment processing logic

The new Redis connection code looked innocent, but it had a subtle bug:
connections weren't being properly released back to the pool.

## The Symptoms
- 🔴 Memory usage: **8 GB** (expected: 2 GB) → **5.2σ deviation**
- 🔴 Heap allocations: **15M** (expected: 2M) → **4.8σ deviation**
- 🔴 Garbage collections: **5000** (expected: 500) → **4.5σ deviation**

The JVM is thrashing, trying to free memory that can't be freed.

## What AIRRA Will Do
1. **Detect** the anomalous memory metrics
2. **Hypothesize** possible root causes (memory leak, traffic surge, resource misconfiguration)
3. **Correlate** with recent deployment (v2.3.1 deployed 6 hours ago)
4. **Recommend** immediate actions (restart pods, rollback deployment, scale up)

---

**Press Enter to see AIRRA analyze this incident in real-time...**
"""


async def main():
    """Run memory leak demo with narrative."""
    console.clear()

    # Show story
    console.print(Panel(
        Markdown(STORY),
        title="[bold red]🚨 Memory Leak Crisis[/bold red]",
        border_style="red",
        box=box.DOUBLE,
    ))

    input()

    # Run the scenario
    await run_scenario_demo(SCENARIO_ID, show_details=False)

    # Post-analysis commentary
    console.print()
    console.print(Panel.fit(
        "[bold cyan]📚 Learning Points[/bold cyan]\n\n"
        "1. **Time correlation is key**: AIRRA linked the memory spike to the deployment 6h ago\n"
        "2. **Multi-metric analysis**: Memory + heap + GC all pointed to the same root cause\n"
        "3. **Prioritized actions**: Immediate mitigation (restart) vs. long-term fix (rollback)\n\n"
        "[dim]This scenario demonstrates AIRRA's ability to diagnose resource exhaustion "
        "issues and connect them to recent changes.[/dim]",
        border_style="cyan",
    ))
    console.print()


if __name__ == "__main__":
    asyncio.run(main())
