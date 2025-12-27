"""Interactive CLI prompts using Textual"""

from typing import List, Optional, Union, Dict, Any, Callable
from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option
from textual.containers import Container, VerticalScroll
from textual.binding import Binding
from .aws_client import extract_name_from_arn


HELP_TEXT = """
[bold]ECS Connect - Keyboard Shortcuts[/bold]

[cyan]Navigation:[/cyan]
  ↑ / ↓       Navigate up/down
  ← / Escape  Go back
  → / Enter   Select / Go deeper

[cyan]Search:[/cyan]
  Type        Filter items by name

[cyan]Other:[/cyan]
  F1          Show this help (hold)
  Ctrl+C      Exit

[dim]─────────────────────────────────[/dim]
[dim]Release F1 to close[/dim]
"""


# Sentinel value for "go back"
class BackSignal:
    """Sentinel class to indicate user wants to go back."""
    pass


BACK = BackSignal()


class ECSConnectApp(App):
    """Single persistent app for ECS Connect navigation"""

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

    #help-overlay {
        dock: top;
        width: 100%;
        height: 100%;
        background: #08060d 95%;
        content-align: center middle;
        padding: 2;
    }

    #help-overlay Static {
        width: auto;
        color: #a99fc4;
        background: #1a1520;
        border: solid #3d3556;
        padding: 1 3;
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
                 initial_cluster: Optional[dict] = None):
        super().__init__()
        self.all_clusters = clusters
        self.aws_client_factory = aws_client_factory
        self.profile = profile
        self.initial_cluster = initial_cluster

        # State
        self.step = "cluster"  # cluster, service, task, container, confirm
        self.selected_cluster = None
        self.selected_service = None
        self.selected_task = None
        self.selected_container = None
        self.aws = None

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
        if self.initial_cluster:
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
        """Show loading message in status bar"""
        self._set_status(f"⏳ {message}")

    def _hide_loading(self) -> None:
        """Clear loading message"""
        self._set_status("")

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
        if cluster_arn not in self.cached_services:
            self._show_loading(f"Fetching services...")
            self.services = self.aws.list_services(cluster_arn)
            self.cached_services[cluster_arn] = self.services
            self._hide_loading()
        else:
            self.services = self.cached_services[cluster_arn]

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
        service_name = extract_name_from_arn(self.selected_service)

        self._show_loading("Fetching tasks...")
        cluster_arn = self.selected_cluster['arn']
        self.tasks = self.aws.list_tasks(cluster_arn, self.selected_service)
        self._hide_loading()

        if not self.tasks:
            self._set_status("No running tasks found")
            self._go_to_service()
            return

        # Auto-select if only one task
        if len(self.tasks) == 1:
            self.selected_task = self.tasks[0]
            self._go_to_container()
            return

        # Enrich with instance info
        self._show_loading("Getting instance info...")
        self.tasks = self.aws.enrich_tasks_with_instance_info(cluster_arn, self.tasks)
        self._hide_loading()

        self._set_status(f"Service: {service_name}")
        search = self.query_one("#search", Input)
        search.value = ""
        search.placeholder = "Type to filter tasks..."

        def display_task(t):
            task_id = extract_name_from_arn(t['taskArn'])
            instance_id = t.get('_instanceId', '')
            instance_ip = t.get('_instanceIp', '')
            if instance_id and instance_ip:
                return f"{task_id}  [{instance_id} / {instance_ip}]"
            elif instance_id:
                return f"{task_id}  [{instance_id}]"
            return task_id

        self._render_list_view(
            f"Select Task ({extract_name_from_arn(self.selected_service)})",
            self.tasks,
            display_task
        )
        search.focus()

    def _go_to_container(self) -> None:
        """Go to container selection"""
        self.step = "container"

        self._show_loading("Getting container instance...")
        cluster_arn = self.selected_cluster['arn']
        instance_id = self.aws.get_container_instance_id(cluster_arn, self.selected_task)
        self._hide_loading()

        if not instance_id:
            self._set_status("Could not determine EC2 instance")
            self._go_to_task()
            return

        self._show_loading(f"Verifying SSM access...")
        ssm_ok = self.aws.verify_ssm_access(instance_id)
        self._hide_loading()

        if not ssm_ok:
            self._set_status(f"Instance {instance_id} not accessible via SSM")
            self._go_to_task()
            return

        self.containers = self.aws.get_task_containers(self.selected_task, exclude_agent=True)

        if not self.containers:
            # No containers, go straight to SSH
            self._set_status("")
            self.result = {
                'type': 'ssh',
                'instance_id': instance_id,
                'region': self.selected_cluster['region']
            }
            self.exit()
            return

        # Auto-select if only one container
        if len(self.containers) == 1:
            self.selected_container = self.containers[0]
            self._go_to_confirm(instance_id)
            return

        self._set_status(f"Instance: {instance_id}")
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
        """Go to connection confirmation"""
        self.step = "confirm"

        if instance_id is None:
            cluster_arn = self.selected_cluster['arn']
            instance_id = self.aws.get_container_instance_id(cluster_arn, self.selected_task)

        self._instance_id = instance_id
        self._set_status(f"Instance: {instance_id}")

        search = self.query_one("#search", Input)
        search.value = ""
        search.placeholder = ""

        options = [
            ("container", "Container"),
            ("ssh", "SSH to host"),
        ]

        self._render_list_view(
            "Proceed connection to:",
            options,
            lambda x: x[1]
        )
        search.focus()

    # ==================== SELECTION HANDLING ====================

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
            choice = item[0]  # "container" or "ssh"
            container_id = self.selected_container.get('runtimeId') if self.selected_container else None

            self.result = {
                'type': choice,
                'instance_id': self._instance_id,
                'container_id': container_id,
                'region': self.selected_cluster['region']
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
            def display_task(t):
                task_id = extract_name_from_arn(t['taskArn'])
                instance_id = t.get('_instanceId', '')
                instance_ip = t.get('_instanceIp', '')
                if instance_id and instance_ip:
                    return f"{task_id}  [{instance_id} / {instance_ip}]"
                elif instance_id:
                    return f"{task_id}  [{instance_id}]"
                return task_id
            self._render_list_view(
                f"Select Task ({extract_name_from_arn(self.selected_service)})",
                self.tasks,
                display_task,
                filter_text=event.value
            )
        elif self.step == "container":
            self._render_list_view(
                "Select Container",
                self.containers,
                lambda c: f"{c['name']} ({c.get('lastStatus', 'unknown')})",
                filter_text=event.value
            )
        elif self.step == "confirm":
            options = [
                ("container", "Container"),
                ("ssh", "SSH to host"),
            ]
            self._render_list_view(
                "Proceed connection to:",
                options,
                lambda x: x[1],
                filter_text=event.value
            )

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
        else:
            # List view
            if event.option_index in self.index_to_item:
                item = self.index_to_item[event.option_index]
                self._handle_list_select(item)

    def action_select_current(self) -> None:
        """Select currently highlighted item"""
        if self.step == "cluster":
            self._handle_cluster_select()
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

    def _is_help_visible(self) -> bool:
        """Check if help overlay is visible"""
        try:
            self.query_one("#help-overlay")
            return True
        except Exception:
            return False

    def on_key(self, event) -> None:
        """Handle key presses"""
        # F1 toggles help
        if event.key == "f1":
            event.prevent_default()
            event.stop()
            if self._is_help_visible():
                self._hide_help()
            else:
                self._show_help()
            return

        # Any key hides help if visible
        if self._is_help_visible():
            self._hide_help()
            event.prevent_default()
            event.stop()
            return

        # Block tab
        if event.key in ("tab", "shift+tab"):
            event.prevent_default()
            event.stop()
        # Intercept left/right for navigation (not text cursor)
        elif event.key == "left":
            event.prevent_default()
            event.stop()
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
                    initial_cluster: Optional[dict] = None) -> Optional[dict]:
    """
    Run the ECS Connect interactive UI.
    Returns result dict with connection info, or None if cancelled.
    """
    if not clusters:
        print("No clusters found")
        return None

    app = ECSConnectApp(clusters, aws_client_class, profile, initial_cluster)
    app.run()

    if app.cancelled:
        return None

    # Include selected cluster in result for resuming later
    if app.result and app.selected_cluster:
        app.result['cluster'] = app.selected_cluster

    return app.result
