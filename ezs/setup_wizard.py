"""Setup wizard for first-time configuration"""

from typing import List, Optional, Set
from textual.app import App, ComposeResult
from textual.widgets import Static, OptionList, LoadingIndicator, Input
from textual.widgets.option_list import Option
from textual.containers import Container, VerticalScroll, Horizontal
from textual.binding import Binding
from textual.worker import Worker, WorkerState

from .config_manager import (
    get_all_aws_regions,
    detect_ecs_regions,
    get_region_display_name,
    save_regions,
)


class SetupWizardApp(App):
    """Setup wizard for selecting AWS regions"""

    CSS = """
    * {
        scrollbar-size: 0 0;
    }

    Screen {
        background: #08060d;
        overflow: hidden;
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
        width: 44;
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
        scrollbar-size: 0 0;
    }

    OptionList {
        width: 44;
        height: auto;
        background: #08060d;
        color: #8a7fa0;
        border: solid #3d3556;
        scrollbar-size: 0 0;
    }

    OptionList > .option-list--option-highlighted {
        background: #b0a7be;
        color: #08060d;
    }

    OptionList:focus {
        border: solid #5c4a6e;
    }

    #method-row {
        width: 100%;
        height: auto;
        layout: horizontal;
        align: center middle;
    }

    .method-box {
        width: 28;
        height: auto;
        border: solid #3d3556;
        margin: 0 8;
        padding: 0;
        background: #08060d;
    }

    .method-box.selected {
        border: solid #5c4a6e;
        background: #1a1520;
    }

    .method-title {
        text-style: bold;
        color: #a99fc4;
        padding: 1 2;
        text-align: center;
    }

    .method-box.selected .method-title {
        background: #b0a7be;
        color: #08060d;
    }

    .method-desc {
        color: #6a6080;
        padding: 0 2 1 2;
        text-align: center;
    }

    .loading-overlay {
        width: 100%;
        height: 100%;
        background: #08060d 95%;
        align: center middle;
        layer: overlay;
        scrollbar-size: 0 0;
        overflow: hidden;
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
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "go_back", "Back", show=True),
        Binding("enter", "confirm", "Save", show=True),
        Binding("space", "toggle_region", "Toggle", show=True, priority=True),
        Binding("up", "nav_up", "Up", show=False),
        Binding("down", "nav_down", "Down", show=False),
        Binding("ctrl+c", "cancel", "Exit", show=False),
        Binding("tab", "noop", show=False),
        Binding("shift+tab", "noop", show=False),
    ]

    def __init__(self, profile: Optional[str] = None):
        super().__init__()
        self.profile = profile
        self.step = "choose_method"  # choose_method, manual_select, auto_detect
        self.all_regions: List[str] = []
        self.selected_regions: Set[str] = set()
        self.result: Optional[List[str]] = None
        self.cancelled = False
        self._scan_progress = (0, 0, "")
        self._current_index = 0
        self._render_id = 0
        self._method_index = 0  # 0 = auto-detect, 1 = manual

    def compose(self) -> ComposeResult:
        yield Static("EZS Setup", id="title")
        yield Input(placeholder="Type to filter regions...", id="search")
        yield VerticalScroll(id="scroll-area")
        yield Static("", id="counter")
        yield Static("", id="status")

    def on_mount(self) -> None:
        self._render_choose_method()

    def _set_title(self, title: str) -> None:
        self.query_one("#title", Static).update(title)

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    def _clear_scroll_area(self) -> None:
        scroll = self.query_one("#scroll-area", VerticalScroll)
        for child in list(scroll.children):
            child.remove()
        self._render_id += 1

    def _show_loading(self, message: str = "Loading...") -> None:
        self._hide_loading()
        loading_box = Container(
            LoadingIndicator(),
            Static(message, markup=True, id="loading-message"),
            Static("", id="progress-text"),
            id="loading-box"
        )
        overlay = Container(loading_box, classes="loading-overlay")
        self.mount(overlay)

    def _hide_loading(self) -> None:
        for overlay in self.query(".loading-overlay"):
            overlay.remove()

    def _update_loading_progress(self, current: int, total: int, region: str) -> None:
        self._scan_progress = (current, total, region)
        self.call_from_thread(self._do_update_progress)

    def _do_update_progress(self) -> None:
        current, total, region = self._scan_progress
        try:
            progress = self.query_one("#progress-text", Static)
            progress.update(f"[dim]{current}/{total} - {region}[/dim]")
        except Exception:
            pass

    # ==================== CHOOSE METHOD ====================

    def _render_choose_method(self) -> None:
        """Render method selection with two boxes side by side"""
        self.step = "choose_method"
        self._set_title("EZS Configure - Choose Method")
        self._clear_scroll_area()

        search = self.query_one("#search", Input)
        search.value = ""
        search.placeholder = ""
        search.display = False

        scroll = self.query_one("#scroll-area", VerticalScroll)

        # Horizontal row with two boxes
        row = Horizontal(id="method-row")
        scroll.mount(row)

        # Auto-detect box (left)
        auto_box = Container(
            Static("Auto-Detect", classes="method-title"),
            Static("Scan all regions for\nECS clusters (1-2 min)", classes="method-desc"),
            id="method-auto",
            classes="method-box"
        )
        row.mount(auto_box)

        # Manual box (right)
        manual_box = Container(
            Static("Manual", classes="method-title"),
            Static("Choose regions\nfrom a list", classes="method-desc"),
            id="method-manual",
            classes="method-box"
        )
        row.mount(manual_box)

        self._method_index = 0
        self._update_method_highlight()

        self.query_one("#counter", Static).update(" 2 options")
        self._set_status("←→ / Tab Navigate | Enter Select | Esc Cancel")

    def _update_method_highlight(self) -> None:
        """Update visual highlight for method selection"""
        try:
            auto_box = self.query_one("#method-auto", Container)
            manual_box = self.query_one("#method-manual", Container)

            if self._method_index == 0:
                auto_box.add_class("selected")
                manual_box.remove_class("selected")
            else:
                auto_box.remove_class("selected")
                manual_box.add_class("selected")
        except Exception:
            pass

    # ==================== REGION SELECTION ====================

    def _render_region_selection(self, preselected: List[str] = None, filter_text: str = "") -> None:
        """Render region selection list"""
        self.step = "manual_select"
        self._set_title("EZS Setup - Select Regions")
        self._clear_scroll_area()

        search = self.query_one("#search", Input)
        search.display = True
        search.placeholder = "Type to filter regions..."
        if not filter_text:
            search.value = ""

        if preselected:
            self.selected_regions = set(preselected)

        scroll = self.query_one("#scroll-area", VerticalScroll)
        self._options_id = f"options-{self._render_id}"
        option_list = OptionList(id=self._options_id)
        scroll.mount(option_list)

        filter_lower = filter_text.lower() if filter_text else ""
        self._filtered_regions = []

        for region in self.all_regions:
            display_name = get_region_display_name(region)
            label = f"{display_name} ({region})"

            if filter_lower and filter_lower not in label.lower():
                continue

            # Show checkbox state - more visible icons
            checkbox = "[■]" if region in self.selected_regions else "[ ]"
            option_list.add_option(Option(f"{checkbox} {label}"))
            self._filtered_regions.append(region)

        if self._filtered_regions:
            option_list.highlighted = 0
            self._current_index = 0

        total = len(self.all_regions)
        selected = len(self.selected_regions)
        shown = len(self._filtered_regions)

        if filter_text:
            self.query_one("#counter", Static).update(f" {shown}/{total} regions | {selected} selected")
        else:
            self.query_one("#counter", Static).update(f" {total} regions | {selected} selected")

        self._set_status("Space Toggle | Enter Save | Esc Back | Type to filter")
        option_list.focus()

    def _update_region_display(self) -> None:
        """Update checkbox display for current selection"""
        try:
            option_list = self.query_one(f"#{self._options_id}", OptionList)
        except Exception:
            return

        # Remember current position
        current_highlighted = option_list.highlighted

        # Clear and repopulate
        option_list.clear_options()

        for region in self._filtered_regions:
            display_name = get_region_display_name(region)
            label = f"{display_name} ({region})"
            checkbox = "[■]" if region in self.selected_regions else "[ ]"
            option_list.add_option(Option(f"{checkbox} {label}"))

        # Restore position
        if current_highlighted is not None and current_highlighted < len(self._filtered_regions):
            option_list.highlighted = current_highlighted

        # Update counter
        total = len(self.all_regions)
        selected = len(self.selected_regions)
        shown = len(self._filtered_regions)
        search = self.query_one("#search", Input)

        if search.value:
            self.query_one("#counter", Static).update(f" {shown}/{total} regions | {selected} selected")
        else:
            self.query_one("#counter", Static).update(f" {total} regions | {selected} selected")

    def _toggle_current_region(self, index: int = None) -> None:
        """Toggle selection of single region at index (or highlighted)"""
        if self.step != "manual_select":
            return

        if not self._filtered_regions:
            return

        # Get index from parameter or from highlighted option
        if index is None:
            try:
                option_list = self.query_one(f"#{self._options_id}", OptionList)
                index = option_list.highlighted
            except Exception:
                return

        if index is None or index < 0 or index >= len(self._filtered_regions):
            return

        region = self._filtered_regions[index]
        if region in self.selected_regions:
            self.selected_regions.discard(region)
        else:
            self.selected_regions.add(region)

        self._update_region_display()

    # ==================== AUTO-DETECT ====================

    def _start_auto_detect(self) -> None:
        """Start auto-detection scan"""
        self.step = "auto_detect"
        self._show_loading("Scanning regions for ECS clusters...")
        self.run_worker(
            self._scan_regions,
            name="scan_regions",
            exclusive=True,
            thread=True
        )

    def _scan_regions(self) -> List[str]:
        """Worker: scan all regions for ECS clusters"""
        return detect_ecs_regions(
            profile=self.profile,
            progress_callback=self._update_loading_progress
        )

    def _fetch_regions(self) -> List[str]:
        """Worker: fetch all AWS regions"""
        return get_all_aws_regions(self.profile)

    # ==================== EVENT HANDLERS ====================

    def on_input_changed(self, event: Input.Changed) -> None:
        if self.step == "manual_select":
            self._render_region_selection(filter_text=event.value)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Handle click on option"""
        if self.step == "manual_select":
            # Toggle clicked region
            self._toggle_current_region(event.option_index)

    def on_worker_state_changed(self, event: Worker.StateChanged) -> None:
        if event.state != WorkerState.SUCCESS:
            return

        worker_name = event.worker.name
        result = event.worker.result
        self._hide_loading()

        if worker_name == "fetch_regions":
            self.all_regions = result
            self._render_region_selection()

        elif worker_name == "scan_regions":
            # Get all regions, then show with detected ones pre-selected
            self.all_regions = get_all_aws_regions(self.profile)
            self._render_region_selection(preselected=result)

            if result:
                self._set_status(f"Found ECS in {len(result)} regions | Space Toggle | Enter Save")
            else:
                self._set_status("No ECS clusters found | Select manually | Enter Save")

    def action_go_back(self) -> None:
        """Go back or cancel"""
        if self.step == "choose_method":
            self.cancelled = True
            self.exit()
        else:
            self._render_choose_method()

    def action_cancel(self) -> None:
        """Cancel setup"""
        self.cancelled = True
        self.exit()

    def action_confirm(self) -> None:
        """Save selection"""
        if self.step == "manual_select":
            if not self.selected_regions:
                self._set_status("[red]Please select at least one region[/red]")
                return

            selected_list = sorted(list(self.selected_regions))
            if save_regions(selected_list):
                self.result = selected_list
                self.exit()
            else:
                self._set_status("[red]Failed to save configuration[/red]")

        elif self.step == "choose_method":
            # Trigger selection based on highlighted method
            if self._method_index == 0:
                # Auto-detect (default)
                self._start_auto_detect()
            else:
                # Manual selection
                self._show_loading("Fetching available regions...")
                self.run_worker(self._fetch_regions, name="fetch_regions", exclusive=True, thread=True)

    def action_toggle_region(self) -> None:
        """Toggle current region selection"""
        self._toggle_current_region()

    def action_nav_up(self) -> None:
        """Navigate up"""
        if self.step == "choose_method":
            self._toggle_method()
        else:
            try:
                option_list = self.query_one(f"#{self._options_id}", OptionList)
                option_list.action_cursor_up()
            except Exception:
                pass

    def action_nav_down(self) -> None:
        """Navigate down"""
        if self.step == "choose_method":
            self._toggle_method()
        else:
            try:
                option_list = self.query_one(f"#{self._options_id}", OptionList)
                option_list.action_cursor_down()
            except Exception:
                pass

    def _toggle_method(self) -> None:
        """Toggle between auto-detect and manual"""
        self._method_index = 1 - self._method_index
        self._update_method_highlight()

    def action_noop(self) -> None:
        """Do nothing - absorb tab key"""
        pass

    def on_key(self, event) -> None:
        """Handle special keys"""
        if self.step == "choose_method":
            if event.key in ("tab", "shift+tab", "left", "right"):
                event.prevent_default()
                event.stop()
                self._toggle_method()
                return
            elif event.key == "enter":
                event.prevent_default()
                event.stop()
                self.action_confirm()
                return
        elif self.step == "manual_select":
            # Space can be reported as "space" or " "
            if event.key == "space" or event.character == " ":
                event.prevent_default()
                event.stop()
                self._toggle_current_region()
                return
            elif event.key == "enter":
                event.prevent_default()
                event.stop()
                self.action_confirm()
                return
            elif event.key == "backspace":
                # Handle backspace for search
                search = self.query_one("#search", Input)
                if search.value:
                    search.value = search.value[:-1]
                event.prevent_default()
                event.stop()
                return
            elif event.key in ("tab", "shift+tab"):
                event.prevent_default()
                event.stop()
                return
            elif event.character and event.character.isprintable() and event.character != " ":
                # Type to filter (but not space)
                search = self.query_one("#search", Input)
                search.value += event.character
                event.prevent_default()
                event.stop()
                return
        elif event.key in ("tab", "shift+tab"):
            event.prevent_default()
            event.stop()


def run_setup_wizard(profile: Optional[str] = None) -> Optional[List[str]]:
    """
    Run the setup wizard.
    Returns list of selected region codes, or None if cancelled.
    """
    app = SetupWizardApp(profile)
    app.run()

    if app.cancelled:
        return None

    return app.result
