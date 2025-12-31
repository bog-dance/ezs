"""Environment Variable Viewer and Editor"""

from typing import Dict, List, Optional
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static, Footer, Input, Button, Label, ListItem, ListView, LoadingIndicator
from textual.binding import Binding
from textual.screen import Screen, ModalScreen
from textual.containers import Container, Horizontal, Vertical, Grid
from textual.worker import Worker, WorkerState
from rich.text import Text


# ==================== MODALS ====================

class EditModal(ModalScreen):
    """Modal to edit a key-value pair"""

    CSS = """
    EditModal {
        align: center middle;
        background: #000000 50%;
    }

    #edit-dialog {
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
        width: 60;
        height: auto;
    }

    #edit-title {
        text-align: center;
        text-style: bold;
        color: #a99fc4;
        margin-bottom: 1;
    }

    #key-label {
        color: #8a7fa0;
        margin-top: 1;
    }

    #edit-input {
        margin: 1 0;
        background: #0f0c16;
        border: solid #3d3556;
        color: #e0dce8;
    }

    #edit-input:focus {
        border: solid #a99fc4;
    }

    #btn-row {
        width: 100%;
        align: center middle;
        margin-top: 1;
        height: 3;
    }

    .modal-btn {
        margin: 0 1;
        min-width: 12;
        background: #3d3556;
        color: #a99fc4;
    }

    .modal-btn:focus {
        background: #5c4a6e;
        color: #ffffff;
    }
    """

    def __init__(self, key: str, value: str):
        super().__init__()
        self.key = key
        self.original_value = value
        self._focus_index = 0  # 0=input, 1=cancel, 2=save

    def compose(self) -> ComposeResult:
        yield Container(
            Static(f"Edit {self.key}", id="edit-title"),
            Static("Value:", id="key-label"),
            Input(value=self.original_value, id="edit-input"),
            Horizontal(
                Button("Cancel", id="cancel", classes="modal-btn"),
                Button("Save", id="save", classes="modal-btn"),
                id="btn-row"
            ),
            id="edit-dialog"
        )

    def on_mount(self) -> None:
        # Focus Input field so user can type immediately
        self.query_one("#edit-input", Input).focus()
        self._focus_index = 0

    def on_key(self, event) -> None:
        """Handle Tab to cycle focus and Escape to cancel"""
        if event.key == "escape":
            self.dismiss(None)
            event.prevent_default()
            event.stop()
        elif event.key == "tab":
            self._focus_index = (self._focus_index + 1) % 3
            self._apply_focus()
            event.prevent_default()
            event.stop()
        elif event.key == "shift+tab":
            self._focus_index = (self._focus_index - 1) % 3
            self._apply_focus()
            event.prevent_default()
            event.stop()

    def _apply_focus(self) -> None:
        """Apply focus to current element"""
        if self._focus_index == 0:
            self.query_one("#edit-input", Input).focus()
        elif self._focus_index == 1:
            self.query_one("#cancel", Button).focus()
        else:
            self.query_one("#save", Button).focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            input_widget = self.query_one("#edit-input", Input)
            self.dismiss(input_widget.value)
        else:
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter in input field - save"""
        self.dismiss(event.value)


class ConfirmationModal(ModalScreen):
    """Modal for Yes/No confirmation"""

    CSS = """
    ConfirmationModal {
        align: center middle;
        background: #000000 50%;
    }

    #confirm-dialog {
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
        width: 50;
        height: auto;
    }

    #confirm-message {
        text-align: center;
        color: #e0dce8;
        margin: 1 0 2 0;
    }

    #confirm-btns {
        width: 100%;
        align: center middle;
        height: 3;
    }

    .modal-btn {
        margin: 0 1;
        min-width: 12;
        background: #3d3556;
        color: #a99fc4;
    }

    .modal-btn:focus {
        background: #5c4a6e;
        color: #ffffff;
    }
    """

    BINDINGS = [
        Binding("escape", "say_no", "No", show=False, priority=True),
        Binding("y", "say_yes", "Yes", show=False, priority=True),
        Binding("n", "say_no", "No", show=False, priority=True),
        Binding("tab", "focus_next", "Next", show=False),
        Binding("shift+tab", "focus_previous", "Previous", show=False),
    ]

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Container(
            Static(self.message, id="confirm-message"),
            Horizontal(
                Button("No", id="no", classes="modal-btn"),
                Button("Yes", id="yes", classes="modal-btn"),
                id="confirm-btns"
            ),
            id="confirm-dialog"
        )

    def on_mount(self) -> None:
        self.query_one("#no", Button).focus()

    def on_key(self, event) -> None:
        """Handle keys and stop propagation"""
        if event.key == "escape":
            self.dismiss(False)
            event.prevent_default()
            event.stop()
        elif event.key == "y":
            self.dismiss(True)
            event.prevent_default()
            event.stop()
        elif event.key == "n":
            self.dismiss(False)
            event.prevent_default()
            event.stop()
        elif event.key in ("tab", "right", "l"):
            self._switch_focus()
            event.prevent_default()
            event.stop()
        elif event.key in ("shift+tab", "left", "h"):
            self._switch_focus()
            event.prevent_default()
            event.stop()
        elif event.key == "enter":
            # Confirm current focused button
            focused = self.focused
            if focused and isinstance(focused, Button):
                focused.press()
            event.prevent_default()
            event.stop()

    def _switch_focus(self) -> None:
        """Switch focus between No and Yes buttons"""
        no_btn = self.query_one("#no", Button)
        yes_btn = self.query_one("#yes", Button)
        if self.focused == no_btn:
            yes_btn.focus()
        else:
            no_btn.focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        else:
            self.dismiss(False)

    def action_say_yes(self) -> None:
        self.dismiss(True)

    def action_say_no(self) -> None:
        self.dismiss(False)


class CommandPalette(ModalScreen):
    """Command palette for actions"""

    CSS = """
    CommandPalette {
        align: center top;
        background: #000000 50%;
        padding-top: 3;
    }

    #palette-container {
        width: 50;
        height: auto;
        background: #1a1520;
        border: solid #5c4a6e;
    }

    ListView {
        height: auto;
        max-height: 20;
    }

    ListItem {
        padding: 1 2;
        color: #a99fc4;
    }

    ListItem:hover {
        background: #2a2536;
    }

    #title {
        padding: 1 2;
        background: #3d3556;
        color: #e0dce8;
        text-style: bold;
    }
    """

    def compose(self) -> ComposeResult:
        yield Container(
            Static("Commands", id="title"),
            ListView(
                ListItem(Static("Edit Variable (Ctrl+E)"), id="edit"),
                ListItem(Static("Copy Filtered Variables (Ctrl+S)"), id="copy"),
                ListItem(Static("Reveal/Hide Secret (Ctrl+R)"), id="reveal"),
                ListItem(Static("Update Service (Ctrl+U)"), id="update"),
                ListItem(Static("Close (Esc)"), id="close"),
            ),
            id="palette-container"
        )

    BINDINGS = [
        Binding("escape", "close", "Close", show=False, priority=True),
    ]

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.id)

    def action_close(self) -> None:
        self.dismiss(None)


class SuccessModal(ModalScreen):
    """Modal to display success messages"""

    CSS = """
    SuccessModal {
        align: center middle;
        background: #000000 50%;
    }

    #success-dialog {
        background: #1a1520;
        border: solid #5c4a6e;
        padding: 1 2;
        width: 70;
        max-width: 90%;
        height: auto;
    }

    #success-title {
        text-align: center;
        text-style: bold;
        color: #a99fc4;
        margin-bottom: 1;
    }

    #success-message {
        color: #a99fc4;
        margin: 1 0;
        max-height: 15;
        overflow-y: auto;
    }

    #success-btn-row {
        width: 100%;
        align: center middle;
        margin-top: 1;
        height: 3;
    }

    .modal-btn {
        margin: 0 1;
        min-width: 12;
        background: #3d3556;
        color: #a99fc4;
    }

    .modal-btn:focus {
        background: #5c4a6e;
        color: #ffffff;
    }
    """

    BINDINGS = [
        Binding("enter", "close", "Close", show=False, priority=True),
    ]

    def __init__(self, title: str, message: str):
        super().__init__()
        self.success_title = title
        self.success_message = message

    def compose(self) -> ComposeResult:
        yield Container(
            Static(self.success_title, id="success-title"),
            Static(self.success_message, id="success-message"),
            Horizontal(
                Button("OK", id="ok", classes="modal-btn"),
                id="success-btn-row"
            ),
            id="success-dialog"
        )

    def on_mount(self) -> None:
        self.query_one("#ok", Button).focus()

    def on_key(self, event) -> None:
        """Handle Escape to close modal"""
        if event.key == "escape":
            self.dismiss()
            event.prevent_default()
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()


class ErrorModal(ModalScreen):
    """Modal to display error messages"""

    CSS = """
    ErrorModal {
        align: center middle;
        background: #000000 50%;
    }

    #error-dialog {
        background: #1a1520;
        border: solid #e06c75;
        padding: 1 2;
        width: 70;
        max-width: 90%;
        height: auto;
    }

    #error-title {
        text-align: center;
        text-style: bold;
        color: #e06c75;
        margin-bottom: 1;
    }

    #error-message {
        color: #a99fc4;
        margin: 1 0;
        max-height: 15;
        overflow-y: auto;
    }

    #error-btn-row {
        width: 100%;
        align: center middle;
        margin-top: 1;
        height: 3;
    }

    .modal-btn {
        margin: 0 1;
        min-width: 12;
        background: #3d3556;
        color: #a99fc4;
    }

    .modal-btn:focus {
        background: #5c4a6e;
        color: #ffffff;
    }
    """

    BINDINGS = [
        Binding("enter", "close", "Close", show=False, priority=True),
    ]

    def __init__(self, title: str, message: str):
        super().__init__()
        self.error_title = title
        self.error_message = message

    def compose(self) -> ComposeResult:
        yield Container(
            Static(self.error_title, id="error-title"),
            Static(self.error_message, id="error-message"),
            Horizontal(
                Button("OK", id="ok", classes="modal-btn"),
                id="error-btn-row"
            ),
            id="error-dialog"
        )

    def on_mount(self) -> None:
        self.query_one("#ok", Button).focus()

    def on_key(self, event) -> None:
        """Handle Escape to close modal"""
        if event.key == "escape":
            self.dismiss()
            event.prevent_default()
            event.stop()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss()

    def action_close(self) -> None:
        self.dismiss()


# ==================== MAIN APP ====================

class EnvEditorApp(App):
    """Viewer and Editor for ECS Environment Variables"""

    CSS = """
    * {
        scrollbar-size: 1 1;
        scrollbar-color: #3d3556;
        scrollbar-background: #08060d;
    }

    Screen {
        background: #08060d;
    }

    #header {
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
        color: #e0dce8;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: #3d3556;
        color: #a99fc4;
        padding: 0 1;
    }

    Footer {
        dock: bottom;
    }

    .dirty {
        color: #ffaa00;
    }
    """

    BINDINGS = [
        Binding("escape", "quit_check", "Back", show=True, priority=True),
        Binding("ctrl+p", "command_palette", "Commands", show=True, priority=True),
        Binding("ctrl+e", "edit_variable", "Edit", show=True, priority=True),
        Binding("ctrl+s", "copy_filtered", "Copy", show=True, priority=True),
        Binding("ctrl+r", "toggle_reveal", "Reveal", show=True, priority=True),
        Binding("ctrl+u", "update_service", "Deploy", show=True, priority=True),
        Binding("up", "cursor_up", show=False),
        Binding("down", "cursor_down", show=False),
    ]

    def __init__(self, aws_client, cluster: str, service: str, task_def_arn: str,
                 container_name: str, env_vars: dict, secrets_map: dict = None, task: dict = None):
        super().__init__()
        self.aws = aws_client
        self.cluster = cluster
        self.service = service
        self.original_task_def_arn = task_def_arn
        self.container_name = container_name
        self._task = task

        # Secrets mapping: env_var_name -> {type, path/arn, json_key, full_ref}
        self.secrets_map = secrets_map or {}

        # Track if service was redeployed (for cache invalidation)
        self.was_redeployed = False

        # State
        self.original_env_vars = env_vars.copy()
        self.current_env_vars = env_vars.copy()
        self._all_keys = sorted(env_vars.keys())
        self._filtered_keys: List[str] = list(self._all_keys)
        self.dirty = False
        self.new_task_def_arn = None
        self._pending_update = None  # Track which var is being updated

    def compose(self) -> ComposeResult:
        title = f"Env Vars: {self.container_name}"
        if self.service:
            title += f" ({self.service})"
        yield Static(title, id="header")
        yield Input(placeholder="Type to filter variables...", id="search")
        yield DataTable()
        yield Static("Ready", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Key", "Value")
        table.cursor_type = "row"
        table.can_focus = False
        self._refresh_table()
        self.query_one("#search", Input).focus()

    def _refresh_table(self) -> None:
        """Refresh table content"""
        table = self.query_one(DataTable)
        table.clear()

        for key in self._filtered_keys:
            val = self.current_env_vars.get(key, "")

            # Mask secret values with asterisks
            display_val = val
            if key in self.secrets_map:
                # Check if revealed (no prefix means revealed)
                if val.startswith('[SECURE]') or val.startswith('[SECRET]'):
                    # Masked - show asterisks
                    display_val = "********"
                # else: revealed - show actual value

            # Check if modified
            orig = self.original_env_vars.get(key)
            if orig != val:
                key_display = Text(key, style="bold #ffaa00")
                val_display = Text(str(display_val), style="#ffaa00")
            else:
                key_display = key
                val_display = str(display_val)

            table.add_row(key_display, val_display, key=key)

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter variables based on search input"""
        query = event.value.lower()
        if query:
            self._filtered_keys = [k for k in self._all_keys if query in k.lower()]
        else:
            self._filtered_keys = list(self._all_keys)
        self._refresh_table()
        self._update_status()

    def _update_status(self) -> None:
        """Update status bar with count"""
        status = self.query_one("#status-bar", Static)
        if len(self._filtered_keys) != len(self._all_keys):
            status.update(f"{len(self._filtered_keys)} of {len(self._all_keys)} variables")
        elif self.dirty:
            status.update("Modified")
        else:
            status.update(f"{len(self._all_keys)} variables")

    def _set_status(self, message: str, is_error: bool = False) -> None:
        """Update status bar"""
        status = self.query_one("#status-bar", Static)
        if is_error:
            status.update(f"[red]{message}[/red]")
        else:
            status.update(message)

    def action_cursor_up(self) -> None:
        table = self.query_one(DataTable)
        table.action_cursor_up()

    def action_cursor_down(self) -> None:
        table = self.query_one(DataTable)
        table.action_cursor_down()

    def on_key(self, event) -> None:
        """Handle key events"""
        if event.key == "tab":
            self.action_cursor_down()
            event.prevent_default()
            event.stop()
        elif event.key == "shift+tab":
            self.action_cursor_up()
            event.prevent_default()
            event.stop()

    def action_quit_check(self) -> None:
        """Quit with dirty check"""
        if self.dirty:
            self.push_screen(
                ConfirmationModal("You have unsaved changes.\nAre you sure you want to quit?"),
                self._handle_quit_confirm
            )
        else:
            self.exit()

    def _handle_quit_confirm(self, should_quit: bool) -> None:
        if should_quit:
            self.exit()

    def action_command_palette(self) -> None:
        """Show command palette"""
        self.push_screen(CommandPalette(), self._handle_command_choice)

    def _handle_command_choice(self, choice: str) -> None:
        if choice == "edit":
            self.action_edit_variable()
        elif choice == "reveal":
            self.action_toggle_reveal()
        elif choice == "update":
            self.action_update_service()
        elif choice == "copy":
            self._copy_selected()

    def _copy_selected(self) -> None:
        """Copy all filtered variables to clipboard (called from Command Palette)"""
        self.action_copy_filtered()

    def action_copy_filtered(self) -> None:
        """Copy all filtered variables to clipboard"""
        if not self._filtered_keys:
            self._set_status("No variables to copy.", is_error=True)
            return

        # Build KEY=VALUE lines for all filtered variables
        lines = []
        for key in self._filtered_keys:
            value = self.current_env_vars.get(key, "")
            # Get raw value (unmask for copying)
            if key in self.secrets_map:
                # For secrets, use the stored value without mask
                raw_value = self._get_raw_secret_value(key)
                lines.append(f"{key}={raw_value}")
            else:
                lines.append(f"{key}={value}")

        clip_text = "\n".join(lines)
        self.copy_to_clipboard(clip_text)
        self.push_screen(SuccessModal("Copied", f"{len(self._filtered_keys)} variables copied to clipboard."))

    def _get_raw_secret_value(self, key: str) -> str:
        """Get raw value for a secret key (without mask)"""
        value = self.current_env_vars.get(key, "")
        # Remove any prefix markers
        if value.startswith('[SECURE]'):
            return value[8:]
        elif value.startswith('[SECRET]'):
            return value[8:]
        return value

    def action_toggle_reveal(self) -> None:
        """Reveal secret value for 2 seconds then hide again"""
        table = self.query_one(DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self._filtered_keys):
            self._set_status("No variable selected", is_error=True)
            return

        key = self._filtered_keys[table.cursor_row]

        # Only works for secrets
        if key not in self.secrets_map:
            self._set_status("Not a secret variable", is_error=True)
            return

        value = self.current_env_vars.get(key, "")

        # Only reveal if currently hidden
        if value.startswith('[SECURE]'):
            # Reveal: remove prefix temporarily
            revealed_value = value[8:]
            self.current_env_vars[key] = revealed_value
            self._refresh_table()
            self._set_status(f"Revealed: {key} (hiding in 2s)")
            # Schedule hide after 2 seconds
            self.set_timer(2.0, lambda: self._hide_secret(key, 'ssm', revealed_value))
        elif value.startswith('[SECRET]'):
            # Reveal: remove prefix temporarily
            revealed_value = value[8:]
            self.current_env_vars[key] = revealed_value
            self._refresh_table()
            self._set_status(f"Revealed: {key} (hiding in 2s)")
            # Schedule hide after 2 seconds
            self.set_timer(2.0, lambda: self._hide_secret(key, 'secretsmanager', revealed_value))
        else:
            self._set_status("Already revealed", is_error=True)

    def _hide_secret(self, key: str, secret_type: str, value: str) -> None:
        """Hide secret after timeout"""
        # Only hide if still revealed (user might have edited it)
        current = self.current_env_vars.get(key, "")
        if current == value:  # Still the same revealed value
            if secret_type == 'ssm':
                self.current_env_vars[key] = f'[SECURE]{value}'
            else:
                self.current_env_vars[key] = f'[SECRET]{value}'
            self._refresh_table()
            self._set_status(f"Hidden: {key}")

    def action_edit_variable(self) -> None:
        """Edit currently selected variable"""
        table = self.query_one(DataTable)
        if table.cursor_row is None or table.cursor_row >= len(self._filtered_keys):
            self._set_status("No variable selected", is_error=True)
            return

        key = self._filtered_keys[table.cursor_row]
        value = self.current_env_vars.get(key, "")

        # Strip [SECURE] or [SECRET] prefix for editing
        if value.startswith('[SECURE]'):
            value = value[8:]
        elif value.startswith('[SECRET]'):
            value = value[8:]

        self.push_screen(EditModal(key, value), lambda res: self._handle_edit_result(key, res))

    def _handle_edit_result(self, key: str, new_value: Optional[str]) -> None:
        if new_value is None:
            # Cancel - just refresh table to restore view
            self._refresh_table()
            return

        old_value = self.current_env_vars.get(key, "")
        # Strip prefix for comparison
        old_clean = old_value
        if old_clean.startswith('[SECURE]'):
            old_clean = old_clean[8:]
        elif old_clean.startswith('[SECRET]'):
            old_clean = old_clean[8:]

        if new_value == old_clean:
            return  # No change

        # Check if this is a secret (SSM or Secrets Manager)
        if key in self.secrets_map:
            secret_info = self.secrets_map[key]
            self._pending_update = {'key': key, 'value': new_value, 'secret_info': secret_info}

            if secret_info['type'] == 'ssm':
                msg = f"Update SSM Parameter?\n\n{secret_info['path']}"
            else:
                msg = f"Update Secrets Manager?\n\n{secret_info.get('arn', secret_info.get('full_ref', ''))}"

            self.push_screen(ConfirmationModal(msg), self._handle_secret_update_confirm)
        else:
            # Regular env var - mark dirty for task definition update
            self.current_env_vars[key] = new_value
            self.dirty = True
            self._refresh_table()
            self._set_status(f"Edited {key}")

    def _handle_secret_update_confirm(self, confirm: bool) -> None:
        if not confirm or not self._pending_update:
            self._pending_update = None
            return

        self._set_status("Updating secret...")
        self.run_worker(self._do_update_secret, name="update_secret", thread=True)

    def _do_update_secret(self) -> dict:
        """Update SSM or Secrets Manager"""
        info = self._pending_update
        secret_info = info['secret_info']
        new_value = info['value']

        if secret_info['type'] == 'ssm':
            path = secret_info['path']
            self.aws.update_ssm_parameter(path, new_value)
            return {'type': 'ssm', 'path': path, 'key': info['key']}
        else:
            arn = secret_info.get('arn', secret_info.get('full_ref'))
            json_key = secret_info.get('json_key')
            self.aws.update_secrets_manager(arn, new_value, json_key)
            return {'type': 'secretsmanager', 'arn': arn, 'json_key': json_key, 'key': info['key']}

    def on_worker_state_changed(self, event) -> None:
        """Handle worker completion"""
        if event.worker.name == "update_service":
            if event.state == WorkerState.SUCCESS:
                self.was_redeployed = True  # Mark for cache invalidation
                self._set_status("Service update initiated. Deployment started.")
                self.push_screen(SuccessModal("Deployment Started", "Service force update initiated.\nNew tasks will be deployed."))
            elif event.state == WorkerState.ERROR:
                error_msg = str(event.worker.error) if event.worker.error else "Unknown error"
                self._set_status("Update failed", is_error=True)
                self.push_screen(ErrorModal("Update Failed", error_msg))

        elif event.worker.name == "update_secret":
            if event.state == WorkerState.SUCCESS:
                result = event.worker.result
                key = result['key']

                # Update local state
                if self._pending_update:
                    new_val = self._pending_update['value']
                    old_val = self.current_env_vars.get(key, '')
                    # Preserve prefix
                    if old_val.startswith('[SECURE]'):
                        self.current_env_vars[key] = f'[SECURE]{new_val}'
                        self.original_env_vars[key] = f'[SECURE]{new_val}'
                    elif old_val.startswith('[SECRET]'):
                        self.current_env_vars[key] = f'[SECRET]{new_val}'
                        self.original_env_vars[key] = f'[SECRET]{new_val}'
                    else:
                        self.current_env_vars[key] = new_val
                        self.original_env_vars[key] = new_val

                self._refresh_table()
                self._pending_update = None

                if result['type'] == 'ssm':
                    msg = f"SSM Parameter updated:\n\n{result['path']}\n\nPress Ctrl+U to force redeploy service."
                    self.push_screen(SuccessModal("SSM Updated", msg))
                else:
                    arn = result.get('arn', '')
                    json_key = result.get('json_key', '')
                    msg = f"Secret updated:\n\n{arn}"
                    if json_key:
                        msg += f"\nKey: {json_key}"
                    msg += "\n\nPress Ctrl+U to force redeploy service."
                    self.push_screen(SuccessModal("Secret Updated", msg))

                self._set_status(f"Updated {key}")

            elif event.state == WorkerState.ERROR:
                error_msg = str(event.worker.error) if event.worker.error else "Unknown error"
                self._set_status("Update failed", is_error=True)
                self.push_screen(ErrorModal("Secret Update Failed", error_msg))
                self._pending_update = None

    def action_update_service(self) -> None:
        """Force update service (redeploy)"""
        if not self.service:
            self._set_status("No service context available.", is_error=True)
            return

        if not self.cluster:
            self._set_status("No cluster context available.", is_error=True)
            return

        msg = f"Force redeploy service '{self.service}'?"
        if self.new_task_def_arn:
            msg += f"\n\nWill use new task definition:\n{self.new_task_def_arn.split('/')[-1]}"
        else:
            msg += "\n\nThis will restart tasks with current task definition."

        self.push_screen(ConfirmationModal(msg), self._handle_update_confirm)

    def _handle_update_confirm(self, confirm: bool) -> None:
        if not confirm:
            return

        self._set_status("Updating service...")
        self.run_worker(self._do_update_service, name="update_service", thread=True)

    def _do_update_service(self) -> bool:
        """Actually update the service with force redeploy"""
        return self.aws.update_service(
            self.cluster,
            self.service,
            self.new_task_def_arn  # Can be None for just force redeploy
        )


