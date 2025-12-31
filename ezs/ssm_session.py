"""SSM Session Manager connection logic"""

import subprocess
import json
import os
import sys
from typing import Optional
from rich.console import Console
from textual.app import App, ComposeResult
from textual.widgets import Static, LoadingIndicator
from textual.containers import Container

console = Console()


class ConnectingApp(App):
    """Loading screen while connecting to SSH/container"""

    CSS = """
    Screen {
        background: #08060d;
        align: center middle;
    }

    #loading-box {
        width: 50;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
    }

    #loading-box LoadingIndicator {
        width: 100%;
        height: 3;
        color: #a99fc4;
        background: transparent;
    }

    #loading-box Static {
        width: 100%;
        text-align: center;
        color: #a99fc4;
        background: transparent;
    }
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Container(
            LoadingIndicator(),
            Static(self.message),
            id="loading-box"
        )

    def on_mount(self) -> None:
        # Exit after a brief moment to show the loading screen
        self.set_timer(0.5, self.exit)


def reset_terminal():
    """Reset terminal state after SSM session"""
    try:
        # Reset terminal to sane state
        os.system('stty sane 2>/dev/null')
        # Clear any pending input
        if sys.stdin.isatty():
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
    except Exception:
        pass


def get_container_id(instance_id: str, container_name: str, region: str) -> Optional[str]:
    """Get Docker container ID from EC2 instance via SSM"""
    try:
        # Execute docker ps command via SSM (with sudo for permissions)
        # Use regex anchor for exact match: ^/name$ (docker adds / prefix to names)
        command = f"sudo docker ps --filter 'name=^/{container_name}$' --format '{{{{.ID}}}}'"
        
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
    # Show loading screen
    app = ConnectingApp(f"Connecting to {instance_id}...")
    app.run()

    try:
        subprocess.run([
            'aws', 'ssm', 'start-session',
            '--target', instance_id,
            '--region', region
        ])
    except KeyboardInterrupt:
        pass
    except Exception as e:
        console.print(f"[red]Error starting session: {e}[/red]")
    finally:
        reset_terminal()


def start_container_session(instance_id: str, container_id: str, region: str):
    """Start SSM session and exec into Docker container"""
    # Take only first container ID if multiple returned, and clean it
    container_id = container_id.strip().split('\n')[0].split()[0]

    # Show loading screen
    app = ConnectingApp(f"Connecting to container {container_id[:12]}...")
    app.run()

    docker_command = f"sudo docker exec -it {container_id} /bin/sh"

    try:
        subprocess.run([
            'aws', 'ssm', 'start-session',
            '--target', instance_id,
            '--region', region,
            '--document-name', 'AWS-StartInteractiveCommand',
            '--parameters', f'{{"command":["{docker_command}"]}}'
        ])
    except KeyboardInterrupt:
        pass
    except Exception as e:
        console.print(f"[red]Error starting container session: {e}[/red]")
        console.print("[yellow]Falling back to regular SSH session...[/yellow]")
        start_ssh_session(instance_id, region)
    finally:
        reset_terminal()


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
