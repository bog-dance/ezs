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
        """Get environment variables for a specific container.

        Returns both regular environment variables and secrets.
        For SSM parameters: fetches the actual value, marks SecureString with [SECURE]
        For Secrets Manager: fetches the actual value, marks with [SECRET]
        """
        try:
            task_def_arn = task.get('taskDefinitionArn')
            if not task_def_arn:
                return {}

            response = self.ecs.describe_task_definition(taskDefinition=task_def_arn)
            task_def = response.get('taskDefinition', {})

            for container_def in task_def.get('containerDefinitions', []):
                if container_def.get('name') == container_name:
                    env_vars = {}

                    # Get regular environment variables
                    for env in container_def.get('environment', []):
                        env_vars[env['name']] = env.get('value', '')

                    # Get secrets (from Secrets Manager or SSM Parameter Store)
                    ssm_params = []  # Collect SSM parameter paths
                    sm_secrets = []  # Collect Secrets Manager refs

                    for secret in container_def.get('secrets', []):
                        name = secret.get('name', '')
                        value_from = secret.get('valueFrom', '')
                        if not value_from:
                            continue

                        if ':secretsmanager:' in value_from:
                            sm_secrets.append((name, value_from))
                        else:
                            # SSM Parameter Store - extract path
                            if value_from.startswith('arn:'):
                                # Extract parameter name from ARN
                                # arn:aws:ssm:region:account:parameter/path/to/param
                                parts = value_from.split(':parameter')
                                if len(parts) > 1:
                                    param_path = parts[1]
                                    ssm_params.append((name, param_path))
                            else:
                                # Direct parameter path
                                ssm_params.append((name, value_from))

                    # Fetch SSM parameters in batch
                    if ssm_params:
                        param_paths = [p[1] for p in ssm_params]
                        param_values = self._fetch_ssm_parameters(param_paths)

                        for name, path in ssm_params:
                            if path in param_values:
                                value, param_type = param_values[path]
                                if param_type == 'SecureString':
                                    env_vars[name] = f'[SECURE]{value}'
                                else:
                                    env_vars[name] = value
                            else:
                                env_vars[name] = '[ERROR] Could not fetch from SSM'

                    # Fetch Secrets Manager secrets
                    if sm_secrets:
                        sm_values = self._fetch_secrets_manager(sm_secrets)
                        for name, value in sm_values.items():
                            env_vars[name] = value

                    return env_vars

            return {}
        except Exception as e:
            console.print(f"[red]Error getting env vars: {e}[/red]")
            return {}

    def _fetch_ssm_parameters(self, param_paths: List[str]) -> Dict[str, tuple]:
        """Fetch SSM parameters and return dict of path -> (value, type)"""
        result = {}
        try:
            # SSM GetParameters can fetch up to 10 at a time
            for i in range(0, len(param_paths), 10):
                batch = param_paths[i:i+10]
                response = self.ssm.get_parameters(
                    Names=batch,
                    WithDecryption=True
                )
                for param in response.get('Parameters', []):
                    name = param.get('Name', '')
                    value = param.get('Value', '')
                    param_type = param.get('Type', 'String')
                    result[name] = (value, param_type)
        except Exception as e:
            console.print(f"[yellow]Warning: Could not fetch SSM parameters: {e}[/yellow]")
        return result

    def _fetch_secrets_manager(self, secrets: List[tuple]) -> Dict[str, str]:
        """Fetch secrets from Secrets Manager and return dict of env_name -> [SECRET]value"""
        result = {}
        try:
            session = boto3.Session(region_name=self.region, profile_name=self.profile)
            sm = session.client('secretsmanager')

            for env_name, secret_arn in secrets:
                try:
                    # Handle ARN with optional JSON key suffix
                    # Format: arn:aws:secretsmanager:region:account:secret:name-suffix:json_key:version
                    secret_id = secret_arn
                    json_key = None

                    # Check if there's a JSON key specified (after the secret name)
                    parts = secret_arn.split(':')
                    if len(parts) >= 7:
                        # Standard ARN has 7 parts, if more - could have json_key
                        # arn:aws:secretsmanager:region:account:secret:name
                        base_arn = ':'.join(parts[:7])
                        if len(parts) > 7:
                            json_key = parts[7] if parts[7] else None
                        secret_id = base_arn

                    response = sm.get_secret_value(SecretId=secret_id)
                    secret_value = response.get('SecretString', '')

                    # If JSON key specified, extract that key
                    if json_key and secret_value:
                        try:
                            import json
                            secret_dict = json.loads(secret_value)
                            secret_value = secret_dict.get(json_key, secret_value)
                        except (json.JSONDecodeError, TypeError):
                            pass

                    result[env_name] = f'[SECRET]{secret_value}'
                except Exception as e:
                    result[env_name] = f'[ERROR] Could not fetch: {str(e)[:30]}'
        except Exception as e:
            console.print(f"[yellow]Warning: Could not fetch Secrets Manager secrets: {e}[/yellow]")
        return result

    def get_all_container_env_vars(self, task: Dict) -> Dict[str, Dict[str, str]]:
        """Get environment variables for all containers in task.

        Returns a dict mapping container_name -> {env_var_name: value}
        Uses get_container_env_vars for each container to fetch SSM values.
        """
        try:
            task_def_arn = task.get('taskDefinitionArn')
            if not task_def_arn:
                return {}

            response = self.ecs.describe_task_definition(taskDefinition=task_def_arn)
            task_def = response.get('taskDefinition', {})

            result = {}
            for container_def in task_def.get('containerDefinitions', []):
                container_name = container_def.get('name', '')
                env_vars = self.get_container_env_vars(task, container_name)
                if env_vars:
                    result[container_name] = env_vars

            return result
        except Exception as e:
            console.print(f"[red]Error getting all env vars: {e}[/red]")
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

    def prefetch_cluster_hierarchy(self, cluster_arn: str, progress_callback=None) -> dict:
        """Fetch entire cluster hierarchy in parallel for caching.

        Returns dict with:
        - services: list of service ARNs
        - tasks: dict of service_arn -> list of tasks
        - containers: dict of task_arn -> (instance_id, containers)
        """
        result = {
            'services': [],
            'tasks': {},
            'containers': {}
        }

        # 1. Fetch all services
        if progress_callback:
            progress_callback("Fetching services...")
        services = self.list_services(cluster_arn)
        result['services'] = services

        if not services:
            return result

        if progress_callback:
            progress_callback(f"Found {len(services)} services, fetching tasks...")

        # 2. Fetch tasks for all services in parallel
        def fetch_service_tasks(service_arn):
            tasks = self.list_tasks(cluster_arn, service_arn)
            if tasks and len(tasks) > 1:
                tasks = self.enrich_tasks_with_instance_info(cluster_arn, tasks)
            elif tasks and len(tasks) == 1:
                # Still enrich single task
                tasks = self.enrich_tasks_with_instance_info(cluster_arn, tasks)
            return service_arn, tasks

        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(fetch_service_tasks, svc) for svc in services]
            for future in as_completed(futures):
                try:
                    service_arn, tasks = future.result()
                    result['tasks'][service_arn] = tasks if tasks else []
                except Exception:
                    pass

        # Count total tasks
        total_tasks = sum(len(t) for t in result['tasks'].values())
        if progress_callback:
            progress_callback(f"Found {total_tasks} tasks, fetching containers...")

        # 3. Fetch containers for all tasks in parallel
        all_tasks = []
        for service_arn, tasks in result['tasks'].items():
            for task in tasks:
                all_tasks.append(task)

        if all_tasks:
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(self._fetch_task_containers, cluster_arn, task): task['taskArn']
                    for task in all_tasks
                }
                for future in as_completed(futures):
                    task_arn = futures[future]
                    try:
                        instance_id, containers = future.result()
                        result['containers'][task_arn] = (instance_id, containers)
                    except Exception:
                        result['containers'][task_arn] = (None, [])

        if progress_callback:
            progress_callback("Done!")

        return result

    def _fetch_task_containers(self, cluster_arn: str, task: dict) -> tuple:
        """Fetch instance_id and containers for a single task"""
        instance_id = self.get_container_instance_id(cluster_arn, task)
        # Verify SSM access
        if instance_id:
            ssm_ok = self.verify_ssm_access(instance_id)
            if not ssm_ok:
                instance_id = None
        containers = self.get_task_containers(task, exclude_agent=True)
        return (instance_id, containers)

    def update_service(self, cluster: str, service: str, task_def_arn: str = None) -> bool:
        """Update service to use new task definition or force redeploy"""
        try:
            kwargs = {
                'cluster': cluster,
                'service': service,
                'forceNewDeployment': True
            }
            if task_def_arn:
                kwargs['taskDefinition'] = task_def_arn
            self.ecs.update_service(**kwargs)
            return True
        except Exception as e:
            raise

    def update_ssm_parameter(self, param_name: str, value: str, param_type: str = None) -> str:
        """Update SSM parameter value. Returns the parameter name."""
        try:
            kwargs = {
                'Name': param_name,
                'Value': value,
                'Overwrite': True
            }
            if param_type:
                kwargs['Type'] = param_type
            self.ssm.put_parameter(**kwargs)
            return param_name
        except Exception as e:
            raise

    def update_secrets_manager(self, secret_arn: str, value: str, json_key: str = None) -> str:
        """Update Secrets Manager secret value. Returns the secret ARN."""
        try:
            session = boto3.Session(region_name=self.region, profile_name=self.profile)
            sm = session.client('secretsmanager')

            if json_key:
                # Need to update just one key in the JSON
                response = sm.get_secret_value(SecretId=secret_arn)
                import json
                secret_dict = json.loads(response.get('SecretString', '{}'))
                secret_dict[json_key] = value
                sm.put_secret_value(SecretId=secret_arn, SecretString=json.dumps(secret_dict))
            else:
                sm.put_secret_value(SecretId=secret_arn, SecretString=value)

            return secret_arn
        except Exception as e:
            raise

    def get_container_secrets_mapping(self, task: Dict, container_name: str) -> Dict[str, dict]:
        """Get mapping of env var name -> secret info (type, path/arn, json_key)"""
        try:
            task_def_arn = task.get('taskDefinitionArn')
            if not task_def_arn:
                return {}

            response = self.ecs.describe_task_definition(taskDefinition=task_def_arn)
            task_def = response.get('taskDefinition', {})

            secrets_map = {}
            for container_def in task_def.get('containerDefinitions', []):
                if container_def.get('name') == container_name:
                    for secret in container_def.get('secrets', []):
                        name = secret.get('name', '')
                        value_from = secret.get('valueFrom', '')
                        if not value_from:
                            continue

                        if ':secretsmanager:' in value_from:
                            # Secrets Manager
                            parts = value_from.split(':')
                            json_key = None
                            base_arn = value_from
                            if len(parts) > 7:
                                base_arn = ':'.join(parts[:7])
                                json_key = parts[7] if parts[7] else None
                            secrets_map[name] = {
                                'type': 'secretsmanager',
                                'arn': base_arn,
                                'json_key': json_key,
                                'full_ref': value_from
                            }
                        else:
                            # SSM Parameter Store
                            param_path = value_from
                            if value_from.startswith('arn:'):
                                parts = value_from.split(':parameter')
                                if len(parts) > 1:
                                    param_path = parts[1]
                            secrets_map[name] = {
                                'type': 'ssm',
                                'path': param_path,
                                'full_ref': value_from
                            }
                    break
            return secrets_map
        except Exception as e:
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
