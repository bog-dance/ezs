"""AWS API client wrappers"""

import boto3
from typing import List, Dict, Optional
from rich.console import Console
from concurrent.futures import ThreadPoolExecutor, as_completed

console = Console()


class AWSClient:
    def __init__(self, region: str, profile: Optional[str] = None):
        """Initialize AWS clients for given region"""
        self.profile = profile
        self.region = region
        self._init_clients(region)

    def _init_clients(self, region: str):
        """Initialize boto3 clients for a specific region"""
        session = boto3.Session(region_name=region, profile_name=self.profile)
        self.ecs = session.client('ecs')
        self.ec2 = session.client('ec2')
        self.ssm = session.client('ssm')
        self.logs = session.client('logs')
        self.region = region

    def set_region(self, region: str):
        """Switch to a different region"""
        self._init_clients(region)

    def list_clusters(self) -> List[str]:
        """List all ECS clusters in current region"""
        try:
            response = self.ecs.list_clusters()
            return response.get('clusterArns', [])
        except Exception as e:
            console.print(f"[red]Error listing clusters: {e}[/red]")
            return []

    @staticmethod
    def list_all_clusters(regions: dict, profile: Optional[str] = None) -> List[Dict]:
        """List all ECS clusters from all regions (parallel), preserving region order"""
        region_order = list(regions.keys())
        results_by_region = {code: [] for code in region_order}

        def fetch_region(region_code: str, region_name: str):
            """Fetch clusters from a single region"""
            try:
                session = boto3.Session(region_name=region_code, profile_name=profile)
                ecs = session.client('ecs')
                response = ecs.list_clusters()
                return region_code, [
                    {
                        'arn': arn,
                        'name': extract_name_from_arn(arn),
                        'region': region_code,
                        'region_name': region_name,
                    }
                    for arn in response.get('clusterArns', [])
                ]
            except Exception:
                return region_code, []

        # Fetch all regions in parallel
        with ThreadPoolExecutor(max_workers=len(regions)) as executor:
            futures = [
                executor.submit(fetch_region, code, name)
                for code, name in regions.items()
            ]
            for future in as_completed(futures):
                region_code, clusters = future.result()
                results_by_region[region_code] = sorted(clusters, key=lambda x: x['name'])

        # Flatten in region order
        all_clusters = []
        for region_code in region_order:
            all_clusters.extend(results_by_region[region_code])

        return all_clusters

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

    def enrich_tasks_with_instance_info(self, cluster: str, tasks: List[Dict]) -> List[Dict]:
        """Add instance ID and IP to each task"""
        if not tasks:
            return tasks

        try:
            # Get unique container instance ARNs
            container_arns = list(set(
                t.get('containerInstanceArn') for t in tasks
                if t.get('containerInstanceArn')
            ))

            if not container_arns:
                return tasks

            # Describe container instances
            response = self.ecs.describe_container_instances(
                cluster=cluster,
                containerInstances=container_arns
            )

            # Map ARN to instance ID
            arn_to_instance = {}
            instance_ids = []
            for ci in response.get('containerInstances', []):
                arn_to_instance[ci['containerInstanceArn']] = ci.get('ec2InstanceId')
                if ci.get('ec2InstanceId'):
                    instance_ids.append(ci['ec2InstanceId'])

            # Get EC2 instance IPs
            instance_to_ip = {}
            if instance_ids:
                ec2_response = self.ec2.describe_instances(InstanceIds=instance_ids)
                for reservation in ec2_response.get('Reservations', []):
                    for instance in reservation.get('Instances', []):
                        instance_id = instance['InstanceId']
                        private_ip = instance.get('PrivateIpAddress', '')
                        instance_to_ip[instance_id] = private_ip

            # Enrich tasks
            for task in tasks:
                arn = task.get('containerInstanceArn')
                instance_id = arn_to_instance.get(arn, '')
                task['_instanceId'] = instance_id
                task['_instanceIp'] = instance_to_ip.get(instance_id, '')

            return tasks

        except Exception as e:
            console.print(f"[yellow]Warning: Could not get instance info: {e}[/yellow]")
            return tasks

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

    def get_log_group_for_task(self, task: Dict, container_name: str) -> Optional[str]:
        """Get CloudWatch log group for a task's container"""
        try:
            # Get task definition ARN
            task_def_arn = task.get('taskDefinitionArn')
            if not task_def_arn:
                return None

            # Describe task definition
            response = self.ecs.describe_task_definition(taskDefinition=task_def_arn)
            task_def = response.get('taskDefinition', {})

            # Find container definition
            for container_def in task_def.get('containerDefinitions', []):
                if container_def.get('name') == container_name:
                    log_config = container_def.get('logConfiguration', {})
                    if log_config.get('logDriver') == 'awslogs':
                        options = log_config.get('options', {})
                        log_group = options.get('awslogs-group')
                        return log_group

            return None
        except Exception as e:
            console.print(f"[red]Error getting log group: {e}[/red]")
            return None

    def get_log_stream_for_task(self, task: Dict, container_name: str) -> Optional[str]:
        """Get CloudWatch log stream name for a task's container"""
        try:
            task_def_arn = task.get('taskDefinitionArn')
            task_id = task.get('taskArn', '').split('/')[-1]

            if not task_def_arn or not task_id:
                return None

            response = self.ecs.describe_task_definition(taskDefinition=task_def_arn)
            task_def = response.get('taskDefinition', {})

            for container_def in task_def.get('containerDefinitions', []):
                if container_def.get('name') == container_name:
                    log_config = container_def.get('logConfiguration', {})
                    if log_config.get('logDriver') == 'awslogs':
                        options = log_config.get('options', {})
                        prefix = options.get('awslogs-stream-prefix', '')
                        # Log stream format: prefix/container-name/task-id
                        if prefix:
                            return f"{prefix}/{container_name}/{task_id}"
                        return f"{container_name}/{task_id}"

            return None
        except Exception as e:
            console.print(f"[red]Error getting log stream: {e}[/red]")
            return None

    def get_all_container_log_configs(self, task: Dict) -> List[Dict]:
        """Get log config (group, stream) for all containers in task"""
        results = []
        try:
            task_def_arn = task.get('taskDefinitionArn')
            task_id = task.get('taskArn', '').split('/')[-1]

            if not task_def_arn or not task_id:
                return []

            response = self.ecs.describe_task_definition(taskDefinition=task_def_arn)
            task_def = response.get('taskDefinition', {})

            for container_def in task_def.get('containerDefinitions', []):
                name = container_def.get('name')
                log_config = container_def.get('logConfiguration', {})

                if log_config.get('logDriver') == 'awslogs':
                    options = log_config.get('options', {})
                    group = options.get('awslogs-group')
                    prefix = options.get('awslogs-stream-prefix', '')

                    stream = None
                    if prefix:
                        stream = f"{prefix}/{name}/{task_id}"
                    else:
                        stream = f"{name}/{task_id}"

                    if group and stream:
                        results.append({
                            'container': name,
                            'log_group': group,
                            'log_stream': stream
                        })

            return results
        except Exception as e:
            console.print(f"[red]Error getting task logs: {e}[/red]")
            return []

    def get_container_env_vars(self, task: Dict, container_name: str) -> Dict[str, str]:
        """Get environment variables for a specific container"""
        try:
            task_def_arn = task.get('taskDefinitionArn')
            if not task_def_arn:
                return {}

            response = self.ecs.describe_task_definition(taskDefinition=task_def_arn)
            task_def = response.get('taskDefinition', {})

            for container_def in task_def.get('containerDefinitions', []):
                if container_def.get('name') == container_name:
                    env_vars = {}
                    for env in container_def.get('environment', []):
                        env_vars[env['name']] = env['value']
                    return env_vars

            return {}
        except Exception as e:
            console.print(f"[red]Error getting env vars: {e}[/red]")
            return {}

    def register_task_definition(self, original_task_def_arn: str, container_name: str, new_env_vars: Dict[str, str]) -> str:
        """
        Create a new task definition revision with updated environment variables.
        Returns the new task definition ARN.
        """
        try:
            # 1. Fetch original definition
            response = self.ecs.describe_task_definition(taskDefinition=original_task_def_arn)
            task_def = response.get('taskDefinition', {})

            # 2. Clean up read-only fields
            fields_to_remove = [
                'taskDefinitionArn', 'revision', 'status', 'requiresAttributes',
                'compatibilities', 'registeredAt', 'registeredBy'
            ]
            new_def = {k: v for k, v in task_def.items() if k not in fields_to_remove}

            # 3. Update container environment
            updated = False
            for container in new_def.get('containerDefinitions', []):
                if container['name'] == container_name:
                    # Convert dict to list of {name, value}
                    env_list = [{'name': k, 'value': v} for k, v in new_env_vars.items()]
                    container['environment'] = env_list
                    updated = True
                    break

            if not updated:
                raise ValueError(f"Container {container_name} not found in task definition")

            # 4. Register new definition
            response = self.ecs.register_task_definition(**new_def)
            new_arn = response['taskDefinition']['taskDefinitionArn']
            return new_arn

        except Exception as e:
            console.print(f"[red]Error registering task definition: {e}[/red]")
            raise

    def update_service(self, cluster: str, service: str, task_def_arn: str) -> bool:
        """Update service to use new task definition"""
        try:
            self.ecs.update_service(
                cluster=cluster,
                service=service,
                taskDefinition=task_def_arn,
                forceNewDeployment=True
            )
            return True
        except Exception as e:
            console.print(f"[red]Error updating service: {e}[/red]")
            raise

    def get_log_events(self, log_group: str, log_stream: str,
                       start_time: Optional[int] = None,
                       end_time: Optional[int] = None,
                       limit: int = 1000) -> List[Dict]:
        """Get log events from CloudWatch"""
        try:
            kwargs = {
                'logGroupName': log_group,
                'logStreamName': log_stream,
                'startFromHead': False,
                'limit': limit
            }
            if start_time:
                kwargs['startTime'] = start_time
            if end_time:
                kwargs['endTime'] = end_time

            response = self.logs.get_log_events(**kwargs)
            return response.get('events', [])
        except Exception as e:
            console.print(f"[red]Error getting log events: {e}[/red]")
            return []

    def stream_log_events(self, log_group: str, log_stream: str):
        """Generator that yields new log events (for live streaming)"""
        import time
        next_token = None

        while True:
            try:
                kwargs = {
                    'logGroupName': log_group,
                    'logStreamName': log_stream,
                    'startFromHead': False,
                    'limit': 100
                }
                if next_token:
                    kwargs['nextToken'] = next_token

                response = self.logs.get_log_events(**kwargs)
                events = response.get('events', [])
                new_token = response.get('nextForwardToken')

                for event in events:
                    yield event

                # If no new events and token hasn't changed, wait
                if not events or new_token == next_token:
                    time.sleep(1)

                next_token = new_token

            except Exception as e:
                console.print(f"[red]Error streaming logs: {e}[/red]")
                break


def extract_name_from_arn(arn: str) -> str:
    """Extract readable name from AWS ARN"""
    # ECS ARNs format: arn:aws:ecs:region:account:cluster/name
    return arn.split('/')[-1] if '/' in arn else arn.split(':')[-1]
