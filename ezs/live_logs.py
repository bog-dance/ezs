"""Live Logs TUI with filtering by log level"""

import re
from datetime import datetime
from typing import Optional, List, Generator
from textual.app import App, ComposeResult
from textual.widgets import Static, RichLog
from textual.containers import Container
from textual.binding import Binding
from textual.worker import Worker, WorkerState

from .aws_client import AWSClient


# Log level patterns for Django and common formats
LOG_LEVEL_PATTERNS = [
    # Django format: "2025-12-27 16:16:59,569 WARNING django.request"
    re.compile(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\.]\d+\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+'),
    # Word boundary match: " WARNING " or " ERROR " etc
    re.compile(r'\s(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s'),
    # Standard format: "[WARNING]" or "[ERROR]" etc
    re.compile(r'\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]', re.IGNORECASE),
    # Simple format: "WARNING:" or "ERROR:" etc
    re.compile(r'\b(DEBUG|INFO|WARNING|ERROR|CRITICAL):', re.IGNORECASE),
    # Python logging: "WARNING -" or "ERROR -"
    re.compile(r'\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+-', re.IGNORECASE),
]


def parse_log_level(message: str) -> str:
    """Extract log level from message. Returns 'INFO' if not found."""
    for pattern in LOG_LEVEL_PATTERNS:
        match = pattern.search(message)
        if match:
            return match.group(1).upper()
    return "INFO"


