"""Environment Variable Viewer"""

import time
from typing import Dict, Set, List
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static, LoadingIndicator, Input, Footer, Button
from textual.containers import Container, Horizontal
from textual.binding import Binding


class FilterInput(Input):
    """Input that blocks space and enter keys (handled by parent app)"""

    async def _on_key(self, event) -> None:
        """Block space and enter from being typed - post message to app instead"""
        if event.key == "space":
            # Block input, trigger app action
            self.app.action_reveal_selected()
            event.prevent_default()
            event.stop()
            return
        if event.key == "enter":
            # Block input, trigger app action
            self.app.action_copy_filtered()
            event.prevent_default()
            event.stop()
            return
        await super()._on_key(event)

# Markers for secret values
SECURE_MARKER = "[SECURE]"  # SecureString from SSM - hide value
SECRET_MARKER = "[SECRET]"  # Secrets Manager - hide value
MASKED_VALUE = "********"
REVEAL_TIMEOUT = 2.0  # seconds
DOUBLE_CLICK_TIME = 0.4  # seconds


def is_secret(value: str) -> bool:
    """Check if value is a secret (should be hidden)"""
    return value.startswith(SECURE_MARKER) or value.startswith(SECRET_MARKER)


def get_display_value(value: str) -> str:
    """Get display value - mask secrets, show others as-is"""
    if is_secret(value):
        return MASKED_VALUE
    return value


def get_real_value(value: str) -> str:
    """Get real value (strip secret marker if present)"""
    if value.startswith(SECURE_MARKER):
        return value[len(SECURE_MARKER):]
    if value.startswith(SECRET_MARKER):
        return value[len(SECRET_MARKER):]
    return value


