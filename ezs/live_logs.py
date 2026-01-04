"""Live Logs TUI with filtering by log level and container"""

import re
import time
import heapq
from datetime import datetime
from typing import Optional, List, Generator, Dict, Any
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static, LoadingIndicator, Button, Label, RichLog
from textual.containers import Container, VerticalScroll, Horizontal
from textual.binding import Binding
from textual.worker import Worker, WorkerState

from .aws_client import AWSClient


# Log level patterns
LOG_LEVEL_PATTERNS = [
    re.compile(r'\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}[,\.]\d+\s+(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+'),
    re.compile(r'\s(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s'),
    re.compile(r'\[(DEBUG|INFO|WARNING|ERROR|CRITICAL)\]', re.IGNORECASE),
    re.compile(r'\b(DEBUG|INFO|WARNING|ERROR|CRITICAL):', re.IGNORECASE),
    re.compile(r'\b(DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+-', re.IGNORECASE),
]

# Container colors for prefix
CONTAINER_COLORS = [
    "cyan", "green", "magenta", "blue", "yellow", "red"
]


def parse_log_level(message: str) -> str:
    """Extract log level from message. Returns 'INFO' if not found."""
    for pattern in LOG_LEVEL_PATTERNS:
        match = pattern.search(message)
        if match:
            return match.group(1).upper()
    return "INFO"


