#!/usr/bin/env python3
"""
AIRRA Incident Simulator Demo Script.

Beautiful CLI demo for running incident scenarios with real-time updates.

Usage:
    python scripts/demo/run_demo.py --list
    python scripts/demo/run_demo.py memory_leak_gradual
    python scripts/demo/run_demo.py --interactive
"""
import argparse
import asyncio
import sys
import time
from pathlib import Path

# Add backend to path for imports
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(backend_path))

import httpx
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
from rich.table import Table
from rich.live import Live
from rich.layout import Layout
from rich.text import Text
from rich import box

console = Console()


# ============================================
# Configuration
# ============================================

API_BASE_URL = "http://localhost:8000/api/v1"
API_KEY = "test-api-key"  # Default dev API key


# ============================================
# API Client Functions
# ============================================

async def list_scenarios():
    """Fetch list of available scenarios from API."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/simulator/scenarios",
            headers={"X-API-Key": API_KEY},
        )
        response.raise_for_status()
        return response.json()


async def get_scenario_details(scenario_id: str):
    """Get detailed information about a scenario."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/simulator/scenarios/{scenario_id}",
            headers={"X-API-Key": API_KEY},
        )
        response.raise_for_status()
        return response.json()


async def start_simulation(scenario_id: str, auto_analyze: bool = True):
    """Start a scenario simulation."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{API_BASE_URL}/simulator/scenarios/{scenario_id}/start",
            headers={"X-API-Key": API_KEY},
            json={
                "auto_analyze": auto_analyze,
                "execution_mode": "demo",
            },
        )
        response.raise_for_status()
        return response.json()


async def get_incident_details(incident_id: int):
    """Get incident details including hypotheses and actions."""
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{API_BASE_URL}/incidents/{incident_id}",
            headers={"X-API-Key": API_KEY},
        )
        response.raise_for_status()
        return response.json()


# ============================================
# Display Functions
# ============================================

def display_scenarios_list(scenarios):
    """Display available scenarios in a beautiful table."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]AIRRA Incident Simulator[/bold cyan]\n"
            "[dim]Pre-packaged realistic incident scenarios for demos and testing[/dim]",
            border_style="cyan",
        )
    )
    console.print()

    table = Table(
        title="📋 Available Scenarios",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
    )

    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Severity", justify="center")
    table.add_column("Difficulty", justify="center")
    table.add_column("Tags", style="dim")
    table.add_column("Duration", justify="right")

    for scenario in scenarios:
        # Color-code severity
        severity = scenario["severity"]
        if severity == "critical":
            severity_display = "[bold red]CRITICAL[/bold red]"
        elif severity == "high":
            severity_display = "[red]HIGH[/red]"
        elif severity == "medium":
            severity_display = "[yellow]MEDIUM[/yellow]"
        else:
            severity_display = "[green]LOW[/green]"

        # Color-code difficulty
        difficulty = scenario["difficulty"]
        if difficulty == "advanced":
            diff_display = "[red]●●●[/red]"
        elif difficulty == "intermediate":
            diff_display = "[yellow]●●○[/yellow]"
        else:
            diff_display = "[green]●○○[/green]"

        table.add_row(
            scenario["id"],
            scenario["name"],
            severity_display,
            diff_display,
            ", ".join(scenario["tags"]),
            f"{scenario['duration_seconds']}s",
        )

    console.print(table)
    console.print()
    console.print(
        "[dim]Run a scenario:[/dim] [cyan]python scripts/demo/run_demo.py <scenario_id>[/cyan]"
    )
    console.print()


