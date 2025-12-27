#!/usr/bin/env python3
"""
ECS Connect - Interactive CLI tool for connecting to ECS containers via SSM
"""

import sys
import argparse
from rich.console import Console
from .config import REGIONS
from .aws_client import AWSClient
from .interactive import run_ecs_connect
from .ssm_session import (
    check_session_manager_plugin,
    start_ssh_session,
    start_container_session
)

console = Console()


def main():
    """Main CLI workflow"""
    parser = argparse.ArgumentParser(description="ECS Connect Tool")
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
    last_cluster = None

    while True:
        result = run_ecs_connect(
            clusters=clusters,
            aws_client_class=AWSClient,
            profile=args.profile,
            initial_cluster=last_cluster
        )

        if result is None:
            console.print("[yellow]Exiting.[/yellow]")
            sys.exit(0)

        # Remember cluster for next iteration
        last_cluster = result.get('cluster')

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
