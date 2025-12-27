"""Interactive CLI prompts using InquirerPy"""

from InquirerPy import inquirer
from InquirerPy.base.control import Choice
from typing import List, Optional
from .aws_client import extract_name_from_arn


def select_region(regions: List[str]) -> Optional[str]:
    """Prompt user to select AWS region"""
    if not regions:
        return None
    return inquirer.select(
        message="Select AWS region:",
        choices=regions,
        multiselect=False,
    ).execute()


def select_cluster(clusters: List[str]) -> Optional[str]:
    """Prompt user to select ECS cluster"""
    if not clusters:
        print("No clusters found in this region")
        return None
    
    choices = [
        Choice(value=cluster, name=extract_name_from_arn(cluster))
        for cluster in clusters
    ]
    
    return inquirer.select(
        message="Select ECS cluster:",
        choices=choices,
        multiselect=False,
    ).execute()


def select_service(services: List[str]) -> Optional[str]:
    """Prompt user to select ECS service"""
    if not services:
        print("No services found in this cluster")
        return None
    
    choices = [
        Choice(value=service, name=extract_name_from_arn(service))
        for service in services
    ]
    
    return inquirer.select(
        message="Select ECS service:",
        choices=choices,
        multiselect=False,
    ).execute()


def select_task(tasks: List[dict]) -> Optional[dict]:
    """Prompt user to select task (if multiple running)"""
    if not tasks:
        print("No running tasks found for this service")
        return None
    
    if len(tasks) == 1:
        return tasks[0]
    
    choices = [
        Choice(
            value=task,
            name=f"{extract_name_from_arn(task['taskArn'])} (started: {task.get('startedAt', 'unknown')})"
        )
        for task in tasks
    ]
    
    return inquirer.select(
        message="Multiple tasks running. Select one:",
        choices=choices,
        multiselect=False,
    ).execute()


def select_container(containers: List[dict]) -> Optional[dict]:
    """Prompt user to select container"""
    if not containers:
        print("No service containers found in this task")
        return None
    
    if len(containers) == 1:
        return containers[0]
    
    choices = [
        Choice(
            value=container,
            name=f"{container['name']} (status: {container.get('lastStatus', 'unknown')})"
        )
        for container in containers
    ]
    
    return inquirer.select(
        message="Multiple containers found. Select one:",
        choices=choices,
        multiselect=False,
    ).execute()


def confirm_container_exec() -> bool:
    """Ask user if they want to exec into container"""
    return inquirer.confirm(
        message="Connect to container? (No = SSH to host only)",
        default=True
    ).execute()