def display_scenario_details(details):
    """Display detailed scenario information."""
    console.print()
    console.print(
        Panel.fit(
            f"[bold cyan]{details['name']}[/bold cyan]\n"
            f"[dim]{details['description']}[/dim]",
            border_style="cyan",
        )
    )
    console.print()

    # Info table
    info_table = Table(box=box.SIMPLE, show_header=False)
    info_table.add_column("Property", style="bold")
    info_table.add_column("Value")

    info_table.add_row("Service", details["service"])
    info_table.add_row("Severity", details["severity"].upper())
    info_table.add_row("Difficulty", details["difficulty"].capitalize())
    info_table.add_row("Duration", f"{details['duration_seconds']} seconds")
    info_table.add_row("Tags", ", ".join(details["tags"]))
    info_table.add_row("Expected Root Cause", details["expected_root_cause"])

    console.print(info_table)
    console.print()

    # Metrics table
    metrics_table = Table(
        title="📊 Anomalous Metrics",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold yellow",
    )

    metrics_table.add_column("Metric", style="cyan")
    metrics_table.add_column("Current", justify="right")
    metrics_table.add_column("Baseline", justify="right")
    metrics_table.add_column("Deviation", justify="right")

    for metric in details["metrics"]:
        if metric["is_anomalous"]:
            deviation_display = f"[red]{metric['deviation_sigma']:.1f}σ[/red]"
            metrics_table.add_row(
                metric["name"],
                f"{metric['value']} {metric['unit']}",
                f"{metric['baseline']} {metric['unit']}",
                deviation_display,
            )

    console.print(metrics_table)
    console.print()


def display_incident_analysis(incident):
    """Display incident analysis results."""
    console.print()
    console.print(
        Panel.fit(
            f"[bold green]✓ Incident Analysis Complete[/bold green]\n"
            f"[dim]Incident ID: {incident['id']}[/dim]",
            border_style="green",
        )
    )
    console.print()

    # Hypotheses
    if incident.get("hypotheses"):
        console.print("[bold yellow]🧠 Generated Hypotheses:[/bold yellow]")
        console.print()

        for i, hypothesis in enumerate(incident["hypotheses"][:3], 1):
            confidence_bar = "█" * int(hypothesis["confidence_score"] * 10)
            confidence_display = f"[cyan]{confidence_bar}[/cyan] {hypothesis['confidence_score']:.0%}"

            console.print(
                Panel(
                    f"[bold]{hypothesis['description']}[/bold]\n\n"
                    f"[dim]Category:[/dim] {hypothesis['category']}\n"
                    f"[dim]Confidence:[/dim] {confidence_display}\n"
                    f"[dim]Reasoning:[/dim] {hypothesis.get('llm_reasoning', 'N/A')[:150]}...",
                    title=f"Hypothesis #{i} (Rank: {hypothesis['rank']})",
                    border_style="yellow",
                    box=box.ROUNDED,
                )
            )

    # Actions
    if incident.get("actions"):
        console.print()
        console.print("[bold green]🔧 Recommended Actions:[/bold green]")
        console.print()

        for action in incident["actions"][:3]:
            risk_color = "red" if action["risk_level"] == "high" else "yellow" if action["risk_level"] == "medium" else "green"

            console.print(
                Panel(
                    f"[bold]{action['name']}[/bold]\n\n"
                    f"{action['description']}\n\n"
                    f"[dim]Type:[/dim] {action['action_type']}\n"
                    f"[dim]Risk:[/dim] [{risk_color}]{action['risk_level'].upper()}[/{risk_color}]\n"
                    f"[dim]Target:[/dim] {action['target_service']}/{action.get('target_resource', 'N/A')}",
                    border_style=risk_color,
                    box=box.ROUNDED,
                )
            )

    console.print()


# ============================================
# Demo Execution
# ============================================