class LiveLogsApp(App):
    """Live logs viewer with filtering by level and container"""

    CSS = """
    * {
        scrollbar-size: 0 0;
    }

    Screen {
        background: #18141d;
    }

    #title {
        dock: top;
        height: 1;
        background: #4d4576;
        color: #c9bfe4;
        text-style: bold;
        padding: 0 1;
    }

    #log-view {
        background: #18141d;
        color: #c9bfe4;
        padding: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: #4d4576;
        layout: horizontal;
    }

    .filter-btn {
        width: 12;
        height: 1;
        padding: 0 1;
        color: #8a80a0;
        background: #4d4576;
        content-align: center middle;
    }

    .filter-btn.active {
        color: #18141d;
        background: #8a7fa0;
        text-style: bold;
    }

    .container-btn {
        width: auto;
        min-width: 10;
        height: 1;
        padding: 0 1;
        color: #8a80a0;
        background: #3a3456;
        content-align: center middle;
        margin: 0 1 0 0;
    }

    .container-btn.active {
        color: #18141d;
        background: #8fa1b3;
        text-style: bold;
    }

    #btn-error.active { background: #e06c75; }
    #btn-warning.active { background: #e5c07b; color: #18141d; }
    #btn-info.active { background: #61afef; color: #18141d; }
    #btn-debug.active { background: #8a80a0; color: #18141d; }

    #info {
        width: 1fr;
        padding: 0 1;
        color: #8a80a0;
        text-align: right;
    }

    #container-bar {
        dock: bottom;
        height: 1;
        background: #3a3456;
        layout: horizontal;
    }

    .help-overlay {
        width: 100%;
        height: 100%;
        background: #18141d 90%;
        align: center middle;
        layer: overlay;
    }

    #help-box {
        width: 50;
        height: auto;
        background: #2a2435;
        border: solid #7c6a9e;
        padding: 1 2;
    }

    #help-title {
        text-align: center;
        text-style: bold;
        color: #c9bfe4;
        padding: 0 0 1 0;
    }

    #help-content {
        color: #a99fc0;
    }

    #help-hint {
        text-align: center;
        color: #8a80a0;
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
        Binding("ctrl+c", "quit", "Quit", show=False, priority=True),
    ]

    def __init__(
        self,
        log_sources: List[Dict], # [{'container': name, 'log_group': g, 'log_stream': s}]
        aws_client: AWSClient,
        title: str = "Live Logs",
    ):
        super().__init__()
        self.log_sources = log_sources
        self.aws = aws_client
        self.app_title = title

        self.current_filter = "ALL"  # ALL, DEBUG, INFO, WARNING, ERROR
        self.container_filter = None # None (All) or container_name

        self._log_buffer: List[dict] = []
        self._streaming = False
        self._total_count = 0
        self._shown_count = 0

        # Assign colors to containers
        self.container_colors = {}
        for i, source in enumerate(log_sources):
            color = CONTAINER_COLORS[i % len(CONTAINER_COLORS)]
            self.container_colors[source['container']] = color

        # Map shortcuts (1-9) to containers
        self.container_shortcuts = {}
        for i, source in enumerate(log_sources):
            if i < 9:
                self.container_shortcuts[str(i+1)] = source['container']

    def compose(self) -> ComposeResult:
        yield Static(self.app_title, id="title")
        yield RichLog(id="log-view", highlight=True, markup=True)

        # Container Filter Bar (only if multiple containers)
        if len(self.log_sources) > 1:
            buttons = [Static("\\[A]ll", id="btn-cont-all", classes="container-btn active")]
            for i, source in enumerate(self.log_sources):
                name = source['container']
                shortcut = str(i + 1) if i < 9 else ""
                label = f"\\[{shortcut}]{name}" if shortcut else name
                buttons.append(Static(label, id=f"btn-cont-{name}", classes="container-btn"))

            yield Horizontal(*buttons, id="container-bar")

        # Log Level Bar
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
        self.query_one(RichLog).focus()
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
        """Worker: stream logs from multiple CloudWatch streams"""
        try:
            # Initialize state for each stream
            streams_state = []
            for source in self.log_sources:
                streams_state.append({
                    'source': source,
                    'next_token': None,
                    'buffer': [],
                    'done': False
                })

            while self._streaming:
                any_data = False

                # Fetch data for all streams
                for state in streams_state:
                    if not self._streaming:
                        return

                    # If buffer empty, fetch more
                    if not state['buffer']:
                        kwargs = {
                            'logGroupName': state['source']['log_group'],
                            'logStreamName': state['source']['log_stream'],
                            'startFromHead': False,
                            'limit': 500    
                        }
                        if state['next_token']:
                            kwargs['nextToken'] = state['next_token']

                        response = self.aws.logs.get_log_events(**kwargs)
                        events = response.get('events', [])
                        new_token = response.get('nextForwardToken')

                        if events:
                            any_data = True
                            for event in events:
                                event['container'] = state['source']['container']
                            state['buffer'].extend(events)

                        state['next_token'] = new_token

                # Merge sort / emit events in order
                # Simple approach: Collect all available events from buffers, sort by timestamp
                # Note: CloudWatch logs are roughly ordered but multi-stream needs alignment

                all_events = []
                for state in streams_state:
                    all_events.extend(state['buffer'])
                    state['buffer'] = [] # Clear buffer after moving to temp list

                if all_events:
                    # Sort by timestamp
                    all_events.sort(key=lambda x: x.get('timestamp', 0))

                    for event in all_events:
                        if not self._streaming:
                            return
                        self.call_from_thread(self._add_log_event, event)

                if not any_data:
                    # Sleep if no new data across all streams
                    for _ in range(10):
                        if not self._streaming: return
                        time.sleep(0.1)

        except Exception as e:
            if self._streaming:
                self.call_from_thread(self._show_error, str(e))

    def _add_log_event(self, event: dict) -> None:
        """Add a log event to the buffer and display if matches filter"""
        timestamp = event.get('timestamp', 0)
        message = event.get('message', '')
        container = event.get('container', '')
        level = parse_log_level(message)

        log_entry = {
            'timestamp': timestamp,
            'message': message,
            'level': level,
            'container': container
        }
        self._log_buffer.append(log_entry)
        self._total_count += 1

        if self._matches_filter(level, container):
            self._display_log(log_entry)
            self._shown_count += 1

        self._update_info()

    def _matches_filter(self, level: str, container: str) -> bool:
        """Check if log entry matches current filters"""
        # Container filter
        if self.container_filter and container != self.container_filter:
            return False

        # Level filter
        if self.current_filter == "ALL":
            return True
        if self.current_filter == "ERROR":
            return level in ("ERROR", "CRITICAL")
        if self.current_filter == "WARNING":
            return level in ("WARNING", "ERROR", "CRITICAL")
        if self.current_filter == "INFO":
            return level in ("INFO", "WARNING", "ERROR", "CRITICAL")
        if self.current_filter == "DEBUG":
            return True
        return True

    def _display_log(self, log_entry: dict) -> None:
        """Display a single log entry"""
        log_view = self.query_one("#log-view", RichLog)
        timestamp = log_entry['timestamp']
        message = log_entry['message']
        level = log_entry['level']
        container = log_entry['container']

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

        # Prefix with container name if showing multiple
        prefix = ""
        if not self.container_filter and len(self.log_sources) > 1:
            cont_color = self.container_colors.get(container, "white")
            prefix = f"[{cont_color}][{container}][/{cont_color}] "

        log_view.write(f"[dim]{time_str}[/dim] {prefix}[{color}]{message}[/{color}]")

    def _update_info(self) -> None:
        """Update info in status bar"""
        info = self.query_one("#info", Static)
        if self.current_filter == "ALL" and not self.container_filter:
            info.update(f"{self._total_count} logs")
        else:
            info.update(f"{self._shown_count}/{self._total_count} logs")

    def _show_error(self, error: str) -> None:
        """Show error message"""
        log_view = self.query_one("#log-view", RichLog)
        log_view.write(f"[red]Error: {error}[/red]")

    def _set_level_filter(self, filter_name: str) -> None:
        """Set level filter and refresh"""
        self.current_filter = filter_name

        buttons = {
            "ALL": "#btn-all",
            "DEBUG": "#btn-debug",
            "INFO": "#btn-info",
            "WARNING": "#btn-warning",
            "ERROR": "#btn-error",
        }

        for name, btn_id in buttons.items():
            try:
                btn = self.query_one(btn_id, Static)
                if name == filter_name:
                    btn.add_class("active")
                else:
                    btn.remove_class("active")
            except Exception:
                pass

        self._refresh_logs()

    def _set_container_filter(self, container_name: Optional[str]) -> None:
        """Set container filter and refresh"""
        self.container_filter = container_name

        # Update buttons
        try:
            # All button
            btn_all = self.query_one("#btn-cont-all", Static)
            if container_name is None:
                btn_all.add_class("active")
            else:
                btn_all.remove_class("active")

            # Individual buttons
            for source in self.log_sources:
                name = source['container']
                btn = self.query_one(f"#btn-cont-{name}", Static)
                if name == container_name:
                    btn.add_class("active")
                else:
                    btn.remove_class("active")
        except Exception:
            pass

        self._refresh_logs()

    def _refresh_logs(self) -> None:
        """Re-display logs with current filter"""
        log_view = self.query_one("#log-view", RichLog)
        log_view.clear()

        self._shown_count = 0
        for log_entry in self._log_buffer:
            if self._matches_filter(log_entry['level'], log_entry['container']):
                self._display_log(log_entry)
                self._shown_count += 1

        self._update_info()

    # Actions
    def action_filter_all(self) -> None: self._set_level_filter("ALL")
    def action_filter_debug(self) -> None: self._set_level_filter("DEBUG")
    def action_filter_info(self) -> None: self._set_level_filter("INFO")
    def action_filter_warning(self) -> None: self._set_level_filter("WARNING")
    def action_filter_error(self) -> None: self._set_level_filter("ERROR")

    def action_show_help(self) -> None:
        """Show help overlay"""
        for overlay in self.query(".help-overlay"):
            overlay.remove()
            return

        help_text = """[bold]Filters[/bold]