class EnvViewerApp(App):
    """A simple viewer for environment variables with secret masking and search"""

    CSS = """
    * {
        scrollbar-size: 1 1;
        scrollbar-color: #3d3556;
        scrollbar-background: #08060d;
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

    #search {
        dock: top;
        margin: 1 1 0 1;
        background: #0f0c16;
        border: solid #3d3556;
    }

    #search:focus {
        border: solid #5c4a6e;
    }

    DataTable {
        background: #08060d;
        color: #a99fc4;
        height: 1fr;
        border: solid #3d3556;
        margin: 1;
    }

    DataTable > .datatable--header {
        background: #3d3556;
        color: #a99fc4;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #2a2536;
        color: #a99fc4;
    }

    #status {
        dock: bottom;
        height: 1;
        background: #3d3556;
        color: #a99fc4;
        padding: 0 1;
    }

    #hint {
        dock: bottom;
        height: 1;
        background: #1a1520;
        color: #6a6080;
        padding: 0 1;
    }

    .overlay {
        width: 100%;
        height: 100%;
        background: #08060d 95%;
        align: center middle;
        layer: overlay;
    }

    .overlay-box {
        width: auto;
        min-width: 40;
        max-width: 70;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
    }

    .overlay-title {
        text-align: center;
        text-style: bold;
        color: #a99fc4;
        padding: 0 0 1 0;
    }

    .overlay-content {
        color: #8a7fa0;
        max-height: 20;
        overflow-y: auto;
    }

    .overlay-hint {
        text-align: center;
        color: #6a6080;
        text-style: italic;
        padding: 1 0 0 0;
    }

    .confirm-buttons {
        width: 100%;
        height: 3;
        align: center middle;
        padding: 1 0 0 0;
    }

    .confirm-btn {
        width: 10;
        height: 3;
        margin: 0 1;
        background: #3d3556;
        color: #a99fc4;
        border: solid #5c4a6e;
    }

    .confirm-btn:focus {
        background: #5c4a6e;
        color: #ffffff;
        text-style: bold;
        border: solid #8a7fa0;
    }

    .loading-box {
        width: 46;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
    }

    .loading-box LoadingIndicator {
        width: 100%;
        height: 3;
        color: #a99fc4;
        background: transparent;
    }

    .loading-box Static {
        width: 100%;
        text-align: center;
        color: #a99fc4;
        background: transparent;
    }
    """

    BINDINGS = [
        Binding("enter", "copy_filtered", "Copy", show=True, priority=True),
        Binding("space", "reveal_selected", "Reveal", show=True, priority=True, key_display="␣"),
        Binding("escape", "close_or_quit", "Back", show=True, priority=True),
        Binding("q", "close_or_quit", "Back", show=False),
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
    ]

    def __init__(self, env_vars: dict, container_name: str):
        super().__init__()
        self.env_vars = env_vars
        self.container_name = container_name
        self._all_keys = sorted(env_vars.keys())
        self._filtered_keys: List[str] = list(self._all_keys)
        self._revealed_key: str = None
        self._hide_timer = None
        self._overlay_visible = False
        self._confirm_mode = False
        self._last_click_time = 0
        self._last_click_row = None

    def compose(self) -> ComposeResult:
        yield Static(f"Environment Variables: {self.container_name}", id="title")
        yield FilterInput(placeholder="Type to filter variables...", id="search")
        yield DataTable()
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Key", "Value")
        table.cursor_type = "row"
        table.can_focus = False  # Prevent focus on table
        self._refresh_table()
        self.query_one("#search", FilterInput).focus()

    def _refresh_table(self) -> None:
        """Refresh table with filtered keys"""
        table = self.query_one(DataTable)
        table.clear()

        for key in self._filtered_keys:
            value = self.env_vars[key]
            if key == self._revealed_key and is_secret(value):
                display_value = get_real_value(value)
            else:
                display_value = get_display_value(value)
            table.add_row(key, display_value)

    def _set_status(self, message: str) -> None:
        """Update status bar"""
        self.query_one("#status", Static).update(message)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter variables based on search input"""
        query = event.value.lower()
        if query:
            self._filtered_keys = [k for k in self._all_keys if query in k.lower()]
        else:
            self._filtered_keys = list(self._all_keys)
        self._refresh_table()
        self._set_status(f"{len(self._filtered_keys)} of {len(self._all_keys)} variables")

    def action_cursor_up(self) -> None:
        """Move cursor up in table"""
        table = self.query_one(DataTable)
        table.action_cursor_up()

    def action_cursor_down(self) -> None:
        """Move cursor down in table"""
        table = self.query_one(DataTable)
        table.action_cursor_down()

    def action_close_or_quit(self) -> None:
        """Close overlay or quit app"""
        if self._overlay_visible:
            self._close_overlay()
        else:
            self.exit()

    def action_copy_filtered(self) -> None:
        """Copy all filtered variables to clipboard"""
        if self._overlay_visible:
            self._close_overlay()
            return

        if not self._filtered_keys:
            return

        # Always show confirmation
        self._show_confirm_overlay()

    def _do_copy(self, keys: List[str]) -> None:
        """Actually copy the keys to clipboard"""
        # Build KEY=VALUE lines
        lines = []
        for key in keys:
            value = self.env_vars[key]
            real_value = get_real_value(value)
            lines.append(f"{key}={real_value}")

        clip_text = "\n".join(lines)
        self.copy_to_clipboard(clip_text)

        # Show overlay with copied keys
        self._show_copy_overlay(keys)

    def _show_confirm_overlay(self) -> None:
        """Show confirmation overlay for copying variables"""
        self._overlay_visible = True
        self._confirm_mode = True

        count = len(self._filtered_keys)
        overlay_box = Container(
            Static(f"Copy {count} variables to clipboard?", classes="overlay-title"),
            Horizontal(
                Button("Yes", id="btn-yes", classes="confirm-btn"),
                Button("No", id="btn-no", classes="confirm-btn"),
                classes="confirm-buttons"
            ),
            classes="overlay-box"
        )
        overlay = Container(overlay_box, classes="overlay", id="confirm-overlay")
        self.mount(overlay)
        # Focus on No button by default
        self.query_one("#btn-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press in confirmation dialog"""
        if event.button.id == "btn-yes":
            self._handle_confirm(True)
        elif event.button.id == "btn-no":
            self._handle_confirm(False)

    def _handle_confirm(self, confirmed: bool) -> None:
        """Handle confirmation response"""
        self._confirm_mode = False
        self._close_overlay()
        if confirmed:
            self._do_copy(self._filtered_keys)

    def _copy_single(self, key: str) -> None:
        """Copy a single variable to clipboard"""
        value = self.env_vars[key]
        real_value = get_real_value(value)
        clip_text = f"{key}={real_value}"
        self.copy_to_clipboard(clip_text)
        self._set_status(f"Copied: {key}")

    def _show_copy_overlay(self, keys: List[str]) -> None:
        """Show overlay with list of copied keys"""
        self._overlay_visible = True

        # Build key list
        if len(keys) <= 15:
            keys_text = "\n".join(keys)
        else:
            keys_text = "\n".join(keys[:15]) + f"\n... and {len(keys) - 15} more"

        overlay_box = Container(
            Static("Copied to clipboard", classes="overlay-title"),
            Static(keys_text, classes="overlay-content"),
            Static("Press Enter or Escape to continue", classes="overlay-hint"),
            classes="overlay-box"
        )
        overlay = Container(overlay_box, classes="overlay")
        self.mount(overlay)

    def _close_overlay(self) -> None:
        """Close the overlay"""
        self._overlay_visible = False
        for overlay in self.query(".overlay"):
            overlay.remove()

    def action_reveal_selected(self) -> None:
        """Reveal the selected secret temporarily"""
        if self._overlay_visible:
            return

        table = self.query_one(DataTable)
        row_idx = table.cursor_row

        if row_idx is None or row_idx >= len(self._filtered_keys):
            return

        key = self._filtered_keys[row_idx]
        value = self.env_vars[key]

        if not is_secret(value):
            return

        self._reveal_key(key)

    def _reveal_key(self, key: str) -> None:
        """Reveal a specific key temporarily"""
        if self._hide_timer:
            self._hide_timer.stop()
            self._hide_timer = None

        if self._revealed_key:
            self._revealed_key = None

        self._revealed_key = key
        self._refresh_table()

        self._hide_timer = self.set_timer(REVEAL_TIMEOUT, self._hide_secret)

    def _hide_secret(self) -> None:
        """Hide the revealed secret"""
        self._revealed_key = None
        self._hide_timer = None
        self._refresh_table()

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        """Handle click on cell - single click reveals, double click copies"""
        row_idx = event.cursor_row
        if row_idx is None or row_idx >= len(self._filtered_keys):
            return

        current_time = time.time()
        key = self._filtered_keys[row_idx]

        if (self._last_click_row == row_idx and
            current_time - self._last_click_time < DOUBLE_CLICK_TIME):
            self._copy_single(key)
            self._last_click_time = 0
            self._last_click_row = None
        else:
            value = self.env_vars[key]
            if is_secret(value):
                self._reveal_key(key)
            self._last_click_time = current_time
            self._last_click_row = row_idx

    def on_key(self, event) -> None:
        """Handle key events globally"""
        # Handle confirmation dialog
        if self._confirm_mode:
            if event.key in ("y", "Y"):
                self._handle_confirm(True)
                event.prevent_default()
                event.stop()
                return
            elif event.key in ("n", "N", "escape"):
                self._handle_confirm(False)
                event.prevent_default()
                event.stop()
                return
            elif event.key in ("tab", "shift+tab", "left", "right"):
                # Allow Tab to switch between buttons
                try:
                    btn_yes = self.query_one("#btn-yes", Button)
                    btn_no = self.query_one("#btn-no", Button)
                    if btn_yes.has_focus:
                        btn_no.focus()
                    else:
                        btn_yes.focus()
                except Exception:
                    pass
                event.prevent_default()
                event.stop()
                return
            # Block other keys during confirmation
            event.prevent_default()
            event.stop()
            return

        # Tab navigates table rows (doesn't switch focus)
        if event.key == "tab":
            self.action_cursor_down()
            event.prevent_default()
            event.stop()
            return

        if event.key == "shift+tab":
            self.action_cursor_up()
            event.prevent_default()
            event.stop()
            return


