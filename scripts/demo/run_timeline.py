#!/usr/bin/env python3
"""
AIRRA Timeline Orchestrator.

Runs multiple incident scenarios automatically at scheduled times to create
a realistic incident stream. Supports both pre-defined scenarios and
LLM-generated variations.

Usage:
    # Run a pre-configured timeline
    python scripts/demo/run_timeline.py --timeline busy_day

    # List available timelines
    python scripts/demo/run_timeline.py --list

    # Custom timeline from JSON file
    python scripts/demo/run_timeline.py --file my_timeline.json
"""
import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Dict, List

# Add backend to path
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(backend_path))

import httpx
from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

console = Console()

# Configuration
API_BASE_URL = "http://localhost:8000/api/v1"
API_KEY = "test-api-key"


# ============================================
# Timeline Configuration Models
# ============================================

class TimelineIncident:
    """Single incident in a timeline."""

    def __init__(self, data: Dict):
        self.delay_seconds = data["delay_seconds"]
        self.type = data["type"]  # "predefined" or "llm_generated"
        self.comment = data.get("comment", "")

        if self.type == "predefined":
            self.scenario_id = data["scenario_id"]
        elif self.type == "llm_generated":
            self.llm_prompt = data["llm_prompt"]
            self.service_name = data.get("service_name", "payment-service")
            self.expected_severity = data.get("expected_severity", "medium")

    def __repr__(self):
        if self.type == "predefined":
            return f"TimelineIncident(predefined, {self.scenario_id}, +{self.delay_seconds}s)"
        else:
            return f"TimelineIncident(llm_generated, +{self.delay_seconds}s)"


class TimelineConfig:
    """Timeline configuration loaded from JSON."""

    def __init__(self, data: Dict):
        self.name = data["name"]
        self.description = data["description"]
        self.duration_minutes = data["duration_minutes"]
        self.incidents = [TimelineIncident(i) for i in data["incidents"]]

    @classmethod
    def from_file(cls, filepath: Path) -> "TimelineConfig":
        """Load timeline from JSON file."""
        with open(filepath, "r") as f:
            data = json.load(f)
        return cls(data)


# ============================================
# API Functions
# ============================================

