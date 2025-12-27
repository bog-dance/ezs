"""Interactive CLI prompts using Textual"""

from typing import List, Optional, Union, Dict, Any, Callable
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static, LoadingIndicator
from textual.widgets.option_list import Option
from textual.containers import Container, VerticalScroll, Horizontal
from textual.binding import Binding
from textual.worker import Worker, WorkerState
from .aws_client import extract_name_from_arn


HELP_TEXT = """
[bold]EZS - Keyboard Shortcuts[/bold]
[dim]ECS, but easy[/dim]

[cyan]Navigation:[/cyan]
  ↑ / ↓       Navigate up/down
  ← / Escape  Go back
  → / Enter   Select / Go deeper

[cyan]Search:[/cyan]
  Type        Filter items by name

[cyan]Other:[/cyan]
  F1          Show this help
  Ctrl+C      Exit

[dim]─────────────────────────────────[/dim]
[dim]Press Escape to close[/dim]
"""


# Sentinel value for "go back"
class BackSignal:
    """Sentinel class to indicate user wants to go back."""
    pass


BACK = BackSignal()


class ECSConnectApp(App):
    """Single persistent app for EZS navigation"""

    CSS = """
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

    #search {
        dock: top;
        margin: 1 1 0 1;
        background: #0f0c16;
        border: solid #3d3556;
    }

    #search:focus {
        border: solid #5c4a6e;
    }

    #status {
        dock: bottom;
        height: 1;
        background: #3d3556;
        color: #a99fc4;
        padding: 0 1;
    }

    #counter {
        dock: bottom;
        height: 1;
        background: #0f0c16;
        color: #6a6080;
        padding: 0 1;
    }

    #scroll-area {
        margin: 1;
        background: #08060d;
    }

    RegionBox {
        border: solid #3d3556;
        border-title-color: #a99fc4;
        border-title-background: #3d3556;
        height: auto;
        width: 42;
        margin: 0 0 1 0;
        padding: 0;
        background: #08060d;
    }

    RegionBox > OptionList {
        height: auto;
        max-height: 14;
        width: 100%;
        background: #08060d;
        color: #8a7fa0;
        scrollbar-size: 1 1;
        scrollbar-color: #b0a7be;
        scrollbar-background: #1a1520;
    }

    RegionBox > OptionList:focus {
        border: none;
    }

    #options {
        margin: 1;
        height: 100%;
        scrollbar-size: 1 1;
        scrollbar-color: #b0a7be;
        scrollbar-background: #1a1520;
        background: #08060d;
    }

    OptionList {
        background: #08060d;
        color: #8a7fa0;
    }

    OptionList > .option-list--option-disabled {
        color: #3a3548;
        text-style: dim;
    }

    OptionList > .option-list--option-highlighted {
        background: #b0a7be;
        color: #08060d;
    }

    OptionList > .option-list--option-hover {
        background: #1a1520;
    }

    OptionList:focus {
        border: solid #5c4a6e;
    }

    #action-row {
        width: 100%;
        height: auto;
        layout: horizontal;
    }

    #action-row RegionBox {
        width: 1fr;
        height: auto;
        margin: 0 1;
    }

    #help-overlay {
        width: 100%;
        height: 100%;
        background: #08060d 95%;
        align: center middle;
        layer: overlay;
    }

    #help-overlay Static {
        width: auto;
        height: auto;
        color: #a99fc4;
        background: #1a1520;
        border: solid #3d3556;
        padding: 1 3;
    }

    .loading-overlay {
        dock: top;
        width: 100%;
        height: 100%;
        background: #08060d 95%;
        align: center middle;
        layer: overlay;
    }

    #loading-box {
        width: 46;
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
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("left", "go_back", "Back", show=False),
        Binding("enter", "select_current", "Select", show=True),
        Binding("right", "select_current", "Select", show=False),
        Binding("ctrl+c", "quit_app", "Exit", show=False),
        Binding("ctrl+d", "quit_app", "Exit", show=False),
        Binding("up", "nav_up", "Up", show=False),
        Binding("down", "nav_down", "Down", show=False),
        Binding("tab", "noop", show=False),
        Binding("shift+tab", "noop", show=False),
    ]

    def __init__(self, clusters: List[dict], aws_client_factory, profile: Optional[str] = None,
                 initial_cluster: Optional[dict] = None, resume_context: Optional[dict] = None):
        super().__init__()
        self.all_clusters = clusters
        self.aws_client_factory = aws_client_factory
        self.profile = profile
        self.initial_cluster = initial_cluster
        self.resume_context = resume_context

        # State
        self.step = "cluster"  # cluster, service, task, container, confirm, time_select
        self.selected_cluster = None
        self.selected_service = None
        self.selected_task = None
        self.selected_container = None
        self.selected_action = None  # For logs actions
        self.aws = None
        self._instance_id = None

        # Cached data
        self.cached_services = {}
        self.services = []
        self.tasks = []
        self.containers = []

        # Navigation for cluster view
        self.regions_order = []
        self.clusters_by_region = {}
        self.nav_list = []  # Flat list for cluster navigation
        self.nav_index = 0

        # Navigation for other views
        self.items = []
        self.index_to_item = {}
        self.first_item_idx = None

        # Result
        self.result = None  # Will be set when user makes final choice
        self.cancelled = False
        self._render_id = 0  # For unique widget IDs
        self._current_options_id = None  # Current options list ID

        # Group clusters by region
        for c in clusters:
            region = c['region']
            if region not in self.clusters_by_region:
                self.regions_order.append(region)
                self.clusters_by_region[region] = []
            self.clusters_by_region[region].append(c)

    def compose(self) -> ComposeResult:
        yield Static("Select ECS Cluster", id="title")
        yield Input(placeholder="Type to filter...", id="search")
        yield VerticalScroll(id="scroll-area")
        yield Static("", id="counter")
        yield Static("", id="status")

    def on_mount(self) -> None:
        if self.resume_context:
            # Resume from Select Action with full context
            self.selected_cluster = self.resume_context.get('cluster')
            self.selected_service = self.resume_context.get('service')
            self.selected_task = self.resume_context.get('task')
            self.selected_container = self.resume_context.get('container')
            self._instance_id = self.resume_context.get('instance_id')

            if self.selected_cluster:
                self.aws = self.aws_client_factory(
                    region=self.selected_cluster['region'],
                    profile=self.profile
                )
                self._go_to_confirm(self._instance_id)
            else:
                self._render_cluster_view()
                self.query_one("#search", Input).focus()
        elif self.initial_cluster:
            # Resume from service selection for the given cluster
            self.selected_cluster = self.initial_cluster
            self.aws = self.aws_client_factory(
                region=self.initial_cluster['region'],
                profile=self.profile
            )
            self._go_to_service()
        else:
            self._render_cluster_view()
            self.query_one("#search", Input).focus()

    def _set_status(self, message: str) -> None:
        """Update status bar"""
        self.query_one("#status", Static).update(message)

    def _show_loading(self, message: str = "Loading...") -> None:
        """Show loading overlay centered on screen with spinner"""
        # Remove all existing loading overlays first
        self._hide_loading()
        self._render_id += 1
        loading_box = Container(
            LoadingIndicator(),
            Static(message, markup=True),
            id="loading-box"
        )
        overlay = Container(loading_box, classes="loading-overlay")
        self.mount(overlay)

    def _hide_loading(self) -> None:
        """Hide all loading overlays"""
        for overlay in self.query(".loading-overlay"):
            overlay.remove()

    def _is_loading(self) -> bool:
        """Check if loading overlay is visible"""
        return len(self.query(".loading-overlay")) > 0

    def _show_help(self) -> None:
        """Show help overlay"""
        try:
            self.query_one("#help-overlay").remove()
        except Exception:
            pass
        overlay = Container(Static(HELP_TEXT, markup=True), id="help-overlay")
        self.mount(overlay)

    def _hide_help(self) -> None:
        """Hide help overlay"""
        try:
            self.query_one("#help-overlay").remove()
        except Exception:
            pass

    def _set_title(self, title: str) -> None:
        """Update title bar"""
        self.query_one("#title", Static).update(title)

    def _clear_scroll_area(self) -> None:
        """Clear the scroll area"""
        scroll = self.query_one("#scroll-area", VerticalScroll)
        # Remove all children explicitly
        for child in list(scroll.children):
            child.remove()

    # ==================== CLUSTER VIEW ====================

    def _render_cluster_view(self, filter_text: str = "") -> None:
        """Render cluster selection with region boxes"""
        self._set_title("Select ECS Cluster")
        self._clear_scroll_area()

        scroll = self.query_one("#scroll-area", VerticalScroll)
        filter_lower = filter_text.lower() if filter_text else ""

        self.nav_list = []
        total_matches = 0

        for region in self.regions_order:
            clusters = self.clusters_by_region[region]

            if filter_lower:
                filtered = [c for c in clusters if filter_lower in c['name'].lower()]
            else:
                filtered = clusters

            if not filtered:
                continue

            region_name = clusters[0]['region_name']
            box = RegionBox(region_name, region)
            box.border_title = f" {region_name} ({region}) "
            scroll.mount(box)

            option_list = OptionList(id=f"list-{region}")
            box.mount(option_list)

            for idx, c in enumerate(filtered):
                option_list.add_option(Option(c['name']))
                self.nav_list.append((region, idx, c))
                total_matches += 1

        # Update counter
        counter = self.query_one("#counter", Static)
        if filter_text:
            counter.update(f" {total_matches}/{len(self.all_clusters)} clusters")
        else:
            counter.update(f" {len(self.all_clusters)} clusters")

        # Reset navigation and highlight first item
        self.nav_index = 0
        if self.nav_list:
            # Schedule highlight update after render
            self.call_after_refresh(self._update_cluster_highlight)

    def _update_cluster_highlight(self) -> None:
        """Update visual highlight for cluster view"""
        # Clear all highlights
        for region in self.regions_order:
            try:
                option_list = self.query_one(f"#list-{region}", OptionList)
                option_list.highlighted = None
            except Exception:
                pass

        # Set highlight on current nav item
        if self.nav_list and 0 <= self.nav_index < len(self.nav_list):
            region, local_idx, _ = self.nav_list[self.nav_index]
            try:
                option_list = self.query_one(f"#list-{region}", OptionList)
                option_list.highlighted = local_idx
                option_list.scroll_to_highlight()
            except Exception:
                pass

    # ==================== LIST VIEW (services, tasks, containers, confirm) ====================

    def _render_list_view(self, title: str, items: List[Any], display_fn: Callable,
                          filter_text: str = "") -> None:
        """Render a simple list view"""
        self._set_title(title)
        self._clear_scroll_area()
        self._render_id += 1

        scroll = self.query_one("#scroll-area", VerticalScroll)
        self._current_options_id = f"options-{self._render_id}"
        option_list = OptionList(id=self._current_options_id)
        scroll.mount(option_list)

        self.items = items
        self.index_to_item = {}
        self.first_item_idx = None

        option_idx = 0
        filter_lower = filter_text.lower() if filter_text else ""
        total_matches = 0

        # Add items
        for item in items:
            display = display_fn(item)
            if filter_lower and filter_lower not in display.lower():
                continue

            option_list.add_option(Option(display))
            self.index_to_item[option_idx] = item
            if self.first_item_idx is None:
                self.first_item_idx = option_idx
            option_idx += 1
            total_matches += 1

        # Update counter
        counter = self.query_one("#counter", Static)
        if filter_text:
            counter.update(f" {total_matches}/{len(items)} items")
        else:
            counter.update(f" {len(items)} items")

        # Highlight first item (not back)
        if self.first_item_idx is not None:
            option_list.highlighted = self.first_item_idx

    # ==================== STEP TRANSITIONS ====================

    def _go_to_cluster(self) -> None:
        """Go to cluster selection"""
        self.step = "cluster"
        self._set_status("")
        search = self.query_one("#search", Input)
        search.value = ""
        search.placeholder = "Type to filter clusters..."
        self._render_cluster_view()
        search.focus()

    def _go_to_service(self) -> None:
        """Go to service selection"""
        self.step = "service"
        cluster_arn = self.selected_cluster['arn']

        # Use cache if available
        if cluster_arn in self.cached_services:
            self.services = self.cached_services[cluster_arn]
            self._render_service_view()
        else:
            self._show_loading("Fetching services...")
            self.run_worker(
                self._fetch_services,
                name="fetch_services",
                exclusive=True,
                thread=True
            )

    def _fetch_services(self) -> list:
        """Worker: fetch services from AWS"""
        cluster_arn = self.selected_cluster['arn']
        return self.aws.list_services(cluster_arn)

    def _render_service_view(self) -> None:
        """Render service selection view"""
        self._set_status(f"Cluster: {self.selected_cluster['name']}")
        search = self.query_one("#search", Input)
        search.value = ""
        search.placeholder = "Type to filter services..."
        self._render_list_view(
            f"Select Service ({self.selected_cluster['name']})",
            self.services,
            extract_name_from_arn
        )
        search.focus()

    def _go_to_task(self) -> None:
        """Go to task selection"""
        self.step = "task"
        self._show_loading("Fetching tasks...")
        self.run_worker(
            self._fetch_tasks,
            name="fetch_tasks",
            exclusive=True,
            thread=True
        )

    def _fetch_tasks(self) -> list:
        """Worker: fetch tasks and enrich with instance info"""
        cluster_arn = self.selected_cluster['arn']
        tasks = self.aws.list_tasks(cluster_arn, self.selected_service)
        if tasks and len(tasks) > 1:
            tasks = self.aws.enrich_tasks_with_instance_info(cluster_arn, tasks)
        return tasks

    def _render_task_view(self) -> None:
        """Render task selection view"""
        service_name = extract_name_from_arn(self.selected_service)
        self._set_status(f"Service: {service_name}")
        search = self.query_one("#search", Input)
        search.value = ""
        search.placeholder = "Type to filter tasks..."

        self._render_list_view(
            f"Select Task ({service_name})",
            self.tasks,
            self._display_task
        )
        search.focus()

    def _display_task(self, t: dict) -> str:
        """Format task for display"""
        task_id = extract_name_from_arn(t['taskArn'])
        instance_id = t.get('_instanceId', '')
        instance_ip = t.get('_instanceIp', '')
        if instance_id and instance_ip:
            return f"{task_id}  [{instance_id} / {instance_ip}]"
        elif instance_id:
            return f"{task_id}  [{instance_id}]"
        return task_id

    def _go_to_container(self) -> None:
        """Go to container selection"""
        self.step = "container"
        self._show_loading("Getting container instance...")
        self.run_worker(
            self._fetch_container_info,
            name="fetch_container_info",
            exclusive=True,
            thread=True
        )

    def _fetch_container_info(self) -> dict:
        """Worker: get instance ID, verify SSM, get containers"""
        cluster_arn = self.selected_cluster['arn']
        instance_id = self.aws.get_container_instance_id(cluster_arn, self.selected_task)

        if not instance_id:
            return {'error': 'no_instance'}

        ssm_ok = self.aws.verify_ssm_access(instance_id)
        if not ssm_ok:
            return {'error': 'no_ssm', 'instance_id': instance_id}

        containers = self.aws.get_task_containers(self.selected_task, exclude_agent=True)
        return {
            'instance_id': instance_id,
            'containers': containers
        }

    def _render_container_view(self) -> None:
        """Render container selection view"""
        self._set_status(f"Instance: {self._instance_id}")
        search = self.query_one("#search", Input)
        search.value = ""
        search.placeholder = ""

        self._render_list_view(
            "Select Container",
            self.containers,
            lambda c: f"{c['name']} ({c.get('lastStatus', 'unknown')})"
        )
        search.focus()

    def _go_to_confirm(self, instance_id: str = None) -> None:
        """Go to action selection (SSH or Logs)"""
        self.step = "confirm"

        if instance_id is None:
            cluster_arn = self.selected_cluster['arn']
            instance_id = self.aws.get_container_instance_id(cluster_arn, self.selected_task)

        self._instance_id = instance_id
        self._set_status(f"Instance: {instance_id}")

        search = self.query_one("#search", Input)
        search.value = ""
        search.placeholder = ""

        self._render_confirm_view()
        search.focus()

    def _render_confirm_view(self, filter_text: str = "") -> None:
        """Render confirm view with SSH and Logs sections side by side"""
        self._set_title("Select Action")
        self._clear_scroll_area()

        scroll = self.query_one("#scroll-area", VerticalScroll)

        # All available items (stored for filtering)
        self._all_ssh_items = [
            ("container", "Container"),
            ("ssh", "Host"),
        ]
        self._all_logs_items = [
            ("logs_live", "Live logs"),
            ("logs_download", "Download logs"),
        ]

        # Initially show all
        self.ssh_items = self._all_ssh_items[:]
        self.logs_items = self._all_logs_items[:]

        # Horizontal container for both sections
        row = Horizontal(id="action-row")
        scroll.mount(row)

        # SSH section (left)
        ssh_box = RegionBox("SSH", "ssh")
        ssh_box.border_title = " SSH "
        row.mount(ssh_box)

        ssh_options = OptionList(id="list-ssh")
        ssh_box.mount(ssh_options)

        for key, label in self.ssh_items:
            ssh_options.add_option(Option(label))

        # Logs section (right)
        logs_box = RegionBox("Logs", "logs")
        logs_box.border_title = " Logs "
        row.mount(logs_box)

        logs_options = OptionList(id="list-logs")
        logs_box.mount(logs_options)

        for key, label in self.logs_items:
            logs_options.add_option(Option(label))

        # Track current section and index
        self._confirm_section = "ssh"
        self._confirm_idx = 0

    def _filter_confirm_view(self, filter_text: str) -> None:
        """Filter items in confirm view without re-rendering"""
        filter_lower = filter_text.lower()

        # Filter items
        self.ssh_items = [
            item for item in self._all_ssh_items
            if not filter_text or filter_lower in item[1].lower()
        ]
        self.logs_items = [
            item for item in self._all_logs_items
            if not filter_text or filter_lower in item[1].lower()
        ]

        # Update SSH OptionList
        try:
            ssh_options = self.query_one("#list-ssh", OptionList)
            ssh_options.clear_options()
            for key, label in self.ssh_items:
                ssh_options.add_option(Option(label))
        except Exception:
            pass

        # Update Logs OptionList
        try:
            logs_options = self.query_one("#list-logs", OptionList)
            logs_options.clear_options()
            for key, label in self.logs_items:
                logs_options.add_option(Option(label))
        except Exception:
            pass

        # Update counter
        counter = self.query_one("#counter", Static)
        counter.update(f" {len(self.ssh_items) + len(self.logs_items)} actions")

        # Reset selection to first available item
        if self.ssh_items:
            self._confirm_section = "ssh"
            self._confirm_idx = 0
        elif self.logs_items:
            self._confirm_section = "logs"
            self._confirm_idx = 0
        else:
            self._confirm_section = "ssh"
            self._confirm_idx = 0

        self.call_after_refresh(self._update_confirm_highlight)

    def _update_confirm_highlight(self) -> None:
        """Update visual highlight for confirm view"""
        # Clear all highlights
        for section in ("ssh", "logs"):
            try:
                option_list = self.query_one(f"#list-{section}", OptionList)
                option_list.highlighted = None
            except Exception:
                pass

        # Set highlight on current section/item
        try:
            option_list = self.query_one(f"#list-{self._confirm_section}", OptionList)
            option_list.highlighted = self._confirm_idx
        except Exception:
            pass

    # ==================== SELECTION HANDLING ====================

    def _handle_confirm_select(self, item: tuple) -> None:
        """Handle selection in confirm view"""
        choice = item[0]
        container_id = self.selected_container.get('runtimeId') if self.selected_container else None

        if choice in ("container", "ssh"):
            # SSH actions
            self.result = {
                'type': choice,
                'instance_id': self._instance_id,
                'container_id': container_id,
                'region': self.selected_cluster['region']
            }
            self.exit()
        elif choice == "logs_live":
            # Live logs
            self.result = {
                'type': 'logs_live',
                'cluster': self.selected_cluster,
                'task': self.selected_task,
                'container': self.selected_container,
                'region': self.selected_cluster['region']
            }
            self.exit()
        elif choice == "logs_download":
            # Go to time selection
            self.selected_action = "logs_download"
            self._go_to_time_select()

    def _go_to_time_select(self) -> None:
        """Go to time range selection for log download"""
        self.step = "time_select"
        self._set_status("Select time range")

        search = self.query_one("#search", Input)
        search.value = ""
        search.placeholder = ""

        time_options = [
            (5, "Last 5 minutes"),
            (15, "Last 15 minutes"),
            (30, "Last 30 minutes"),
            (60, "Last 1 hour"),
            (120, "Last 2 hours"),
            (360, "Last 6 hours"),
            (720, "Last 12 hours"),
            (1440, "Last 24 hours"),
        ]

        self._render_list_view(
            "Download logs - Select time range",
            time_options,
            lambda x: x[1]
        )
        search.focus()

    def _handle_cluster_select(self) -> None:
        """Handle cluster selection"""
        if self.nav_list and 0 <= self.nav_index < len(self.nav_list):
            _, _, cluster = self.nav_list[self.nav_index]
            self.selected_cluster = cluster
            self._set_status(f"Connecting to {cluster['name']}...")
            self.refresh()

            # Initialize AWS client
            self.aws = self.aws_client_factory(
                region=cluster['region'],
                profile=self.profile
            )

            self._go_to_service()

    def _handle_list_select(self, item: Any) -> None:
        """Handle selection in list views"""
        if self.step == "service":
            self.selected_service = item
            self._set_status(f"Selected: {extract_name_from_arn(item)}")
            self._go_to_task()

        elif self.step == "task":
            self.selected_task = item
            self._set_status(f"Selected: {extract_name_from_arn(item['taskArn'])}")
            self._go_to_container()

        elif self.step == "container":
            self.selected_container = item
            cluster_arn = self.selected_cluster['arn']
            instance_id = self.aws.get_container_instance_id(cluster_arn, self.selected_task)
            self._go_to_confirm(instance_id)

        elif self.step == "confirm":
            self._handle_confirm_select(item)

        elif self.step == "time_select":
            # item is (minutes, label)
            minutes = item[0]
            self.result = {
                'type': 'logs_download',
                'cluster': self.selected_cluster,
                'task': self.selected_task,
                'container': self.selected_container,
                'region': self.selected_cluster['region'],
                'minutes': minutes
            }
            self.exit()

    def _handle_back(self) -> None:
        """Handle back navigation"""
        if self.step == "cluster":
            self.cancelled = True
            self.exit()
        elif self.step == "service":
            self._go_to_cluster()
        elif self.step == "task":
            self._go_to_service()
        elif self.step == "container":
            self._go_to_task()
        elif self.step == "confirm":
            self._go_to_service()  # Skip task/container auto-select
        elif self.step == "time_select":
            self._go_to_confirm(self._instance_id)

    # ==================== EVENT HANDLERS ====================

    def on_input_changed(self, event: Input.Changed) -> None:
        """Handle search input"""
        if self.step == "cluster":
            self._render_cluster_view(event.value)
        elif self.step == "service":
            self._render_list_view(
                f"Select Service ({self.selected_cluster['name']})",
                self.services,
                extract_name_from_arn,
                filter_text=event.value
            )
        elif self.step == "task":
            self._render_list_view(
                f"Select Task ({extract_name_from_arn(self.selected_service)})",
                self.tasks,
                self._display_task,
                filter_text=event.value
            )
        elif self.step == "container":
            self._render_list_view(
                "Select Container",
                self.containers,
                lambda c: f"{c['name']} ({c.get('lastStatus', 'unknown')})",
                filter_text=event.value
            )
        elif self.step == "time_select":
            time_options = [
                (5, "Last 5 minutes"),
                (15, "Last 15 minutes"),
                (30, "Last 30 minutes"),
                (60, "Last 1 hour"),
                (120, "Last 2 hours"),
                (360, "Last 6 hours"),
                (720, "Last 12 hours"),
                (1440, "Last 24 hours"),
            ]
            self._render_list_view(
                "Download logs - Select time range",
                time_options,
                lambda x: x[1],
                filter_text=event.value
            )
        elif self.step == "confirm":
            self._filter_confirm_view(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle enter in search field"""
        self.action_select_current()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle mouse click on option"""
        if self.step == "cluster":
            # Find clicked cluster
            option_list = event.option_list
            for region in self.regions_order:
                if option_list.id == f"list-{region}":
                    for i, (r, idx, cluster) in enumerate(self.nav_list):
                        if r == region and idx == event.option_index:
                            self.nav_index = i
                            self._handle_cluster_select()
                            return
        elif self.step == "confirm":
            # Find clicked action in confirm view
            option_list = event.option_list
            for section in ("ssh", "logs"):
                if option_list.id == f"list-{section}":
                    self._confirm_section = section
                    self._confirm_idx = event.option_index
                    items = self.ssh_items if section == "ssh" else self.logs_items
                    if 0 <= event.option_index < len(items):
                        self._handle_confirm_select(items[event.option_index])
                    return
        else:
            # List view
            if event.option_index in self.index_to_item:
                item = self.index_to_item[event.option_index]
                self._handle_list_select(item)

    def action_select_current(self) -> None:
        """Select currently highlighted item"""
        if self.step == "cluster":
            self._handle_cluster_select()
        elif self.step == "confirm":
            # Get current item from section
            items = self.ssh_items if self._confirm_section == "ssh" else self.logs_items
            if 0 <= self._confirm_idx < len(items):
                self._handle_confirm_select(items[self._confirm_idx])
        else:
            try:
                option_list = self.query_one(f"#{self._current_options_id}", OptionList)
                highlighted = option_list.highlighted
                if highlighted is not None and highlighted in self.index_to_item:
                    item = self.index_to_item[highlighted]
                    self._handle_list_select(item)
            except Exception:
                pass

    def action_go_back(self) -> None:
        """Go back to previous step"""
        self._handle_back()

    def action_nav_up(self) -> None:
        """Navigate up"""
        if self.step == "cluster":
            if self.nav_list:
                if self.nav_index > 0:
                    self.nav_index -= 1
                else:
                    self.nav_index = len(self.nav_list) - 1
                self._update_cluster_highlight()
        elif self.step == "confirm":
            # Stay within current section
            items = self.ssh_items if self._confirm_section == "ssh" else self.logs_items
            if self._confirm_idx > 0:
                self._confirm_idx -= 1
            else:
                self._confirm_idx = len(items) - 1
            self._update_confirm_highlight()
        else:
            try:
                option_list = self.query_one(f"#{self._current_options_id}", OptionList)
                option_list.action_cursor_up()
            except Exception:
                pass

    def action_nav_down(self) -> None:
        """Navigate down"""
        if self.step == "cluster":
            if self.nav_list:
                if self.nav_index < len(self.nav_list) - 1:
                    self.nav_index += 1
                else:
                    self.nav_index = 0
                self._update_cluster_highlight()
        elif self.step == "confirm":
            # Stay within current section
            items = self.ssh_items if self._confirm_section == "ssh" else self.logs_items
            if self._confirm_idx < len(items) - 1:
                self._confirm_idx += 1
            else:
                self._confirm_idx = 0
            self._update_confirm_highlight()
        else:
            try:
                option_list = self.query_one(f"#{self._current_options_id}", OptionList)
                option_list.action_cursor_down()
            except Exception:
                pass

    def action_noop(self) -> None:
        """Do nothing - absorb tab key"""
        pass

    def action_quit_app(self) -> None:
        """Quit application"""
        self.cancelled = True
        self.exit()

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        """Handle worker completion"""
        if event.state != WorkerState.SUCCESS:
            return

        worker_name = event.worker.name
        result = event.worker.result
        self._hide_loading()

        if worker_name == "fetch_services":
            cluster_arn = self.selected_cluster['arn']
            self.services = result
            self.cached_services[cluster_arn] = result
            self._render_service_view()

        elif worker_name == "fetch_tasks":
            self.tasks = result
            if not self.tasks:
                self._set_status("No running tasks found")
                self._go_to_service()
                return
            # Auto-select if only one task
            if len(self.tasks) == 1:
                self.selected_task = self.tasks[0]
                self._go_to_container()
                return
            self._render_task_view()

        elif worker_name == "fetch_container_info":
            if result.get('error') == 'no_instance':
                self._set_status("Could not determine EC2 instance")
                self._go_to_task()
                return
            if result.get('error') == 'no_ssm':
                self._set_status(f"Instance {result['instance_id']} not accessible via SSM")
                self._go_to_task()
                return

            self._instance_id = result['instance_id']
            self.containers = result['containers']

            if not self.containers:
                # No containers, go straight to SSH
                self._set_status("")
                self.result = {
                    'type': 'ssh',
                    'instance_id': self._instance_id,
                    'region': self.selected_cluster['region']
                }
                self.exit()
                return

            # Auto-select if only one container
            if len(self.containers) == 1:
                self.selected_container = self.containers[0]
                self._go_to_confirm(self._instance_id)
                return

            self._render_container_view()

    def _is_help_visible(self) -> bool:
        """Check if help overlay is visible"""
        try:
            self.query_one("#help-overlay")
            return True
        except Exception:
            return False

    def on_key(self, event) -> None:
        """Handle key presses"""
        # Block all input during loading (except Ctrl+C)
        if self._is_loading():
            if event.key not in ("ctrl+c", "ctrl+d"):
                event.prevent_default()
                event.stop()
            return

        # F1 toggles help
        if event.key == "f1":
            event.prevent_default()
            event.stop()
            if self._is_help_visible():
                self._hide_help()
            else:
                self._show_help()
            return

        # Escape closes help if visible
        if self._is_help_visible():
            if event.key == "escape":
                self._hide_help()
                event.prevent_default()
                event.stop()
                return
            # Block other keys while help is visible
            event.prevent_default()
            event.stop()
            return

        # Tab switches between sections in confirm view
        if event.key in ("tab", "shift+tab"):
            event.prevent_default()
            event.stop()
            if self.step == "confirm":
                # Toggle between ssh and logs sections
                if self._confirm_section == "ssh":
                    self._confirm_section = "logs"
                else:
                    self._confirm_section = "ssh"
                self._confirm_idx = 0
                self._update_confirm_highlight()
            return
        # Intercept left/right for navigation (not text cursor)
        elif event.key == "left":
            event.prevent_default()
            event.stop()
            # Don't exit from cluster view with left arrow
            if self.step != "cluster":
                self._handle_back()
        elif event.key == "right":
            event.prevent_default()
            event.stop()
            self.action_select_current()


class RegionBox(Container):
    """A bordered container for a region's clusters"""

    def __init__(self, region_name: str, region_id: str):
        super().__init__()
        self.region_name = region_name
        self.region_id = region_id


# ==================== PUBLIC API ====================

def run_ecs_connect(clusters: List[dict], aws_client_class, profile: Optional[str] = None,
                    initial_cluster: Optional[dict] = None,
                    resume_context: Optional[dict] = None) -> Optional[dict]:
    """
    Run the EZS interactive UI.
    Returns result dict with connection info, or None if cancelled.

    resume_context: dict with keys to resume from Select Action:
        - cluster, service, task, container, instance_id
    """
    if not clusters:
        print("No clusters found")
        return None

    app = ECSConnectApp(clusters, aws_client_class, profile, initial_cluster, resume_context)
    app.run()

    if app.cancelled:
        return None

    # Include context in result for resuming later
    if app.result:
        app.result['cluster'] = app.selected_cluster
        app.result['service'] = app.selected_service
        app.result['task'] = app.selected_task
        app.result['container'] = app.selected_container
        app.result['instance_id'] = getattr(app, '_instance_id', None)

    return app.result
