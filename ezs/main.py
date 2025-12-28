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
from .config import REGIONS, reload_regions
from .config_manager import config_exists
from .aws_client import AWSClient
from .interactive import run_ecs_connect
from .setup_wizard import run_setup_wizard
from .live_logs import run_live_logs
from .download_logs import run_download_logs
from .env_viewer import run_env_viewer
from .ssm_session import (
    check_session_manager_plugin,
    start_ssh_session,
    start_container_session
)

console = Console()


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

    console.print(f"[cyan]Getting log configuration for {container_name}...[/cyan]")

    log_group = aws.get_log_group_for_task(task, container_name)
    log_stream = aws.get_log_stream_for_task(task, container_name)

    if not log_group or not log_stream:
        console.print("[red]Could not find CloudWatch logs configuration for this container.[/red]")
        console.print("[yellow]Make sure the container uses awslogs driver.[/yellow]")
        return

    # Run the Live Logs TUI (single source)
    source = {
        'container': container_name,
        'log_group': log_group,
        'log_stream': log_stream
    }
    run_live_logs(
        log_sources=[source],
        aws_client=aws,
        title=f"Live Logs: {container_name}",
    )


def stream_task_logs(result: dict, profile: str = None):
    """Stream live logs for ALL containers in a task"""
    task = result['task']
    region = result['region']

    aws = AWSClient(region=region, profile=profile)
    task_id = task.get('taskArn', '').split('/')[-1]

    console.print(f"[cyan]Getting log configuration for task {task_id}...[/cyan]")

    log_sources = aws.get_all_container_log_configs(task)

    if not log_sources:
        console.print("[red]Could not find any CloudWatch logs configuration for this task.[/red]")
        return

    console.print(f"[green]Found {len(log_sources)} log streams.[/green]")

    run_live_logs(
        log_sources=log_sources,
        aws_client=aws,
        title=f"Task Logs: {task_id}",
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
    task_def_arn = task.get('taskDefinitionArn')

    if not container_name:
        console.print("[red]No container selected[/red]")
        return

    aws = AWSClient(region=region, profile=profile)
    env_vars = aws.get_container_env_vars(task, container_name)

    if not env_vars:
        console.print("[yellow]No environment variables found (or error fetching them).[/yellow]")
        env_vars = {}

    run_env_viewer(
        aws_client=aws,
        cluster=cluster,
        service=service,
        task_def_arn=task_def_arn,
        container_name=container_name,
        env_vars=env_vars
    )


def view_task_env_vars(result: dict, profile: str = None):
    """View environment variables for all containers in task"""
    # For now, just pick first container and show editor
    task = result['task']
    region = result['region']
    cluster = result.get('cluster', {}).get('arn')
    service = result.get('service')

    aws = AWSClient(region=region, profile=profile)
    containers = task.get('containers', [])

    if not containers:
        console.print("[red]No containers found in task[/red]")
        return

    # Use first container
    container_name = containers[0].get('name')
    task_def_arn = task.get('taskDefinitionArn')
    env_vars = aws.get_container_env_vars(task, container_name)

    if not env_vars:
        env_vars = {}

    run_env_viewer(
        aws_client=aws,
        cluster=cluster,
        service=service,
        task_def_arn=task_def_arn,
        container_name=container_name,
        env_vars=env_vars
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

    console.print(f"[cyan]Getting log configuration for {container_name}...[/cyan]")

    log_group = aws.get_log_group_for_task(task, container_name)
    log_stream = aws.get_log_stream_for_task(task, container_name)

    if not log_group or not log_stream:
        console.print("[red]Could not find CloudWatch logs configuration for this container.[/red]")
        console.print("[yellow]Make sure the container uses awslogs driver.[/yellow]")
        return

    task_id = task.get('taskArn', '').split('/')[-1][:8]

    # Run the Download Logs TUI
    run_download_logs(
        log_group=log_group,
        log_stream=log_stream,
        aws_client=aws,
        container_name=container_name,
        task_id=task_id,
        minutes=minutes,
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

    # Fetch clusters from configured regions
    console.print("[cyan]Fetching ECS clusters from all regions...[/cyan]")
    clusters = AWSClient.list_all_clusters(regions, profile=args.profile)

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