async def run_scenario_demo(scenario_id: str, show_details: bool = True):
    """Run a complete scenario demo with beautiful output."""
    try:
        console.clear()

        # Step 1: Show scenario details
        if show_details:
            with console.status("[cyan]Loading scenario details...[/cyan]"):
                details = await get_scenario_details(scenario_id)

            display_scenario_details(details)

            console.print("[bold]Press Enter to start simulation...[/bold]", end="")
            input()
            console.print()

        # Step 2: Start simulation
        console.print(
            Panel.fit(
                "[bold yellow]🚀 Starting Simulation[/bold yellow]",
                border_style="yellow",
            )
        )
        console.print()

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TimeElapsedColumn(),
            console=console,
        ) as progress:
            task1 = progress.add_task("[cyan]Injecting metrics into mock service...", total=None)
            await asyncio.sleep(1)
            progress.update(task1, completed=True)

            task2 = progress.add_task("[cyan]Creating incident in database...", total=None)
            await asyncio.sleep(1)
            progress.update(task2, completed=True)

            task3 = progress.add_task("[cyan]Analyzing with LLM (generating hypotheses)...", total=None)

            # Actually start the simulation
            result = await start_simulation(scenario_id)

            progress.update(task3, completed=True)

            task4 = progress.add_task("[cyan]Generating remediation actions...", total=None)
            await asyncio.sleep(0.5)
            progress.update(task4, completed=True)

        console.print()
        console.print(
            Panel.fit(
                f"[bold green]✓ Simulation Started Successfully[/bold green]\n\n"
                f"[dim]Simulation ID:[/dim] [cyan]{result['simulation_id']}[/cyan]\n"
                f"[dim]Incident ID:[/dim] [cyan]{result['incident_id']}[/cyan]\n"
                f"[dim]Hypotheses:[/dim] {result['hypotheses_count']}\n"
                f"[dim]Actions:[/dim] {result['actions_count']}\n"
                f"[dim]Metrics Injected:[/dim] {'✓' if result['metrics_injected'] else '✗ (mock service offline)'}",
                border_style="green",
            )
        )
        console.print()

        # Step 3: Fetch and display incident details
        console.print("[dim]Fetching full incident details...[/dim]")
        incident = await get_incident_details(result["incident_id"])

        display_incident_analysis(incident)

        # Step 4: Demo complete
        console.print(
            Panel.fit(
                "[bold green]✓ Demo Complete![/bold green]\n\n"
                "[dim]The incident will auto-resolve after the scenario duration.[/dim]\n"
                f"[dim]View in UI:[/dim] [link]http://localhost:3000/incidents/{result['incident_id']}[/link]",
                border_style="green",
            )
        )
        console.print()

    except httpx.HTTPStatusError as e:
        console.print(f"[bold red]API Error:[/bold red] {e.response.status_code}")
        console.print(f"[dim]{e.response.text}[/dim]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[bold red]Error:[/bold red] {str(e)}")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)


async def interactive_mode():
    """Interactive mode for selecting scenarios."""
    console.clear()

    with console.status("[cyan]Loading scenarios...[/cyan]"):
        scenarios = await list_scenarios()

    display_scenarios_list(scenarios)

    console.print("[bold]Select a scenario by number or ID:[/bold]")
    for i, scenario in enumerate(scenarios, 1):
        console.print(f"  {i}. {scenario['id']} - {scenario['name']}")

    console.print()
    choice = console.input("[bold cyan]Enter your choice:[/bold cyan] ").strip()

    # Parse choice
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(scenarios):
            scenario_id = scenarios[idx]["id"]
        else:
            console.print("[red]Invalid choice[/red]")
            return
    else:
        scenario_id = choice

    await run_scenario_demo(scenario_id)


# ============================================
# Main CLI
# ============================================

async def main():
    parser = argparse.ArgumentParser(
        description="AIRRA Incident Simulator Demo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List all scenarios
  python scripts/demo/run_demo.py --list

  # Run a specific scenario
  python scripts/demo/run_demo.py memory_leak_gradual

  # Interactive mode
  python scripts/demo/run_demo.py --interactive
        """,
    )

    parser.add_argument(
        "scenario_id",
        nargs="?",
        help="Scenario ID to run (e.g., memory_leak_gradual)",
    )
    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List all available scenarios",
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Interactive mode for selecting scenarios",
    )
    parser.add_argument(
        "--no-details",
        action="store_true",
        help="Skip showing scenario details before running",
    )

    args = parser.parse_args()

    # List mode
    if args.list:
        with console.status("[cyan]Loading scenarios...[/cyan]"):
            scenarios = await list_scenarios()
        display_scenarios_list(scenarios)
        return

    # Interactive mode
    if args.interactive:
        await interactive_mode()
        return

    # Run specific scenario
    if args.scenario_id:
        await run_scenario_demo(args.scenario_id, show_details=not args.no_details)
        return

    # No arguments - show help
    parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