class MultiEnvViewerApp(App):
    """Viewer for environment variables from multiple containers"""

    CSS = """
    * {
        scrollbar-size: 1 1;
        scrollbar-color: #3d3556;
        scrollbar-background: #08060d;
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

    #container-tabs {
        dock: top;
        height: 1;
        background: #1a1520;
        padding: 0 1;
    }

    .tab-btn {
        padding: 0 2;
        color: #6a6080;
        background: #1a1520;
    }

    .tab-btn.active {
        color: #a99fc4;
        background: #3d3556;
        text-style: bold;
    }

    DataTable {
        background: #08060d;
        color: #a99fc4;
        height: 1fr;
        border: solid #3d3556;
        margin: 1;
    }

    DataTable > .datatable--header {
        background: #3d3556;
        color: #a99fc4;
        text-style: bold;
    }

    DataTable > .datatable--cursor {
        background: #2a2536;
        color: #a99fc4;
    }

    .overlay {
        width: 100%;
        height: 100%;
        background: #08060d 95%;
        align: center middle;
        layer: overlay;
    }

    .overlay-box {
        width: auto;
        min-width: 40;
        max-width: 70;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
    }

    .overlay-title {
        text-align: center;
        text-style: bold;
        color: #a99fc4;
        padding: 0 0 1 0;
    }

    .overlay-content {
        color: #8a7fa0;
        max-height: 20;
        overflow-y: auto;
    }

    .overlay-hint {
        text-align: center;
        color: #6a6080;
        text-style: italic;
        padding: 1 0 0 0;
    }

    .confirm-buttons {
        width: 100%;
        height: 3;
        align: center middle;
        padding: 1 0 0 0;
    }

    .confirm-btn {
        width: 10;
        height: 3;
        margin: 0 1;
        background: #3d3556;
        color: #a99fc4;
        border: solid #5c4a6e;
    }

    .confirm-btn:focus {
        background: #5c4a6e;
        color: #ffffff;
        text-style: bold;
        border: solid #8a7fa0;
    }

    .loading-box {
        width: 46;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
    }

    .loading-box LoadingIndicator {
        width: 100%;
        height: 3;
        color: #a99fc4;
        background: transparent;
    }

    .loading-box Static {
        width: 100%;
        text-align: center;
        color: #a99fc4;
        background: transparent;
    }
    """

    BINDINGS = [
        Binding("enter", "copy_filtered", "Copy", show=True, priority=True),
        Binding("space", "reveal_selected", "Reveal", show=True, priority=True, key_display="␣"),
        Binding("escape", "close_or_quit", "Back", show=True, priority=True),
        Binding("q", "close_or_quit", "Back", show=False),
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
        Binding("1", "select_tab_1", show=False),
        Binding("2", "select_tab_2", show=False),
        Binding("3", "select_tab_3", show=False),
        Binding("4", "select_tab_4", show=False),
        Binding("5", "select_tab_5", show=False),
    ]

    def __init__(self, all_env_vars: Dict[str, Dict[str, str]], title: str):
        super().__init__()
        self.all_env_vars = all_env_vars
        self.title_text = title
        self._containers = list(all_env_vars.keys())
        self._all_keys: Dict[str, List[str]] = {}
        self._filtered_keys: Dict[str, List[str]] = {}
        for container, env_vars in all_env_vars.items():
            sorted_keys = sorted(env_vars.keys())
            self._all_keys[container] = sorted_keys
            self._filtered_keys[container] = list(sorted_keys)
        self._revealed_key: Dict[str, str] = {}
        self._hide_timer = None
        self._current_idx = 0
        self._overlay_visible = False
        self._confirm_mode = False
        self._search_query = ""
        self._last_click_time = 0
        self._last_click_row = None

    @property
    def _current_container(self) -> str:
        if self._containers:
            return self._containers[self._current_idx]
        return ""

    def compose(self) -> ComposeResult:
        yield Static(f"Environment Variables: {self.title_text}", id="title")
        yield FilterInput(placeholder="Type to filter variables...", id="search")

        # Container tabs if multiple
        if len(self._containers) > 1:
            from textual.containers import Horizontal
            tabs = []
            for i, name in enumerate(self._containers):
                cls = "tab-btn active" if i == 0 else "tab-btn"
                tabs.append(Static(f"[{i+1}] {name}", classes=cls, id=f"tab-{i}"))
            yield Horizontal(*tabs, id="container-tabs")

        yield DataTable()
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Key", "Value")
        table.cursor_type = "row"
        table.can_focus = False
        self._refresh_table()
        self.query_one("#search", FilterInput).focus()

    def _refresh_table(self) -> None:
        """Refresh table for current container"""
        container = self._current_container
        if not container:
            return

        table = self.query_one(DataTable)
        table.clear()

        env_vars = self.all_env_vars[container]
        revealed_key = self._revealed_key.get(container)

        for key in self._filtered_keys[container]:
            value = env_vars[key]
            if key == revealed_key and is_secret(value):
                display_value = get_real_value(value)
            else:
                display_value = get_display_value(value)
            table.add_row(key, display_value)

    def _update_tabs(self) -> None:
        """Update tab styling"""
        for i in range(len(self._containers)):
            try:
                tab = self.query_one(f"#tab-{i}", Static)
                if i == self._current_idx:
                    tab.add_class("active")
                else:
                    tab.remove_class("active")
            except Exception:
                pass

    def _select_tab(self, idx: int) -> None:
        """Select a container tab by index"""
        if 0 <= idx < len(self._containers):
            self._current_idx = idx
            self._update_tabs()
            self._refresh_table()

    def action_select_tab_1(self) -> None: self._select_tab(0)
    def action_select_tab_2(self) -> None: self._select_tab(1)
    def action_select_tab_3(self) -> None: self._select_tab(2)
    def action_select_tab_4(self) -> None: self._select_tab(3)
    def action_select_tab_5(self) -> None: self._select_tab(4)

    def _set_status(self, message: str) -> None:
        """Update status bar"""
        self.query_one("#status", Static).update(message)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter variables based on search input"""
        self._search_query = event.value.lower()

        total_filtered = 0
        total_all = 0
        for container in self._containers:
            all_keys = self._all_keys[container]
            if self._search_query:
                self._filtered_keys[container] = [k for k in all_keys if self._search_query in k.lower()]
            else:
                self._filtered_keys[container] = list(all_keys)
            total_filtered += len(self._filtered_keys[container])
            total_all += len(all_keys)

        self._refresh_table()
        self._set_status(f"{total_filtered} of {total_all} variables")

    def action_cursor_up(self) -> None:
        table = self.query_one(DataTable)
        table.action_cursor_up()

    def action_cursor_down(self) -> None:
        table = self.query_one(DataTable)
        table.action_cursor_down()

    def action_close_or_quit(self) -> None:
        if self._overlay_visible:
            self._close_overlay()
        else:
            self.exit()

    def action_copy_filtered(self) -> None:
        """Copy all filtered variables from current container"""
        if self._overlay_visible:
            self._close_overlay()
            return

        container = self._current_container
        if not container:
            return

        filtered = self._filtered_keys.get(container, [])
        if not filtered:
            return

        # Always show confirmation
        self._show_confirm_overlay(filtered)

    def _do_copy(self, keys: List[str]) -> None:
        """Actually copy the keys to clipboard"""
        container = self._current_container
        lines = []
        env_vars = self.all_env_vars[container]
        for key in keys:
            value = env_vars[key]
            real_value = get_real_value(value)
            lines.append(f"{key}={real_value}")

        clip_text = "\n".join(lines)
        self.copy_to_clipboard(clip_text)
        self._show_copy_overlay(keys)

    def _show_confirm_overlay(self, keys: List[str]) -> None:
        """Show confirmation overlay for copying variables"""
        self._overlay_visible = True
        self._confirm_mode = True
        self._pending_copy_keys = keys

        overlay_box = Container(
            Static(f"Copy {len(keys)} variables to clipboard?", classes="overlay-title"),
            Horizontal(
                Button("Yes", id="btn-yes", classes="confirm-btn"),
                Button("No", id="btn-no", classes="confirm-btn"),
                classes="confirm-buttons"
            ),
            classes="overlay-box"
        )
        overlay = Container(overlay_box, classes="overlay", id="confirm-overlay")
        self.mount(overlay)
        # Focus on No button by default
        self.query_one("#btn-no", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button press in confirmation dialog"""
        if event.button.id == "btn-yes":
            self._handle_confirm(True)
        elif event.button.id == "btn-no":
            self._handle_confirm(False)

    def _handle_confirm(self, confirmed: bool) -> None:
        """Handle confirmation response"""
        keys = self._pending_copy_keys
        self._confirm_mode = False
        self._pending_copy_keys = None
        self._close_overlay()
        if confirmed:
            self._do_copy(keys)

    def _copy_single(self, key: str) -> None:
        container = self._current_container
        if not container:
            return
        value = self.all_env_vars[container][key]
        real_value = get_real_value(value)
        clip_text = f"{key}={real_value}"
        self.copy_to_clipboard(clip_text)
        self._set_status(f"Copied: {key}")

    def _show_copy_overlay(self, keys: List[str]) -> None:
        self._overlay_visible = True

        if len(keys) <= 15:
            keys_text = "\n".join(keys)
        else:
            keys_text = "\n".join(keys[:15]) + f"\n... and {len(keys) - 15} more"

        overlay_box = Container(
            Static("Copied to clipboard", classes="overlay-title"),
            Static(keys_text, classes="overlay-content"),
            Static("Press Enter or Escape to continue", classes="overlay-hint"),
            classes="overlay-box"
        )
        overlay = Container(overlay_box, classes="overlay")
        self.mount(overlay)

    def _close_overlay(self) -> None:
        self._overlay_visible = False
        for overlay in self.query(".overlay"):
            overlay.remove()

    def action_reveal_selected(self) -> None:
        if self._overlay_visible:
            return

        container = self._current_container
        if not container:
            return

        table = self.query_one(DataTable)
        row_idx = table.cursor_row
        filtered = self._filtered_keys.get(container, [])

        if row_idx is None or row_idx >= len(filtered):
            return

        key = filtered[row_idx]
        value = self.all_env_vars[container][key]

        if not is_secret(value):
            return

        self._reveal_key(container, key)

    def _reveal_key(self, container: str, key: str) -> None:
        if self._hide_timer:
            self._hide_timer.stop()
            self._hide_timer = None

        if container in self._revealed_key:
            del self._revealed_key[container]

        self._revealed_key[container] = key
        self._refresh_table()

        self._hide_timer = self.set_timer(REVEAL_TIMEOUT, lambda: self._hide_secret(container))

    def _hide_secret(self, container: str) -> None:
        if container in self._revealed_key:
            del self._revealed_key[container]
        self._hide_timer = None
        self._refresh_table()

    def on_data_table_cell_selected(self, event: DataTable.CellSelected) -> None:
        container = self._current_container
        if not container:
            return

        row_idx = event.cursor_row
        filtered = self._filtered_keys.get(container, [])

        if row_idx is None or row_idx >= len(filtered):
            return

        current_time = time.time()
        key = filtered[row_idx]

        if (self._last_click_row == row_idx and
            current_time - self._last_click_time < DOUBLE_CLICK_TIME):
            self._copy_single(key)
            self._last_click_time = 0
            self._last_click_row = None
        else:
            value = self.all_env_vars[container][key]
            if is_secret(value):
                self._reveal_key(container, key)
            self._last_click_time = current_time
            self._last_click_row = row_idx

    def on_key(self, event) -> None:
        """Handle key events globally"""
        # Handle confirmation dialog
        if self._confirm_mode:
            if event.key in ("y", "Y"):
                self._handle_confirm(True)
                event.prevent_default()
                event.stop()
                return
            elif event.key in ("n", "N", "escape"):
                self._handle_confirm(False)
                event.prevent_default()
                event.stop()
                return
            elif event.key in ("tab", "shift+tab", "left", "right"):
                # Allow Tab to switch between buttons
                try:
                    btn_yes = self.query_one("#btn-yes", Button)
                    btn_no = self.query_one("#btn-no", Button)
                    if btn_yes.has_focus:
                        btn_no.focus()
                    else:
                        btn_yes.focus()
                except Exception:
                    pass
                event.prevent_default()
                event.stop()
                return
            # Block other keys during confirmation
            event.prevent_default()
            event.stop()
            return

        # Tab navigates table rows (doesn't switch focus)
        if event.key == "tab":
            self.action_cursor_down()
            event.prevent_default()
            event.stop()
            return

        if event.key == "shift+tab":
            self.action_cursor_up()
            event.prevent_default()
            event.stop()
            return


