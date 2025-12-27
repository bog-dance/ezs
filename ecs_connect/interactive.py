"""Interactive CLI prompts using questionary"""

import questionary
from typing import List, Optional
from .aws_client import extract_name_from_arn


def select_region(regions: List[str]) -> Optional[str]:
    """Prompt user to select AWS region"""
    return questionary.select(
        "Select AWS region:",
        choices=regions
    ).ask()


def select_cluster(clusters: List[str]) -> Optional[str]:
    """Prompt user to select ECS cluster"""
    if not clusters:
        print("No clusters found in this region")
        return None
    
    # Display friendly names but return full ARN
    choices = [
        questionary.Choice(
            title=extract_name_from_arn(cluster),
            value=cluster
        )
        for cluster in clusters
    ]
    
    return questionary.select(
        "Select ECS cluster:",
        choices=choices
    ).ask()


def select_service(services: List[str]) -> Optional[str]:
    """Prompt user to select ECS service"""
    if not services:
        print("No services found in this cluster")
        return None
    
    choices = [
        questionary.Choice(
            title=extract_name_from_arn(service),
            value=service
        )
        for service in services
    ]
    
    return questionary.select(
        "Select ECS service:",
        choices=choices
    ).ask()


def select_task(tasks: List[dict]) -> Optional[dict]:
    """Prompt user to select task (if multiple running)"""
    if not tasks:
        print("No running tasks found for this service")
        return None
    
    if len(tasks) == 1:
        # Auto-select if only one task
        return tasks[0]
    
    choices = [
        questionary.Choice(
            title=f"{extract_name_from_arn(task['taskArn'])} (started: {task.get('startedAt', 'unknown')})",
            value=task
        )
        for task in tasks
    ]
    
    return questionary.select(
        "Multiple tasks running. Select one:",
        choices=choices
    ).ask()


def select_container(containers: List[dict]) -> Optional[dict]:
    """Prompt user to select container"""
    if not containers:
        print("No service containers found in this task")
        return None
    
    if len(containers) == 1:
        # Auto-select if only one container
        return containers[0]
    
    choices = [
        questionary.Choice(
            title=f"{container['name']} (status: {container.get('lastStatus', 'unknown')})",
            value=container
        )
        for container in containers
    ]
    
    return questionary.select(
        "Multiple containers found. Select one:",
        choices=choices
    ).ask()


def confirm_container_exec() -> bool:
    """Ask user if they want to exec into container"""
    return questionary.confirm(
        "Connect to container? (No = SSH to host only)",
        default=True
    ).ask()