async def start_predefined_scenario(scenario_id: str) -> Dict:
    """Start a pre-defined scenario via API."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{API_BASE_URL}/simulator/scenarios/{scenario_id}/start",
            headers={"X-API-Key": API_KEY},
            json={"auto_analyze": True, "execution_mode": "demo"},
        )
        response.raise_for_status()
        return response.json()


async def start_llm_generated_scenario(
    llm_prompt: str,
    service_name: str,
    severity: str
) -> Dict:
    """Start an LLM-generated scenario."""
    # For now, we'll use the quick_incident API with a note
    # In the future, we could add a dedicated /simulator/generate endpoint
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{API_BASE_URL}/quick-incident",
            headers={"X-API-Key": API_KEY},
            json={
                "service_name": service_name,
                "title": f"[LLM Generated] Incident",
                "description": f"Generated from prompt: {llm_prompt}",
                "severity": severity,
                "context": {
                    "generated_by": "llm_timeline",
                    "generation_prompt": llm_prompt,
                },
            },
        )
        response.raise_for_status()
        return response.json()


# ============================================
# Timeline Execution
# ============================================

class IncidentTracker:
    """Tracks incidents created during timeline."""

    def __init__(self):
        self.incidents: List[Dict] = []
        self.start_time = datetime.utcnow()

    def add(self, incident: Dict, incident_type: str, comment: str):
        """Add a tracked incident."""
        self.incidents.append({
            "incident_id": incident.get("id") or incident.get("incident_id"),
            "scenario_id": incident.get("scenario_id", "N/A"),
            "type": incident_type,
            "comment": comment,
            "created_at": datetime.utcnow(),
            "elapsed_seconds": (datetime.utcnow() - self.start_time).total_seconds(),
            "status": incident.get("status", "unknown"),
            "hypotheses_count": incident.get("hypotheses_count", 0),
            "actions_count": incident.get("actions_count", 0),
        })

    def get_summary_table(self) -> Table:
        """Generate summary table of all incidents."""
        table = Table(
            title="📊 Timeline Execution Summary",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold cyan",
        )

        table.add_column("#", style="dim", no_wrap=True)
        table.add_column("Time", style="cyan")
        table.add_column("Type", style="yellow")
        table.add_column("Scenario/Comment", style="white")
        table.add_column("Incident ID", justify="center")
        table.add_column("Hypotheses", justify="center")
        table.add_column("Actions", justify="center")

        for idx, inc in enumerate(self.incidents, 1):
            elapsed_min = int(inc["elapsed_seconds"] // 60)
            elapsed_sec = int(inc["elapsed_seconds"] % 60)
            time_str = f"+{elapsed_min:02d}:{elapsed_sec:02d}"

            incident_type = inc["type"]
            type_display = "📦 Pre-defined" if incident_type == "predefined" else "🤖 LLM Generated"

            comment = inc["comment"] if inc["comment"] else inc["scenario_id"]

            table.add_row(
                str(idx),
                time_str,
                type_display,
                comment[:50],
                str(inc["incident_id"]),
                str(inc["hypotheses_count"]),
                str(inc["actions_count"]),
            )

        return table


async def run_timeline(config: TimelineConfig):
    """Execute a timeline configuration."""
    console.clear()

    # Show timeline header
    console.print(Panel.fit(
        f"[bold cyan]{config.name}[/bold cyan]\n"
        f"[dim]{config.description}[/dim]\n\n"
        f"Duration: [yellow]{config.duration_minutes}[/yellow] minutes\n"
        f"Incidents: [yellow]{len(config.incidents)}[/yellow] scenarios",
        border_style="cyan",
        title="🎬 Timeline Starting",
    ))
    console.print()

    tracker = IncidentTracker()
    start_time = datetime.utcnow()

    # Sort incidents by delay
    sorted_incidents = sorted(config.incidents, key=lambda x: x.delay_seconds)

    # Display timeline schedule
    schedule_table = Table(
        title="📅 Incident Schedule",
        box=box.SIMPLE,
        show_header=True,
        header_style="bold magenta",
    )
    schedule_table.add_column("Time", style="cyan")
    schedule_table.add_column("Type", style="yellow")
    schedule_table.add_column("Description")

    for inc in sorted_incidents:
        min_sec = f"+{inc.delay_seconds // 60:02d}:{inc.delay_seconds % 60:02d}"
        inc_type = "📦 Pre-defined" if inc.type == "predefined" else "🤖 LLM Generated"
        desc = inc.comment or (inc.scenario_id if inc.type == "predefined" else "LLM scenario")
        schedule_table.add_row(min_sec, inc_type, desc[:60])

    console.print(schedule_table)
    console.print()

    console.print("[bold]Press Enter to start timeline...[/bold]", end="")
    input()
    console.print()

    # Execute timeline
    last_delay = 0

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:

        timeline_task = progress.add_task(
            f"[cyan]Timeline Progress (0/{len(sorted_incidents)} incidents)",
            total=len(sorted_incidents)
        )

        for idx, incident_config in enumerate(sorted_incidents, 1):
            # Wait for scheduled time
            wait_time = incident_config.delay_seconds - last_delay
            if wait_time > 0:
                wait_task = progress.add_task(
                    f"[dim]Waiting {wait_time}s until next incident...",
                    total=wait_time
                )
                for _ in range(wait_time):
                    await asyncio.sleep(1)
                    progress.update(wait_task, advance=1)
                progress.remove_task(wait_task)

            # Trigger incident
            progress.update(timeline_task, description=f"[cyan]Triggering incident {idx}/{len(sorted_incidents)}")

            try:
                if incident_config.type == "predefined":
                    console.print(
                        f"[green]▶[/green] Starting predefined scenario: "
                        f"[bold]{incident_config.scenario_id}[/bold]"
                    )
                    result = await start_predefined_scenario(incident_config.scenario_id)
                    tracker.add(result, "predefined", incident_config.comment)
                    console.print(
                        f"  [dim]→ Incident ID: {result.get('incident_id')}, "
                        f"Hypotheses: {result.get('hypotheses_count', 0)}, "
                        f"Actions: {result.get('actions_count', 0)}[/dim]"
                    )

                elif incident_config.type == "llm_generated":
                    console.print(
                        f"[yellow]▶[/yellow] Generating LLM scenario...\n"
                        f"  [dim]Prompt: {incident_config.llm_prompt[:80]}...[/dim]"
                    )
                    result = await start_llm_generated_scenario(
                        incident_config.llm_prompt,
                        incident_config.service_name,
                        incident_config.expected_severity,
                    )
                    tracker.add(result, "llm_generated", incident_config.comment)
                    console.print(
                        f"  [dim]→ Incident ID: {result.get('id')}, "
                        f"Hypotheses: {len(result.get('hypotheses', []))}, "
                        f"Actions: {len(result.get('actions', []))}[/dim]"
                    )

                console.print()

            except Exception as e:
                console.print(f"[red]✗ Failed to trigger incident: {str(e)}[/red]")
                console.print()

            progress.update(timeline_task, advance=1)
            progress.update(
                timeline_task,
                description=f"[cyan]Timeline Progress ({idx}/{len(sorted_incidents)} incidents)"
            )

            last_delay = incident_config.delay_seconds

    # Show summary
    console.print()
    console.print(Panel.fit(
        "[bold green]✓ Timeline Execution Complete[/bold green]\n\n"
        f"Total Incidents Created: [cyan]{len(tracker.incidents)}[/cyan]\n"
        f"Execution Time: [cyan]{(datetime.utcnow() - start_time).total_seconds():.1f}[/cyan] seconds",
        border_style="green",
    ))
    console.print()

    console.print(tracker.get_summary_table())
    console.print()

    console.print(
        f"[dim]View incidents in UI:[/dim] [link]http://localhost:3000/incidents[/link]"
    )
    console.print()


# ============================================
# CLI
# ============================================

def list_timelines():
    """List available timeline configurations."""
    timeline_dir = Path(__file__).parent / "timeline_configs"

    if not timeline_dir.exists():
        console.print("[yellow]No timeline configurations found.[/yellow]")
        return

    console.print()
    console.print(Panel.fit(
        "[bold cyan]Available Timeline Configurations[/bold cyan]\n"
        "[dim]Pre-packaged incident timelines for demos[/dim]",
        border_style="cyan",
    ))
    console.print()

    table = Table(
        title="📅 Timelines",
        box=box.ROUNDED,
        show_header=True,
        header_style="bold magenta",
    )

    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name", style="bold")
    table.add_column("Duration", justify="center")
    table.add_column("Incidents", justify="center")
    table.add_column("Description")

    for json_file in sorted(timeline_dir.glob("*.json")):
        try:
            config = TimelineConfig.from_file(json_file)
            table.add_row(
                json_file.stem,
                config.name,
                f"{config.duration_minutes} min",
                str(len(config.incidents)),
                config.description[:60] + "..." if len(config.description) > 60 else config.description,
            )
        except Exception as e:
            console.print(f"[red]Error loading {json_file.name}: {str(e)}[/red]")

    console.print(table)
    console.print()
    console.print(
        "[dim]Run a timeline:[/dim] [cyan]python scripts/demo/run_timeline.py --timeline <id>[/cyan]"
    )
    console.print()


async def main():
    parser = argparse.ArgumentParser(
        description="AIRRA Timeline Orchestrator - Run incident scenarios automatically",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available timelines
  python scripts/demo/run_timeline.py --list

  # Run a pre-configured timeline
  python scripts/demo/run_timeline.py --timeline busy_day
  python scripts/demo/run_timeline.py --timeline incident_storm

  # Run custom timeline from file
  python scripts/demo/run_timeline.py --file my_timeline.json
        """,
    )

    parser.add_argument(
        "--list",
        "-l",
        action="store_true",
        help="List available timeline configurations",
    )
    parser.add_argument(
        "--timeline",
        "-t",
        help="Timeline ID to run (e.g., busy_day, incident_storm)",
    )
    parser.add_argument(
        "--file",
        "-f",
        type=Path,
        help="Path to custom timeline JSON file",
    )

    args = parser.parse_args()

    # List mode
    if args.list:
        list_timelines()
        return

    # Run timeline
    if args.timeline:
        timeline_dir = Path(__file__).parent / "timeline_configs"
        timeline_file = timeline_dir / f"{args.timeline}.json"

        if not timeline_file.exists():
            console.print(f"[red]Timeline not found: {args.timeline}[/red]")
            console.print(f"[dim]Use --list to see available timelines[/dim]")
            sys.exit(1)

        config = TimelineConfig.from_file(timeline_file)
        await run_timeline(config)
        return

    # Custom file
    if args.file:
        if not args.file.exists():
            console.print(f"[red]File not found: {args.file}[/red]")
            sys.exit(1)

        config = TimelineConfig.from_file(args.file)
        await run_timeline(config)
        return

    # No arguments - show help
    parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())