def run_env_viewer(env_vars: dict, container_name: str):
    app = EnvViewerApp(env_vars, container_name)
    app.run()


def run_multi_env_viewer(all_env_vars: Dict[str, Dict[str, str]], title: str):
    app = MultiEnvViewerApp(all_env_vars, title)
    app.run()


class EnvViewerWithLoadingApp(App):
    """Env viewer that fetches data with loading overlay"""

    CSS = """
    * {
        scrollbar-size: 1 1;
        scrollbar-color: #3d3556;
        scrollbar-background: #08060d;
    }

    Screen {
        background: #08060d;
        align: center middle;
    }

    #title {
        dock: top;
        height: 1;
        background: #3d3556;
        color: #a99fc4;
        text-style: bold;
        padding: 0 1;
    }

    .loading-box {
        width: 50;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
    }

    .loading-box LoadingIndicator {
        width: 100%;
        height: 3;
        color: #a99fc4;
        background: transparent;
    }

    .loading-box Static {
        width: 100%;
        text-align: center;
        color: #a99fc4;
        background: transparent;
    }

    .error-box {
        width: 50;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
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
        color: #a99fc4;
    }

    .error-hint {
        text-align: center;
        color: #6a6080;
        text-style: italic;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "quit", "Back", show=True),
        Binding("enter", "quit", show=False),
    ]

    def __init__(self, task_data: dict, container_name: str, region: str, profile: str = None):
        super().__init__()
        self._task_data = task_data
        self.container_name = container_name
        self.region = region
        self.profile = profile
        self._env_vars = None
        self._error = None

    def compose(self) -> ComposeResult:
        yield Static(f"Environment Variables: {self.container_name}", id="title")
        yield Container(
            LoadingIndicator(),
            Static(f"Fetching environment variables..."),
            classes="loading-box"
        )

    def on_mount(self) -> None:
        self.run_worker(self._fetch_env_vars, name="fetch_env", thread=True)

    def _fetch_env_vars(self) -> dict:
        from .aws_client import AWSClient
        aws = AWSClient(region=self.region, profile=self.profile)
        return aws.get_container_env_vars(self._task_data, self.container_name)

    def on_worker_state_changed(self, event) -> None:
        from textual.worker import WorkerState
        if event.state != WorkerState.SUCCESS:
            return
        if event.worker.name != "fetch_env":
            return

        self._env_vars = event.worker.result

        if not self._env_vars:
            self._show_error("No environment variables found")
        else:
            # Launch the actual viewer
            self.exit(result="show_viewer")

    def _show_error(self, message: str) -> None:
        # Remove loading
        for box in self.query(".loading-box"):
            box.remove()

        error_box = Container(
            Static("Error", classes="error-title"),
            Static(message, classes="error-content"),
            Static("Press Escape to go back", classes="error-hint"),
            classes="error-box"
        )
        self.mount(error_box)


class TaskEnvViewerWithLoadingApp(App):
    """Env viewer for task that fetches data with loading overlay"""

    CSS = """
    * {
        scrollbar-size: 1 1;
        scrollbar-color: #3d3556;
        scrollbar-background: #08060d;
    }

    Screen {
        background: #08060d;
        align: center middle;
    }

    #title {
        dock: top;
        height: 1;
        background: #3d3556;
        color: #a99fc4;
        text-style: bold;
        padding: 0 1;
    }

    .loading-box {
        width: 50;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
    }

    .loading-box LoadingIndicator {
        width: 100%;
        height: 3;
        color: #a99fc4;
        background: transparent;
    }

    .loading-box Static {
        width: 100%;
        text-align: center;
        color: #a99fc4;
        background: transparent;
    }

    .error-box {
        width: 50;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
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
        color: #a99fc4;
    }

    .error-hint {
        text-align: center;
        color: #6a6080;
        text-style: italic;
        padding: 1 0 0 0;
    }
    """

    BINDINGS = [
        Binding("escape", "quit", "Back", show=True),
        Binding("enter", "quit", show=False),
    ]

    def __init__(self, task_data: dict, region: str, profile: str = None):
        super().__init__()
        self._task_data = task_data
        self.region = region
        self.profile = profile
        self._task_id = task_data.get('taskArn', '').split('/')[-1]
        self._all_env_vars = None

    def compose(self) -> ComposeResult:
        yield Static(f"Environment Variables: Task {self._task_id}", id="title")
        yield Container(
            LoadingIndicator(),
            Static(f"Fetching environment variables..."),
            classes="loading-box"
        )

    def on_mount(self) -> None:
        self.run_worker(self._fetch_env_vars, name="fetch_env", thread=True)

    def _fetch_env_vars(self) -> dict:
        from .aws_client import AWSClient
        aws = AWSClient(region=self.region, profile=self.profile)
        return aws.get_all_container_env_vars(self._task_data)

    def on_worker_state_changed(self, event) -> None:
        from textual.worker import WorkerState
        if event.state != WorkerState.SUCCESS:
            return
        if event.worker.name != "fetch_env":
            return

        self._all_env_vars = event.worker.result

        if not self._all_env_vars:
            self._show_error("No environment variables found")
        else:
            self.exit(result="show_viewer")

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


def run_env_viewer_with_loading(task: dict, container_name: str, region: str, profile: str = None):
    """Run env viewer with loading overlay"""
    loader = EnvViewerWithLoadingApp(task, container_name, region, profile)
    result = loader.run()

    if result == "show_viewer" and loader._env_vars:
        viewer = EnvViewerApp(loader._env_vars, container_name)
        viewer.run()


def run_task_env_viewer_with_loading(task: dict, region: str, profile: str = None):
    """Run task env viewer with loading overlay"""
    loader = TaskEnvViewerWithLoadingApp(task, region, profile)
    result = loader.run()

    if result == "show_viewer" and loader._all_env_vars:
        if len(loader._all_env_vars) == 1:
            container_name = list(loader._all_env_vars.keys())[0]
            viewer = EnvViewerApp(loader._all_env_vars[container_name], container_name)
        else:
            viewer = MultiEnvViewerApp(loader._all_env_vars, f"Task: {loader._task_id}")
        viewer.run()
