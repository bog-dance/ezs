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
from textual.app import App, ComposeResult
from textual.widgets import Static, LoadingIndicator
from textual.containers import Container
from textual.worker import WorkerState
from .config import REGIONS, reload_regions
from .config_manager import config_exists
from .aws_client import AWSClient
from .interactive import run_ecs_connect
from .setup_wizard import run_setup_wizard
from .live_logs import run_live_logs, run_live_logs_with_loading, run_task_logs_with_loading
from .download_logs import run_download_logs, run_download_logs_with_loading
from .env_viewer import run_env_viewer
from .ssm_session import (
    check_session_manager_plugin,
    start_ssh_session,
    start_container_session
)

console = Console()


class ClusterLoadingApp(App):
    """Loading screen while fetching clusters"""

    CSS = """
    Screen {
        background: #08060d;
        align: center middle;
    }

    #loading-box {
        width: 50;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
    }

    #loading-box LoadingIndicator {
        width: 100%;
        height: 3;
        color: #a99fc4;
        background: transparent;
    }

    #loading-box Static {
        width: 100%;
        text-align: center;
        color: #a99fc4;
        background: transparent;
    }
    """

    def __init__(self, regions: dict, profile: str = None):
        super().__init__()
        self.regions = regions
        self.profile = profile
        self.clusters = None

    def compose(self) -> ComposeResult:
        yield Container(
            LoadingIndicator(),
            Static("Retrieving ECS clusters..."),
            id="loading-box"
        )

    def on_mount(self) -> None:
        self.run_worker(self._fetch_clusters, name="fetch_clusters", thread=True)

    def _fetch_clusters(self) -> list:
        return AWSClient.list_all_clusters(self.regions, profile=self.profile)

    def on_worker_state_changed(self, event) -> None:
        if event.worker.name != "fetch_clusters":
            return

        if event.state == WorkerState.SUCCESS:
            self.clusters = event.worker.result
            self.exit(result="success")
        elif event.state == WorkerState.ERROR:
            self.exit(result="error")


def stream_live_logs(result: dict, profile: str = None):
    """Stream live logs from CloudWatch with TUI"""
    task = result['task']
    container = result['container']
    region = result['region']

    aws = AWSClient(region=region, profile=profile)
    container_name = container.get('name') if container else None

    if not container_name:
        console.print("[red]No container selected[/red]")
        return

    # Run with loading screen
    run_live_logs_with_loading(
        aws_client=aws,
        task=task,
        container_name=container_name,
        title=f"Live Logs: {container_name}"
    )


def stream_task_logs(result: dict, profile: str = None):
    """Stream live logs for ALL containers in a task"""
    task = result['task']
    region = result['region']

    aws = AWSClient(region=region, profile=profile)
    task_id = task.get('taskArn', '').split('/')[-1]

    # Run with loading screen
    run_task_logs_with_loading(
        aws_client=aws,
        task=task,
        title=f"Task Logs: {task_id}"
    )


def view_env_vars(result: dict, profile: str = None):
    """View environment variables for a container"""
    from .env_viewer import run_env_viewer_with_loading
    task = result['task']
    container = result['container']
    region = result['region']
    cluster = result.get('cluster', {}).get('arn')
    service = result.get('service')

    container_name = container.get('name') if container else None

    if not container_name:
        return

    aws = AWSClient(region=region, profile=profile)

    run_env_viewer_with_loading(
        aws_client=aws,
        task=task,
        container_name=container_name,
        cluster=cluster,
        service=service
    )


def view_task_env_vars(result: dict, profile: str = None):
    """View environment variables for all containers in task"""
    from .env_viewer import run_env_viewer_with_loading
    task = result['task']
    region = result['region']
    cluster = result.get('cluster', {}).get('arn')
    service = result.get('service')

    containers = task.get('containers', [])

    if not containers:
        return

    # Use first container
    container_name = containers[0].get('name')
    aws = AWSClient(region=region, profile=profile)

    run_env_viewer_with_loading(
        aws_client=aws,
        task=task,
        container_name=container_name,
        cluster=cluster,
        service=service
    )


def download_logs(result: dict, profile: str = None):
    """Download logs from CloudWatch with TUI"""
    task = result['task']
    container = result['container']
    region = result['region']
    minutes = result.get('minutes', 60)

    aws = AWSClient(region=region, profile=profile)
    container_name = container.get('name') if container else None

    if not container_name:
        console.print("[red]No container selected[/red]")
        return

    run_download_logs_with_loading(
        aws_client=aws,
        task=task,
        container_name=container_name,
        minutes=minutes
    )


def main():
    """Main CLI workflow"""
    parser = argparse.ArgumentParser(description="EZS - ECS Container Access Tool")
    parser.add_argument('--profile', type=str, help='AWS profile to use')
    parser.add_argument('--configure', action='store_true', help='Configure AWS regions for ECS discovery')
    args = parser.parse_args()

    # Check prerequisites
    if not check_session_manager_plugin():
        sys.exit(1)

    # Check if first run or --configure flag
    if args.configure or not config_exists():
        if not config_exists():
            console.print("[cyan]First run detected. Starting setup wizard...[/cyan]")

        result = run_setup_wizard(profile=args.profile)

        if result is None:
            console.print("[yellow]Setup cancelled.[/yellow]")
            sys.exit(0)

        # Reload regions after setup
        regions = reload_regions()
        console.print(f"[green]Configuration saved. {len(result)} regions configured.[/green]")
    else:
        regions = REGIONS

    # Fetch clusters from configured regions with loading UI
    loader = ClusterLoadingApp(regions, profile=args.profile)
    result = loader.run()

    if result != "success" or not loader.clusters:
        console.print("[red]No ECS clusters found in any region.[/red]")
        sys.exit(1)

    clusters = loader.clusters

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
            # Cached data for faster resume
            'services': result.get('services'),
            'tasks': result.get('tasks'),
            'containers': result.get('containers'),
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
        elif result['type'] == 'task_logs_live':
            stream_task_logs(result, args.profile)
        elif result['type'] == 'env_vars':
            view_env_vars(result, args.profile)
        elif result['type'] == 'task_env_vars':
            view_task_env_vars(result, args.profile)
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