# ==================== LOADING APP ====================

class EnvViewerLoadingApp(App):
    """Loading screen while fetching environment variables"""

    CSS = """
    Screen {
        background: #08060d;
        align: center middle;
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
    ]

    def __init__(self, aws_client, task: dict, container_name: str):
        super().__init__()
        self.aws = aws_client
        self._task = task
        self.container_name = container_name
        self.env_vars = None
        self.secrets_map = None

    def compose(self) -> ComposeResult:
        yield Container(
            LoadingIndicator(),
            Static("Retrieving environment variables..."),
            classes="loading-box"
        )

    def on_mount(self) -> None:
        self.run_worker(self._fetch_env_vars, name="fetch_env", thread=True)

    def _fetch_env_vars(self) -> dict:
        env_vars = self.aws.get_container_env_vars(self._task, self.container_name)
        secrets_map = self.aws.get_container_secrets_mapping(self._task, self.container_name)
        return {'env_vars': env_vars, 'secrets_map': secrets_map}

    def on_worker_state_changed(self, event) -> None:
        if event.worker.name != "fetch_env":
            return

        if event.state == WorkerState.SUCCESS:
            result = event.worker.result
            self.env_vars = result['env_vars']
            self.secrets_map = result['secrets_map']
            self.exit(result="success")
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


def run_env_viewer(aws_client, cluster: str, service: str, task_def_arn: str,
                   container_name: str, env_vars: dict, secrets_map: dict = None, task: dict = None):
    """Run the environment variable editor"""
    app = EnvEditorApp(aws_client, cluster, service, task_def_arn, container_name, env_vars, secrets_map, task)
    app.run()


def run_env_viewer_with_loading(aws_client, task: dict, container_name: str,
                                 cluster: str, service: str) -> dict:
    """Run env viewer with loading screen.

    Returns dict with:
    - was_redeployed: bool - whether service was redeployed
    - service: str - service ARN that was redeployed (if any)
    """
    result_info = {'was_redeployed': False, 'service': service}

    # First show loading screen
    loader = EnvViewerLoadingApp(aws_client, task, container_name)
    result = loader.run()

    if result == "success" and loader.env_vars is not None:
        task_def_arn = task.get('taskDefinitionArn', '')
        env_vars = loader.env_vars if loader.env_vars else {}
        secrets_map = loader.secrets_map if loader.secrets_map else {}

        # Then show the editor
        app = EnvEditorApp(
            aws_client=aws_client,
            cluster=cluster,
            service=service,
            task_def_arn=task_def_arn,
            container_name=container_name,
            env_vars=env_vars,
            secrets_map=secrets_map,
            task=task
        )
        app.run()

        # Check if service was redeployed
        result_info['was_redeployed'] = app.was_redeployed

    return result_info