[bold white]A[/bold white] All      - show all logs
[bold red]E[/bold red] Error    - errors only
[bold yellow]W[/bold yellow] Warning  - warnings + errors
[bold cyan]I[/bold cyan] Info     - info + warnings + errors
[bold dim]D[/bold dim] Debug    - all including debug

[bold]Containers[/bold]
1-9      - Filter by container (if multiple)
Shift+A  - Show all containers

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
        # Close help
        if list(self.query(".help-overlay")):
            if event.key in ("escape", "f1", "enter", "space"):
                self.query(".help-overlay").remove()
            event.prevent_default()
            event.stop()
            return

        # Container shortcuts
        if event.key in self.container_shortcuts:
            self._set_container_filter(self.container_shortcuts[event.key])
        elif event.key == "A": # Shift+A
            self._set_container_filter(None)

    def action_quit(self) -> None:
        self._streaming = False
        self.exit()


def run_live_logs(
    log_sources: List[Dict],
    aws_client: Any,
    title: str = "Live Logs",
) -> None:
    """Run the live logs TUI"""
    app = LiveLogsApp(
        log_sources=log_sources,
        aws_client=aws_client,
        title=title,
    )
    app.run()


class LogLoaderApp(App):
    """Loading screen while fetching log configuration"""

    CSS = """
    Screen {
        background: #18141d;
        align: center middle;
    }

    .loading-box {
        width: 50;
        height: auto;
        background: #2a2435;
        border: solid #7c6a9e;
        padding: 1 2;
    }

    .loading-box LoadingIndicator {
        width: 100%;
        height: 3;
        color: #c9bfe4;
        background: transparent;
    }

    .loading-box Static {
        width: 100%;
        text-align: center;
        color: #c9bfe4;
        background: transparent;
    }

    .error-box {
        width: 60;
        height: auto;
        background: #2a2435;
        border: solid #e06c75;
        padding: 1 2;
    }

    .error-title {
        text-align: center;
        text-style: bold;
        color: #e06c75;
        padding: 0 0 1 0;
    }

    .error-content {
        text-align: center;
        color: #c9bfe4;
    }

    .error-hint {
        text-align: center;
        color: #8a80a0;
        text-style: italic;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        ("escape", "quit", "Back"),
    ]

    def __init__(self, aws_client, task: dict, container_name: str, message: str = "Retrieving log configuration..."):
        super().__init__()
        self.aws = aws_client
        self.ecs_task = task
        self.container_name = container_name
        self.message = message
        self.result = None  # Will hold {'log_group': ..., 'log_stream': ...}

    def compose(self) -> ComposeResult:
        yield Container(
            LoadingIndicator(),
            Static(self.message),
            classes="loading-box"
        )

    def on_mount(self) -> None:
        self.run_worker(self._fetch_config, name="fetch_config", thread=True)

    def _fetch_config(self) -> dict:
        log_group = self.aws.get_log_group_for_task(self.ecs_task, self.container_name)
        log_stream = self.aws.get_log_stream_for_task(self.ecs_task, self.container_name)
        return {'log_group': log_group, 'log_stream': log_stream}

    def on_worker_state_changed(self, event) -> None:
        if event.worker.name != "fetch_config":
            return

        if event.state == WorkerState.SUCCESS:
            data = event.worker.result
            if data['log_group'] and data['log_stream']:
                self.result = data
                self.exit(result="success")
            else:
                self._show_error("Could not find CloudWatch logs configuration.\\nMake sure the container uses 'awslogs' driver.")
        elif event.state == WorkerState.ERROR:
            self._show_error(str(event.worker.error))

    def _show_error(self, message: str) -> None:
        for box in self.query(".loading-box"):
            box.remove()

        error_box = Container(
            Static("Error", classes="error-title"),
            Static(message, classes="error-content"),
            Static("Press Escape to go back", classes="error-hint"),
            classes="error-box"
        )
        self.mount(error_box)


class TaskLogsLoaderApp(App):
    """Loading screen while fetching log configuration for ALL containers"""

    CSS = LogLoaderApp.CSS
    BINDINGS = LogLoaderApp.BINDINGS

    def __init__(self, aws_client, task: dict):
        super().__init__()
        self.aws = aws_client
        self.ecs_task = task
        self.result = None

    def compose(self) -> ComposeResult:
        yield Container(
            LoadingIndicator(),
            Static("Discovering log streams for task..."),
            classes="loading-box"
        )

    def on_mount(self) -> None:
        self.run_worker(self._fetch_config, name="fetch_config", thread=True)

    def _fetch_config(self) -> list:
        return self.aws.get_all_container_log_configs(self.ecs_task)

    def on_worker_state_changed(self, event) -> None:
        if event.worker.name != "fetch_config":
            return

        if event.state == WorkerState.SUCCESS:
            sources = event.worker.result
            if sources:
                self.result = sources
                self.exit(result="success")
            else:
                self._show_error("No log configurations found for any container in this task.")
        elif event.state == WorkerState.ERROR:
            self._show_error(str(event.worker.error))

    def _show_error(self, message: str) -> None:
        # Same as LogLoaderApp
        for box in self.query(".loading-box"):
            box.remove()

        error_box = Container(
            Static("Error", classes="error-title"),
            Static(message, classes="error-content"),
            Static("Press Escape to go back", classes="error-hint"),
            classes="error-box"
        )
        self.mount(error_box)


def run_live_logs_with_loading(
    aws_client: Any,
    task: dict,
    container_name: str,
    title: str = "Live Logs",
) -> None:
    """Run live logs with loading screen first"""
    loader = LogLoaderApp(aws_client, task, container_name)
    result = loader.run()

    if result == "success" and loader.result:
        source = {
            'container': container_name,
            'log_group': loader.result['log_group'],
            'log_stream': loader.result['log_stream']
        }
        run_live_logs([source], aws_client, title)


def run_task_logs_with_loading(
    aws_client: Any,
    task: dict,
    title: str = "Task Logs",
) -> None:
    """Run task logs with loading screen first"""
    loader = TaskLogsLoaderApp(aws_client, task)
    result = loader.run()

    if result == "success" and loader.result:
        run_live_logs(loader.result, aws_client, title)
