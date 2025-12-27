"""SSM Session Manager connection logic"""

import subprocess
import json
from typing import Optional
from rich.console import Console

console = Console()


def get_container_id(instance_id: str, container_name: str, region: str) -> Optional[str]:
    """Get Docker container ID from EC2 instance via SSM"""
    try:
        # Execute docker ps command via SSM (with sudo for permissions)
        command = f"sudo docker ps --filter 'name={container_name}' --format '{{{{.ID}}}}'"
        
        result = subprocess.run([
            'aws', 'ssm', 'send-command',
            '--instance-ids', instance_id,
            '--document-name', 'AWS-RunShellScript',
            '--parameters', f'commands=["{command}"]',
            '--region', region,
            '--output', 'json'
        ], capture_output=True, text=True, timeout=10)
        
        if result.returncode != 0:
            console.print(f"[red]Failed to send SSM command: {result.stderr}[/red]")
            return None
        
        response = json.loads(result.stdout)
        command_id = response['Command']['CommandId']
        
        # Wait and get command output
        import time
        time.sleep(2)  # Give command time to execute
        
        output_result = subprocess.run([
            'aws', 'ssm', 'get-command-invocation',
            '--command-id', command_id,
            '--instance-id', instance_id,
            '--region', region,
            '--output', 'json'
        ], capture_output=True, text=True, timeout=10)
        
        if output_result.returncode != 0:
            console.print(f"[red]Failed to get command output: {output_result.stderr}[/red]")
            return None
        
        output = json.loads(output_result.stdout)
        container_id = output.get('StandardOutputContent', '').strip()
        
        return container_id if container_id else None
        
    except subprocess.TimeoutExpired:
        console.print("[red]SSM command timed out[/red]")
        return None
    except Exception as e:
        console.print(f"[red]Error getting container ID: {e}[/red]")
        return None


def start_ssh_session(instance_id: str, region: str):
    """Start SSM session to EC2 instance (SSH mode)"""
    console.print(f"[green]Starting SSH session to {instance_id}...[/green]")
    
    try:
        subprocess.run([
            'aws', 'ssm', 'start-session',
            '--target', instance_id,
            '--region', region
        ])
    except KeyboardInterrupt:
        console.print("\n[yellow]Session terminated[/yellow]")
    except Exception as e:
        console.print(f"[red]Error starting session: {e}[/red]")


def start_container_session(instance_id: str, container_id: str, region: str):
    """Start SSM session and exec into Docker container"""
    console.print(f"[green]Starting session to container {container_id[:12]}...[/green]")

    docker_command = f"sudo docker exec -it {container_id} bash || sudo docker exec -it {container_id} sh"

    try:
        # Use shell=True to properly handle the complex command
        cmd = (
            f'aws ssm start-session '
            f'--target {instance_id} '
            f'--region {region} '
            f'--document-name AWS-StartInteractiveCommand '
            f'--parameters \'{{"command":["{docker_command}"]}}\''
        )
        subprocess.run(cmd, shell=True)
    except KeyboardInterrupt:
        console.print("\n[yellow]Session terminated[/yellow]")
    except Exception as e:
        console.print(f"[red]Error starting container session: {e}[/red]")
        console.print("[yellow]Falling back to regular SSH session...[/yellow]")
        start_ssh_session(instance_id, region)


def check_session_manager_plugin() -> bool:
    """Verify that AWS Session Manager plugin is installed"""
    try:
        result = subprocess.run(
            ['session-manager-plugin'],
            capture_output=True,
            timeout=2
        )
        return True
    except FileNotFoundError:
        console.print("[red]AWS Session Manager Plugin not found![/red]")
        console.print("[yellow]Install from: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html[/yellow]")
        return False
    except Exception:
        return True  # Assume it's installed if we get other errors
