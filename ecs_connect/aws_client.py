"""AWS API client wrappers"""

import boto3
from typing import List, Dict, Optional
from rich.console import Console

console = Console()


class AWSClient:
    def __init__(self, region: str, profile: Optional[str] = None):
        """Initialize AWS clients for given region"""
        session = boto3.Session(region_name=region, profile_name=profile)
        self.ecs = session.client('ecs')
        self.ec2 = session.client('ec2')
        self.ssm = session.client('ssm')
        self.region = region

    def list_clusters(self) -> List[str]:
        """List all ECS clusters in region"""
        try:
            response = self.ecs.list_clusters()
            # Return ARNs, we'll extract names for display
            return response.get('clusterArns', [])
        except Exception as e:
            console.print(f"[red]Error listing clusters: {e}[/red]")
            return []

    def list_services(self, cluster: str, service_name: Optional[str] = None) -> List[str]:
        """List all services in ECS cluster, optionally filtering by name."""
        try:
            paginator = self.ecs.get_paginator('list_services')
            pages = paginator.paginate(cluster=cluster)

            service_arns = []
            for page in pages:
                service_arns.extend(page.get('serviceArns', []))

            if not service_name:
                service_arns.sort(key=extract_name_from_arn)
                return service_arns

            filtered_arns = [
                arn for arn in service_arns
                if service_name.lower() in extract_name_from_arn(arn).lower()
            ]

            filtered_arns.sort(key=extract_name_from_arn)
            return filtered_arns

        except Exception as e:
            console.print(f"[red]Error listing services: {e}[/red]")
            return []

    def list_tasks(self, cluster: str, service: str) -> List[Dict]:
        """List running tasks for service with details"""
        try:
            # Get task ARNs
            response = self.ecs.list_tasks(
                cluster=cluster,
                serviceName=service,
                desiredStatus='RUNNING'
            )
            task_arns = response.get('taskArns', [])
            
            if not task_arns:
                console.print("[yellow]Warning: No RUNNING tasks found for this service[/yellow]")
                return []
            
            # Get task details
            tasks_response = self.ecs.describe_tasks(
                cluster=cluster,
                tasks=task_arns
            )
            
            tasks = tasks_response.get('tasks', [])
            
            # Filter only RUNNING tasks and warn about others
            running_tasks = []
            for task in tasks:
                if task['lastStatus'] == 'RUNNING':
                    running_tasks.append(task)
                else:
                    console.print(f"[yellow]Warning: Skipping task {task['taskArn'].split('/')[-1]} (status: {task['lastStatus']})[/yellow]")
            
            return running_tasks
            
        except Exception as e:
            console.print(f"[red]Error listing tasks: {e}[/red]")
            return []

    def get_container_instance_id(self, cluster: str, task: Dict) -> Optional[str]:
        """Get EC2 instance ID from task's container instance ARN"""
        try:
            container_instance_arn = task.get('containerInstanceArn')
            if not container_instance_arn:
                return None
            
            response = self.ecs.describe_container_instances(
                cluster=cluster,
                containerInstances=[container_instance_arn]
            )
            
            instances = response.get('containerInstances', [])
            if instances:
                return instances[0].get('ec2InstanceId')
            
            return None
            
        except Exception as e:
            console.print(f"[red]Error getting instance ID: {e}[/red]")
            return None

    def get_task_containers(self, task: Dict, exclude_agent: bool = True) -> List[Dict]:
        """Get containers from task, optionally excluding ECS agent"""
        from .config import ECS_AGENT_CONTAINER_NAME
        
        containers = task.get('containers', [])
        
        if exclude_agent:
            containers = [
                c for c in containers 
                if ECS_AGENT_CONTAINER_NAME not in c.get('name', '').lower()
            ]
        
        return containers

    def verify_ssm_access(self, instance_id: str) -> bool:
        """Check if instance is accessible via SSM"""
        try:
            response = self.ssm.describe_instance_information(
                Filters=[
                    {
                        'Key': 'InstanceIds',
                        'Values': [instance_id]
                    }
                ]
            )
            return len(response.get('InstanceInformationList', [])) > 0
        except Exception as e:
            console.print(f"[red]Error checking SSM access: {e}[/red]")
            return False


def extract_name_from_arn(arn: str) -> str:
    """Extract readable name from AWS ARN"""
    # ECS ARNs format: arn:aws:ecs:region:account:cluster/name
    return arn.split('/')[-1] if '/' in arn else arn.split(':')[-1]
