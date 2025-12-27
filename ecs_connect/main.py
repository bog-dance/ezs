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
    fuzzy_select_service
)
from .ssm_session import (
    check_session_manager_plugin,
    get_container_id,
    start_ssh_session,
    start_container_session
)

console = Console()

def main():
    """Main CLI workflow"""
    parser = argparse.ArgumentParser(description="ECS Connect Tool")
    parser.add_argument('--profile', type=str, help='AWS profile to use')
    parser.add_argument('--service', type=str, help='Filter services by name')
    args = parser.parse_args()

    console.print("[bold blue]ECS Connect Tool[/bold blue]")
    console.print()

    # Check prerequisites
    if not check_session_manager_plugin():
        sys.exit(1)

    # Step 1: Select region
    region = select_region(REGIONS)
    if not region:
        console.print("[red]No region selected. Exiting.[/red]")
        sys.exit(0)

    console.print(f"[dim]Selected region: {region}[/dim]\n")

    # Initialize AWS client
    aws = AWSClient(region=region, profile=args.profile)

    # Step 2: Select cluster
    console.print("[cyan]Fetching ECS clusters...[/cyan]")
    clusters = aws.list_clusters()
    cluster = select_cluster(clusters)
    if not cluster:
        sys.exit(0)

    console.print(f"[dim]Selected cluster: {cluster.split('/')[-1]}[/dim]\n")

    # Step 3: Select service
    console.print("[cyan]Fetching services...[/cyan]")
    services = aws.list_services(cluster, service_name=args.service)

    if args.service and len(services) == 1:
        service = services[0]
    elif args.service and len(services) > 1:
        service = fuzzy_select_service(services)
    else:
        service = select_service(services)

    if not service:
        sys.exit(0)
    
    console.print(f"[dim]Selected service: {service.split('/')[-1]}[/dim]\n")
    
    # Step 4: Get running tasks
    console.print("[cyan]Fetching running tasks...[/cyan]")
    tasks = aws.list_tasks(cluster, service)
    if not tasks:
        console.print("[red]No running tasks found. Exiting.[/red]")
        sys.exit(1)
    
    task = select_task(tasks)
    if not task:
        sys.exit(0)
    
    console.print(f"[dim]Selected task: {task['taskArn'].split('/')[-1]}[/dim]\n")
    
    # Step 5: Get EC2 instance ID
    console.print("[cyan]Getting container instance...[/cyan]")
    instance_id = aws.get_container_instance_id(cluster, task)
    if not instance_id:
        console.print("[red]Could not determine EC2 instance. Exiting.[/red]")
        sys.exit(1)
    
    console.print(f"[dim]Instance ID: {instance_id}[/dim]\n")
    
    # Verify SSM access
    if not aws.verify_ssm_access(instance_id):
        console.print(f"[red]Instance {instance_id} is not accessible via SSM.[/red]")
        console.print("[yellow]Make sure the instance has SSM agent installed and IAM role attached.[/yellow]")
        sys.exit(1)
    
    # Step 6: Get service containers (exclude ecs-agent)
    containers = aws.get_task_containers(task, exclude_agent=True)
    if not containers:
        console.print("[yellow]No service containers found (only ecs-agent). Connecting to host.[/yellow]")
        start_ssh_session(instance_id, region)
        sys.exit(0)
    
    container = select_container(containers)
    if not container:
        sys.exit(0)
    
    console.print(f"[dim]Selected container: {container['name']}[/dim]\n")
    
    # Step 7: Ask if user wants to exec into container
    exec_container = confirm_container_exec()
    
    if not exec_container:
        # Connect to host only
        start_ssh_session(instance_id, region)
    else:
        # Get container ID and exec into it
        console.print("[cyan]Getting container ID from host...[/cyan]")
        container_id = get_container_id(instance_id, container['name'], region)
        
        if not container_id:
            console.print("[yellow]Could not get container ID. Falling back to SSH.[/yellow]")
            start_ssh_session(instance_id, region)
        else:
            start_container_session(instance_id, container_id, region)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled by user[/yellow]")
        sys.exit(0)
    except Exception as e:
        console.print(f"\n[red]Unexpected error: {e}[/red]")
        sys.exit(1)
