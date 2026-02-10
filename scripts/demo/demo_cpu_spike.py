#!/usr/bin/env python3
"""
CPU Spike Scenario Demo.

Demonstrates a traffic surge scenario causing CPU exhaustion.
Perfect for showing AIRRA's capacity planning and scaling recommendations.
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

SCENARIO_ID = "cpu_spike_traffic_surge"

STORY = """
# ⚡ CPU Spike from Traffic Surge

## Background
It's Black Friday. Your marketing team just launched a flash sale campaign via email
to 2 million customers. Nobody told engineering.

## What Happened?
At 10:00 AM, traffic to your payment service jumped from **800 req/s** to **3,500 req/s**.
Your 3 pods are configured for normal load, not 4x surge.

## The Symptoms
- 🔴 CPU usage: **98.5%** (expected: 45%) → **6.0σ deviation**
- 🔴 Request rate: **3,500 req/s** (expected: 800 req/s) → **5.5σ deviation**
- 🔴 P95 latency: **4.2s** (expected: 0.3s) → **5.0σ deviation**
- 🔴 Thread pool queue: **450 threads** (expected: 5) → **4.8σ deviation**

Requests are queueing up. Some users are seeing timeouts. Your SLA is at risk.

## What AIRRA Will Do
1. **Detect** the CPU and throughput anomalies
2. **Correlate** high traffic with poor performance
3. **Recommend** horizontal scaling (add more pods) and rate limiting
4. **Assess risk**: Scaling is low-risk, rate limiting might impact revenue

The key insight: This isn't a bug—it's a capacity problem. Scale out immediately.

---

**Press Enter to see AIRRA's real-time analysis...**
"""


async def main():
    """Run CPU spike demo with narrative."""
    console.clear()

    console.print(Panel(
        Markdown(STORY),
        title="[bold yellow]⚡ Traffic Surge Alert[/bold yellow]",
        border_style="yellow",
        box=box.DOUBLE,
    ))

    input()

    await run_scenario_demo(SCENARIO_ID, show_details=False)

    console.print()
    console.print(Panel.fit(
        "[bold cyan]📚 Learning Points[/bold cyan]\n\n"
        "1. **Capacity vs. Bug**: AIRRA distinguishes between code issues and capacity problems\n"
        "2. **Proactive scaling**: The hypothesis should suggest auto-scaling before manual intervention\n"
        "3. **Business context**: Rate limiting is technically correct but may impact revenue\n\n"
        "[dim]This scenario shows AIRRA's ability to recommend infrastructure changes "
        "rather than just code fixes.[/dim]",
        border_style="cyan",
    ))
    console.print()


if __name__ == "__main__":
    asyncio.run(main())