class LiveLogsApp(App):
    """Live logs viewer with filtering"""

    CSS = """
    * {
        scrollbar-size: 0 0;
    }

    Screen {
        background: #08060d;
    }

    #title {
        dock: top;
        height: 1;
        background: #3d3556;
        color: #a99fc4;
        text-style: bold;
        padding: 0 1;
    }

    #log-view {
        background: #08060d;
        color: #a99fc4;
        padding: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: #3d3556;
        layout: horizontal;
    }

    .filter-btn {
        width: 12;
        height: 1;
        padding: 0 1;
        color: #6a6080;
        background: #3d3556;
        content-align: center middle;
    }

    .filter-btn.active {
        color: #08060d;
        background: #b0a7be;
        text-style: bold;
    }

    #btn-error.active {
        background: #e06c75;
    }

    #btn-warning.active {
        background: #e5c07b;
        color: #08060d;
    }

    #btn-info.active {
        background: #61afef;
        color: #08060d;
    }

    #btn-debug.active {
        background: #6a6080;
        color: #08060d;
    }

    #info {
        width: 1fr;
        padding: 0 1;
        color: #6a6080;
        text-align: right;
    }

    .help-overlay {
        width: 100%;
        height: 100%;
        background: #08060d 90%;
        align: center middle;
        layer: overlay;
    }

    #help-box {
        width: 50;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
    }

    #help-title {
        text-align: center;
        text-style: bold;
        color: #a99fc4;
        padding: 0 0 1 0;
    }

    #help-content {
        color: #8a7fa0;
    }

    #help-hint {
        text-align: center;
        color: #6a6080;
        text-style: italic;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("f1", "show_help", "Help", show=True),
        Binding("a", "filter_all", "All", show=True),
        Binding("e", "filter_error", "Error", show=True),
        Binding("w", "filter_warning", "Warning", show=True),
        Binding("i", "filter_info", "Info", show=True),
        Binding("d", "filter_debug", "Debug", show=True),
        Binding("q", "quit", "Quit", show=True),
        Binding("escape", "quit", "Quit", show=False),
        Binding("left", "quit", "Quit", show=False),
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
    ]

    def __init__(
        self,
        log_group: str,
        log_stream: str,
        aws_client: AWSClient,
        container_name: str = "",
    ):
        super().__init__()
        self.log_group = log_group
        self.log_stream = log_stream
        self.aws = aws_client
        self.container_name = container_name
        self.current_filter = "ALL"  # ALL, DEBUG, INFO, WARNING, ERROR
        self._log_buffer: List[dict] = []  # Store all logs for re-filtering
        self._streaming = False
        self._total_count = 0
        self._shown_count = 0

    def compose(self) -> ComposeResult:
        yield Static(f"Live Logs: {self.container_name}", id="title")
        yield RichLog(id="log-view", highlight=True, markup=True)
        yield Container(
            Static("\\[A]ll", id="btn-all", classes="filter-btn active"),
            Static("\\[E]rror", id="btn-error", classes="filter-btn"),
            Static("\\[W]arning", id="btn-warning", classes="filter-btn"),
            Static("\\[I]nfo", id="btn-info", classes="filter-btn"),
            Static("\\[D]ebug", id="btn-debug", classes="filter-btn"),
            Static("", id="info"),
            id="status-bar"
        )

    def on_mount(self) -> None:
        self._start_streaming()

    def _start_streaming(self) -> None:
        """Start log streaming worker"""
        self._streaming = True
        self.run_worker(
            self._stream_logs,
            name="stream_logs",
            exclusive=True,
            thread=True
        )

    def _stream_logs(self) -> None:
        """Worker: stream logs from CloudWatch"""
        import time
        try:
            next_token = None
            while self._streaming:
                kwargs = {
                    'logGroupName': self.log_group,
                    'logStreamName': self.log_stream,
                    'startFromHead': False,
                    'limit': 100
                }
                if next_token:
                    kwargs['nextToken'] = next_token

                response = self.aws.logs.get_log_events(**kwargs)
                events = response.get('events', [])
                new_token = response.get('nextForwardToken')

                for event in events:
                    if not self._streaming:
                        return
                    self.call_from_thread(self._add_log_event, event)

                # Short sleeps to allow quick exit
                if not events or new_token == next_token:
                    for _ in range(10):  # 1 second total, but check every 0.1s
                        if not self._streaming:
                            return
                        time.sleep(0.1)

                next_token = new_token
        except Exception as e:
            if self._streaming:
                self.call_from_thread(self._show_error, str(e))

    def _add_log_event(self, event: dict) -> None:
        """Add a log event to the buffer and display if matches filter"""
        timestamp = event.get('timestamp', 0)
        message = event.get('message', '')
        level = parse_log_level(message)

        log_entry = {
            'timestamp': timestamp,
            'message': message,
            'level': level,
        }
        self._log_buffer.append(log_entry)
        self._total_count += 1

        if self._matches_filter(level):
            self._display_log(log_entry)
            self._shown_count += 1

        self._update_info()

    def _matches_filter(self, level: str) -> bool:
        """Check if log level matches current filter.

        Filter shows selected level and MORE SEVERE levels:
        - ERROR: only ERROR, CRITICAL
        - WARNING: WARNING, ERROR, CRITICAL
        - INFO: INFO, WARNING, ERROR, CRITICAL
        - DEBUG: everything (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        - ALL: everything
        """
        if self.current_filter == "ALL":
            return True
        if self.current_filter == "ERROR":
            return level in ("ERROR", "CRITICAL")
        if self.current_filter == "WARNING":
            return level in ("WARNING", "ERROR", "CRITICAL")
        if self.current_filter == "INFO":
            return level in ("INFO", "WARNING", "ERROR", "CRITICAL")
        if self.current_filter == "DEBUG":
            return True  # Show everything including DEBUG
        return True

    def _display_log(self, log_entry: dict) -> None:
        """Display a single log entry"""
        log_view = self.query_one("#log-view", RichLog)
        timestamp = log_entry['timestamp']
        message = log_entry['message']
        level = log_entry['level']

        dt = datetime.fromtimestamp(timestamp / 1000)
        time_str = dt.strftime('%H:%M:%S')

        # Color based on level
        level_colors = {
            'DEBUG': 'dim',
            'INFO': 'white',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'bold red',
        }
        color = level_colors.get(level, 'white')

        log_view.write(f"[dim]{time_str}[/dim] [{color}]{message}[/{color}]")

    def _update_info(self) -> None:
        """Update info in status bar"""
        info = self.query_one("#info", Static)
        if self.current_filter == "ALL":
            info.update(f"{self._total_count} logs")
        else:
            info.update(f"{self._shown_count}/{self._total_count} logs")

    def _show_error(self, error: str) -> None:
        """Show error message"""
        log_view = self.query_one("#log-view", RichLog)
        log_view.write(f"[red]Error: {error}[/red]")

    def _set_filter(self, filter_name: str) -> None:
        """Set filter and refresh display"""
        self.current_filter = filter_name

        # Update button styles
        buttons = {
            "ALL": "#btn-all",
            "DEBUG": "#btn-debug",
            "INFO": "#btn-info",
            "WARNING": "#btn-warning",
            "ERROR": "#btn-error",
        }

        for name, btn_id in buttons.items():
            btn = self.query_one(btn_id, Static)
            if name == filter_name:
                btn.add_class("active")
            else:
                btn.remove_class("active")

        # Refresh log display
        self._refresh_logs()

    def _refresh_logs(self) -> None:
        """Re-display logs with current filter"""
        log_view = self.query_one("#log-view", RichLog)
        log_view.clear()

        self._shown_count = 0
        for log_entry in self._log_buffer:
            if self._matches_filter(log_entry['level']):
                self._display_log(log_entry)
                self._shown_count += 1

        self._update_info()

    def action_filter_all(self) -> None:
        self._set_filter("ALL")

    def action_filter_debug(self) -> None:
        self._set_filter("DEBUG")

    def action_filter_info(self) -> None:
        self._set_filter("INFO")

    def action_filter_warning(self) -> None:
        self._set_filter("WARNING")

    def action_filter_error(self) -> None:
        self._set_filter("ERROR")

    def action_show_help(self) -> None:
        """Show help overlay"""
        # Remove existing help if any
        for overlay in self.query(".help-overlay"):
            overlay.remove()
            return

        help_text = """[bold]Log Level Filters[/bold]

[bold white]A[/bold white] All      - show all logs
[bold red]E[/bold red] Error    - errors only
[bold yellow]W[/bold yellow] Warning  - warnings + errors
[bold cyan]I[/bold cyan] Info     - info + warnings + errors
[bold dim]D[/bold dim] Debug    - all including debug

[bold]Navigation[/bold]

Q / Esc  - quit live logs"""

        help_box = Container(
            Static("Help", id="help-title"),
            Static(help_text, id="help-content"),
            Static("Press F1 or Esc to close", id="help-hint"),
            id="help-box"
        )
        overlay = Container(help_box, classes="help-overlay")
        self.mount(overlay)

    def on_key(self, event) -> None:
        """Handle key events"""
        # Close help on any key if help is shown
        help_overlays = list(self.query(".help-overlay"))
        if help_overlays and event.key in ("escape", "f1", "enter", "space"):
            for overlay in help_overlays:
                overlay.remove()
            event.prevent_default()
            event.stop()

    def action_quit(self) -> None:
        self._streaming = False
        self.exit()


def run_live_logs(
    log_group: str,
    log_stream: str,
    aws_client: AWSClient,
    container_name: str = "",
) -> None:
    """Run the live logs TUI"""
    app = LiveLogsApp(
        log_group=log_group,
        log_stream=log_stream,
        aws_client=aws_client,
        container_name=container_name,
    )
    app.run()
