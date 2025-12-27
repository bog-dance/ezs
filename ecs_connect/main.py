#!/usr/bin/env python3
"""
EZS - Interactive CLI tool for connecting to ECS containers via SSM
"""

import sys
import os
import time
import argparse
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.align import Align
from rich.text import Text
from .config import REGIONS
from .aws_client import AWSClient
from .interactive import run_ecs_connect
from .ssm_session import (
    check_session_manager_plugin,
    start_ssh_session,
    start_container_session
)

console = Console()


def stream_live_logs(result: dict, profile: str = None):
    """Stream live logs from CloudWatch"""
    cluster = result['cluster']
    task = result['task']
    container = result['container']
    region = result['region']

    aws = AWSClient(region=region, profile=profile)
    container_name = container.get('name') if container else None

    if not container_name:
        console.print("[red]No container selected[/red]")
        return

    console.print(f"[cyan]Getting log configuration for {container_name}...[/cyan]")

    log_group = aws.get_log_group_for_task(task, container_name)
    log_stream = aws.get_log_stream_for_task(task, container_name)

    if not log_group or not log_stream:
        console.print("[red]Could not find CloudWatch logs configuration for this container.[/red]")
        console.print("[yellow]Make sure the container uses awslogs driver.[/yellow]")
        return

    console.print(f"[green]Log group:[/green] {log_group}")
    console.print(f"[green]Log stream:[/green] {log_stream}")
    console.print("[dim]Press Ctrl+C to stop streaming[/dim]\n")

    try:
        for event in aws.stream_log_events(log_group, log_stream):
            timestamp = event.get('timestamp', 0)
            message = event.get('message', '')
            dt = datetime.fromtimestamp(timestamp / 1000)
            time_str = dt.strftime('%H:%M:%S')
            console.print(f"[dim]{time_str}[/dim] {message}")
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped streaming.[/yellow]")


def download_logs(result: dict, profile: str = None):
    """Download logs from CloudWatch to ~/Downloads"""
    cluster = result['cluster']
    task = result['task']
    container = result['container']
    region = result['region']
    minutes = result.get('minutes', 60)

    aws = AWSClient(region=region, profile=profile)
    container_name = container.get('name') if container else None

    if not container_name:
        console.print("[red]No container selected[/red]")
        return

    console.print(f"[cyan]Getting log configuration for {container_name}...[/cyan]")

    log_group = aws.get_log_group_for_task(task, container_name)
    log_stream = aws.get_log_stream_for_task(task, container_name)

    if not log_group or not log_stream:
        console.print("[red]Could not find CloudWatch logs configuration for this container.[/red]")
        console.print("[yellow]Make sure the container uses awslogs driver.[/yellow]")
        return

    console.print(f"[green]Log group:[/green] {log_group}")
    console.print(f"[green]Log stream:[/green] {log_stream}")

    # Calculate time range
    end_time = int(time.time() * 1000)
    start_time = end_time - (minutes * 60 * 1000)

    console.print(f"[cyan]Fetching logs from last {minutes} minutes...[/cyan]")

    events = aws.get_log_events(log_group, log_stream, start_time=start_time, end_time=end_time, limit=10000)

    if not events:
        console.print("[yellow]No logs found in the specified time range.[/yellow]")
        return

    # Prepare download path
    downloads_dir = Path.home() / "Downloads"
    downloads_dir.mkdir(exist_ok=True)

    task_id = task.get('taskArn', '').split('/')[-1][:8]
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    filename = f"ecs_logs_{container_name}_{task_id}_{timestamp}.log"
    filepath = downloads_dir / filename

    # Write logs to file
    with open(filepath, 'w') as f:
        for event in events:
            ts = event.get('timestamp', 0)
            message = event.get('message', '')
            dt = datetime.fromtimestamp(ts / 1000)
            time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"{time_str} {message}\n")

    # Show centered success message
    message = Text()
    message.append("✓ Download complete\n\n", style="bold green")
    message.append(f"{len(events)}", style="bold cyan")
    message.append(" log entries\n\n", style="")
    message.append("Saved to:\n", style="dim")
    message.append(str(filepath), style="bold")
    message.append("\n\n", style="")
    message.append("Press Enter to continue...", style="dim italic")

    panel = Panel(
        Align.center(message),
        border_style="green",
        padding=(1, 4),
    )
    console.print()
    console.print(Align.center(panel))
    console.print()

    # Wait for user to press Enter
    input()


def main():
    """Main CLI workflow"""
    parser = argparse.ArgumentParser(description="EZS - ECS Container Access Tool")
    parser.add_argument('--profile', type=str, help='AWS profile to use')
    args = parser.parse_args()


    # Check prerequisites
    if not check_session_manager_plugin():
        sys.exit(1)

    # Fetch clusters from all regions
    console.print("[cyan]Fetching ECS clusters from all regions...[/cyan]")
    clusters = AWSClient.list_all_clusters(REGIONS, profile=args.profile)

    if not clusters:
        console.print("[red]No ECS clusters found in any region.[/red]")
        sys.exit(1)

    # Run the interactive UI (stays in Textual until SSH session)
    resume_context = None

    while True:
        result = run_ecs_connect(
            clusters=clusters,
            aws_client_class=AWSClient,
            profile=args.profile,
            resume_context=resume_context
        )

        if result is None:
            console.print("[yellow]Exiting.[/yellow]")
            sys.exit(0)

        # Save context for returning to Select Action after SSH/logs
        resume_context = {
            'cluster': result.get('cluster'),
            'service': result.get('service'),
            'task': result.get('task'),
            'container': result.get('container'),
            'instance_id': result.get('instance_id'),
        }

        # Start the appropriate session
        if result['type'] == 'ssh':
            start_ssh_session(result['instance_id'], result['region'])
        elif result['type'] == 'container':
            if result.get('container_id'):
                start_container_session(
                    result['instance_id'],
                    result['container_id'],
                    result['region']
                )
            else:
                console.print("[yellow]Container ID not available. Falling back to SSH.[/yellow]")
                start_ssh_session(result['instance_id'], result['region'])
        elif result['type'] == 'logs_live':
            stream_live_logs(result, args.profile)
        elif result['type'] == 'logs_download':
            download_logs(result, args.profile)


if __name__ == '__main__':
    try:
        main()
    except (KeyboardInterrupt, EOFError):
        # Ctrl+C or Ctrl+D
        console.print("\n[yellow]Exiting.[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]Unexpected error: {e}[/red]")
        sys.exit(1)
