#!/usr/bin/env python3
"""
ECS Connect - Interactive CLI tool for connecting to ECS containers via SSM
"""

import sys
import argparse
from rich.console import Console
from .config import REGIONS
from .aws_client import AWSClient
from .interactive import (
    select_region,
    select_cluster,
    select_service,
    select_task,
    select_container,
    confirm_container_exec,
    fuzzy_select_service,
    BACK,
    BackSignal,
)
from .ssm_session import (
    check_session_manager_plugin,
    get_container_id,
    start_ssh_session,
    start_container_session
)

console = Console()


def main():
    """Main CLI workflow with back navigation"""
    parser = argparse.ArgumentParser(description="ECS Connect Tool")
    parser.add_argument('--profile', type=str, help='AWS profile to use')
    parser.add_argument('--service', type=str, help='Filter services by name')
    args = parser.parse_args()

    console.print("[bold blue]ECS Connect Tool[/bold blue]")
    console.print()

    # Check prerequisites
    if not check_session_manager_plugin():
        sys.exit(1)

    # State variables
    region = None
    aws = None
    clusters = None
    cluster = None
    services = None
    service = None
    tasks = None
    task = None
    instance_id = None
    containers = None
    container = None

    step = 1

    while True:
        if step == 1:
            # Select region
            region = select_region(REGIONS)
            if not region:
                console.print("[yellow]Exiting.[/yellow]")
                sys.exit(0)
            console.print(f"[dim]Selected region: {region}[/dim]\n")
            aws = AWSClient(region=region, profile=args.profile)
            step = 2

        elif step == 2:
            # Select cluster
            console.print("[cyan]Fetching ECS clusters...[/cyan]")
            clusters = aws.list_clusters()
            cluster = select_cluster(clusters)
            if cluster is None:
                sys.exit(0)
            if isinstance(cluster, BackSignal):
                step = 1
                continue
            console.print(f"[dim]Selected cluster: {cluster.split('/')[-1]}[/dim]\n")
            step = 3

        elif step == 3:
            # Select service
            console.print("[cyan]Fetching services...[/cyan]")
            services = aws.list_services(cluster, service_name=args.service)

            if args.service and len(services) == 1:
                service = services[0]
            elif args.service and len(services) > 1:
                service = fuzzy_select_service(services)
            else:
                service = select_service(services)

            if service is None:
                sys.exit(0)
            if isinstance(service, BackSignal):
                step = 2
                continue
            console.print(f"[dim]Selected service: {service.split('/')[-1]}[/dim]\n")
            step = 4

        elif step == 4:
            # Select task
            console.print("[cyan]Fetching running tasks...[/cyan]")
            tasks = aws.list_tasks(cluster, service)
            if not tasks:
                console.print("[red]No running tasks found.[/red]")
                step = 3
                continue

            task = select_task(tasks)
            if task is None:
                sys.exit(0)
            if isinstance(task, BackSignal):
                step = 3
                continue
            console.print(f"[dim]Selected task: {task['taskArn'].split('/')[-1]}[/dim]\n")
            step = 5

        elif step == 5:
            # Get instance and containers
            console.print("[cyan]Getting container instance...[/cyan]")
            instance_id = aws.get_container_instance_id(cluster, task)
            if not instance_id:
                console.print("[red]Could not determine EC2 instance.[/red]")
                step = 4
                continue

            console.print(f"[dim]Instance ID: {instance_id}[/dim]\n")

            if not aws.verify_ssm_access(instance_id):
                console.print(f"[red]Instance {instance_id} is not accessible via SSM.[/red]")
                console.print("[yellow]Make sure the instance has SSM agent installed and IAM role attached.[/yellow]")
                step = 4
                continue

            containers = aws.get_task_containers(task, exclude_agent=True)
            if not containers:
                console.print("[yellow]No service containers found (only ecs-agent). Connecting to host.[/yellow]")
                start_ssh_session(instance_id, region)
                sys.exit(0)

            container = select_container(containers)
            if container is None:
                sys.exit(0)
            if isinstance(container, BackSignal):
                step = 4
                continue
            console.print(f"[dim]Selected container: {container['name']}[/dim]\n")
            step = 6

        elif step == 6:
            # Confirm and connect
            exec_container = confirm_container_exec()
            if isinstance(exec_container, BackSignal):
                step = 5
                continue

            if not exec_container:
                start_ssh_session(instance_id, region)
            else:
                console.print("[cyan]Getting container ID from host...[/cyan]")
                container_id = get_container_id(instance_id, container['name'], region)

                if not container_id:
                    console.print("[yellow]Could not get container ID. Falling back to SSH.[/yellow]")
                    start_ssh_session(instance_id, region)
                else:
                    start_container_session(instance_id, container_id, region)

            # After session ends, return to service selection
            console.print("\n[dim]Session ended. Returning to menu...[/dim]\n")
            step = 3
            continue


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
