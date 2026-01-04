"""Download Logs TUI with progress and statistics"""

import time
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from textual.app import App, ComposeResult
from textual.widgets import Static, LoadingIndicator
from textual.containers import Container
from textual.binding import Binding
from textual.worker import Worker, WorkerState

import subprocess
import platform
import os
from .aws_client import AWSClient
from .live_logs import parse_log_level, LogLoaderApp


class DownloadLogsApp(App):
    """Download logs viewer with statistics"""

    CSS = """
    * {
        scrollbar-size: 0 0;
    }

    Screen {
        background: #18141d;
        align: center middle;
    }

    #title {
        dock: top;
        height: 1;
        background: #4d4576;
        color: #c9bfe4;
        text-style: bold;
        padding: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: #4d4576;
        color: #8a80a0;
        padding: 0 1;
    }

    .loading-container {
        width: 50;
        height: auto;
        background: #2a2435;
        border: solid #7c6a9e;
        padding: 1 2;
        align: center middle;
    }

    .loading-container LoadingIndicator {
        width: 100%;
        height: 3;
        color: #c9bfe4;
        background: transparent;
    }

    .loading-container Static {
        width: 100%;
        text-align: center;
        color: #c9bfe4;
        background: transparent;
    }

    #result-box {
        width: 60;
        height: auto;
        background: #2a2435;
        border: solid #7c6a9e;
        padding: 1 2;
    }

    #result-title {
        text-align: center;
        text-style: bold;
        color: #c9bfe4;
        padding: 0 0 1 0;
    }

    #result-stats {
        text-align: center;
        padding: 1 0;
    }

    #result-path {
        text-align: center;
        color: #8a80a0;
        padding: 1 0 0 0;
    }

    #result-hint {
        text-align: center;
        color: #8a80a0;
        text-style: italic;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("enter", "continue", "Continue", show=True),
        Binding("escape", "continue", "Continue", show=False),
        Binding("q", "continue", "Continue", show=False),
    ]

    def __init__(
        self,
        log_group: str,
        log_stream: str,
        aws_client: AWSClient,
        container_name: str,
        task_id: str,
        minutes: int = 60,
    ):
        super().__init__()
        self.log_group = log_group
        self.log_stream = log_stream
        self.aws = aws_client
        self.container_name = container_name
        self.task_id = task_id
        self.minutes = minutes
        self.result_path: Optional[Path] = None
        self.stats: Dict[str, int] = {}
        self._done = False

    def compose(self) -> ComposeResult:
        yield Static(f"Download Logs: {self.container_name}", id="title")
        yield Container(
            LoadingIndicator(),
            Static(f"Fetching logs from last {self.minutes} minutes..."),
            classes="loading-container",
            id="loading"
        )
        yield Static("Enter Continue | Esc Back", id="status-bar")

    def on_mount(self) -> None:
        self._start_download()

    def _start_download(self) -> None:
        """Start download worker"""
        self.run_worker(
            self._download_logs,
            name="download_logs",
            exclusive=True,
            thread=True
        )

    def _download_logs(self) -> dict:
        """Worker: download logs from CloudWatch"""
        # Calculate time range
        end_time = int(time.time() * 1000)
        start_time = end_time - (self.minutes * 60 * 1000)

        events = self.aws.get_log_events(
            self.log_group,
            self.log_stream,
            start_time=start_time,
            end_time=end_time,
            limit=10000
        )

        if not events:
            return {'events': [], 'stats': {}, 'path': None}

        # Count by log level
        stats = {'DEBUG': 0, 'INFO': 0, 'WARNING': 0, 'ERROR': 0, 'CRITICAL': 0}
        for event in events:
            level = parse_log_level(event.get('message', ''))
            if level in stats:
                stats[level] += 1
            else:
                stats['INFO'] += 1

        # Prepare download path
        downloads_dir = Path.home() / "Downloads"
        downloads_dir.mkdir(exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"ecs_logs_{self.container_name}_{self.task_id}_{timestamp}.log"
        filepath = downloads_dir / filename

        # Write logs to file
        with open(filepath, 'w') as f:
            for event in events:
                ts = event.get('timestamp', 0)
                message = event.get('message', '')
                dt = datetime.fromtimestamp(ts / 1000)
                time_str = dt.strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"{time_str} {message}\n")

        return {'events': events, 'stats': stats, 'path': filepath}

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state != WorkerState.SUCCESS:
            return

        if event.worker.name != "download_logs":
            return

        result = event.worker.result
        self._show_result(result)

    def _show_result(self, result: dict) -> None:
        """Show download result"""
        # Remove loading
        loading = self.query_one("#loading", Container)
        loading.remove()

        events = result.get('events', [])
        stats = result.get('stats', {})
        filepath = result.get('path')

        if not events:
            # No logs found
            result_box = Container(
                Static("No Logs Found", id="result-title"),
                Static(f"[yellow]No logs in the last {self.minutes} minutes[/yellow]", id="result-stats"),
                Static("Press Enter to continue", id="result-hint"),
                id="result-box"
            )
        else:
            # Build stats display
            total = len(events)
            stats_parts = []

            # Order: DEBUG, INFO, WARNING, ERROR (with colors)
            if stats.get('DEBUG', 0) > 0:
                stats_parts.append(f"[dim]{stats['DEBUG']} debug[/dim]")
            if stats.get('INFO', 0) > 0:
                stats_parts.append(f"[white]{stats['INFO']} info[/white]")
            if stats.get('WARNING', 0) > 0:
                stats_parts.append(f"[yellow]{stats['WARNING']} warning[/yellow]")
            error_count = stats.get('ERROR', 0) + stats.get('CRITICAL', 0)
            if error_count > 0:
                stats_parts.append(f"[red]{error_count} error[/red]")

            stats_line = " | ".join(stats_parts) if stats_parts else ""

            result_box = Container(
                Static("Download Complete", id="result-title"),
                Static(f"[bold cyan]{total}[/bold cyan] log entries\n\n{stats_line}", id="result-stats"),
                Static(f"[dim]Saved to:[/dim]\n[@click=open_file('{filepath}')]{filepath}[/]", id="result-path"),
                Static("Press Enter to continue", id="result-hint"),
                id="result-box"
            )

        self.mount(result_box)
        self._done = True

    def action_continue(self) -> None:
        self.exit()

    def action_open_file(self, path: str) -> None:
        """Open file in default editor"""
        try:
            if platform.system() == 'Darwin':       # macOS
                subprocess.call(('open', path))
            elif platform.system() == 'Windows':    # Windows
                os.startfile(path)
            else:                                   # linux variants
                subprocess.call(('xdg-open', path))
        except Exception:
            # Fallback or ignore if fails
            pass


def run_download_logs(
    log_group: str,
    log_stream: str,
    aws_client: AWSClient,
    container_name: str,
    task_id: str,
    minutes: int = 60,
) -> None:
    """Run the download logs TUI"""
    app = DownloadLogsApp(
        log_group=log_group,
        log_stream=log_stream,
        aws_client=aws_client,
        container_name=container_name,
        task_id=task_id,
        minutes=minutes,
    )
    app.run()


def run_download_logs_with_loading(
    aws_client: AWSClient,
    task: dict,
    container_name: str,
    minutes: int = 60,
) -> None:
    """Run download logs with loading screen first"""
    # Use the same loader as live logs
    loader = LogLoaderApp(aws_client, task, container_name, "Retrieving log configuration...")
    result = loader.run()

    if result == "success" and loader.result:
        task_id = task.get('taskArn', '').split('/')[-1][:8]
        run_download_logs(
            log_group=loader.result['log_group'],
            log_stream=loader.result['log_stream'],
            aws_client=aws_client,
            container_name=container_name,
            task_id=task_id,
            minutes=minutes
        )
