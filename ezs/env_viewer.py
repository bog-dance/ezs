"""Environment Variable Viewer and Editor"""

from typing import Dict, List, Optional
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static, Footer, Input, Button, Label, ListItem, ListView
from textual.binding import Binding
from textual.screen import Screen, ModalScreen
from textual.containers import Container, Horizontal, Vertical, Grid
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

    Button {
        margin: 0 1;
    }
    """

    def __init__(self, key: str, value: str):
        super().__init__()
        self.key = key
        self.original_value = value
        self.new_value = value

    def compose(self) -> ComposeResult:
        yield Container(
            Static(f"Edit {self.key}", id="edit-title"),
            Static("Value:", id="key-label"),
            Input(value=self.original_value, id="edit-input"),
            Horizontal(
                Button("Cancel", variant="error", id="cancel"),
                Button("Save", variant="success", id="save"),
                id="btn-row"
            ),
            id="edit-dialog"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "save":
            input_widget = self.query_one("#edit-input", Input)
            self.dismiss(input_widget.value)
        else:
            self.dismiss(None)


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

    Button {
        margin: 0 1;
    }
    """

    def __init__(self, message: str):
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        yield Container(
            Static(self.message, id="confirm-message"),
            Horizontal(
                Button("No", variant="error", id="no"),
                Button("Yes", variant="success", id="yes"),
                id="confirm-btns"
            ),
            id="confirm-dialog"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "yes":
            self.dismiss(True)
        else:
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
                ListItem(Static("Register Task Revision (Ctrl+Y)"), id="register"),
                ListItem(Static("Update Service (Ctrl+U)"), id="update"),
                ListItem(Static("Copy Value (Ctrl+C)"), id="copy"),
                ListItem(Static("Close (Esc)"), id="close"),
            ),
            id="palette-container"
        )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        self.dismiss(event.item.id)


# ==================== MAIN APP ====================

class EnvEditorApp(App):
    """Viewer and Editor for ECS Environment Variables"""

    CSS = """
    Screen {
        background: #08060d;
    }

    DataTable {
        background: #08060d;
        color: #a99fc4;
        height: 1fr;
        border: solid #3d3556;
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

    #header {
        dock: top;
        height: 1;
        background: #3d3556;
        color: #a99fc4;
        text-style: bold;
        padding: 0 1;
    }

    #status-bar {
        dock: bottom;
        height: 1;
        background: #2a2536;
        color: #8a7fa0;
        padding: 0 1;
    }

    .dirty {
        color: #ffaa00;
    }
    """

    BINDINGS = [
        Binding("escape", "quit_check", "Back/Quit"),
        Binding("q", "quit_check", "Quit"),
        Binding("ctrl+p", "command_palette", "Commands"),
        Binding("ctrl+e", "edit_variable", "Edit"),
        Binding("ctrl+y", "register_task", "Register Revision"),
        Binding("ctrl+u", "update_service", "Update Service"),
    ]

    def __init__(self, aws_client, cluster: str, service: str, task_def_arn: str,
                 container_name: str, env_vars: dict):
        super().__init__()
        self.aws = aws_client
        self.cluster = cluster
        self.service = service
        self.original_task_def_arn = task_def_arn
        self.container_name = container_name

        # State
        self.original_env_vars = env_vars.copy()
        self.current_env_vars = env_vars.copy()
        self.dirty = False
        self.new_task_def_arn = None

    def compose(self) -> ComposeResult:
        title = f"Env Vars: {self.container_name} ({self.service})"
        yield Static(title, id="header")
        yield DataTable()
        yield Static("Ready", id="status-bar")
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Key", "Value")
        self._refresh_table()
        table.focus()

    def _refresh_table(self) -> None:
        """Refresh table content"""
        table = self.query_one(DataTable)
        table.clear()

        # Sort keys
        for key in sorted(self.current_env_vars.keys()):
            val = self.current_env_vars[key]

            # Check if modified
            orig = self.original_env_vars.get(key)
            if orig != val:
                key_display = Text(key, style="bold #ffaa00")
                val_display = Text(val, style="#ffaa00")
            else:
                key_display = key
                val_display = val

            table.add_row(key_display, val_display, key=key)

    def _set_status(self, message: str, is_error: bool = False) -> None:
        """Update status bar"""
        status = self.query_one("#status-bar", Static)
        if is_error:
            status.update(f"[red]{message}[/red]")
        else:
            status.update(message)

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
        elif choice == "register":
            self.action_register_task()
        elif choice == "update":
            self.action_update_service()
        elif choice == "copy":
            # Just a placeholder, rich doesn't access clipboard easily
            self._set_status("Clipboard copy not implemented in TUI")
        elif choice == "close":
            pass

    def action_edit_variable(self) -> None:
        """Edit currently selected variable"""
        table = self.query_one(DataTable)
        row_key = table.coordinate_to_cell_key(table.cursor_coordinate).row_key

        if not row_key:
            return

        key = str(row_key.value)
        value = self.current_env_vars.get(key, "")

        self.push_screen(EditModal(key, value), lambda res: self._handle_edit_result(key, res))

    def _handle_edit_result(self, key: str, new_value: Optional[str]) -> None:
        if new_value is not None and new_value != self.current_env_vars.get(key):
            self.current_env_vars[key] = new_value
            self.dirty = True
            self._refresh_table()
            self._set_status(f"Edited {key}. Press Ctrl+Y to register changes.")

    def action_register_task(self) -> None:
        """Register new task definition revision"""
        if not self.dirty:
            self._set_status("No changes to register.")
            return

        self.push_screen(
            ConfirmationModal("Register new Task Definition revision?"),
            self._handle_register_confirm
        )

    def _handle_register_confirm(self, confirm: bool) -> None:
        if not confirm:
            return

        self._set_status("Registering new task definition...")
        try:
            new_arn = self.aws.register_task_definition(
                self.original_task_def_arn,
                self.container_name,
                self.current_env_vars
            )
            self.new_task_def_arn = new_arn
            self.dirty = False
            self.original_task_def_arn = new_arn # Update reference to latest
            self.original_env_vars = self.current_env_vars.copy() # Reset dirty state base

            self._refresh_table()
            self._set_status(f"Registered: {new_arn.split('/')[-1]}. Press Ctrl+U to update service.")

        except Exception as e:
            self._set_status(f"Error registering task: {e}", is_error=True)

    def action_update_service(self) -> None:
        """Update service to use new revision"""
        if not self.new_task_def_arn:
            self._set_status("Register a new revision (Ctrl+Y) first.", is_error=True)
            return

        self.push_screen(
            ConfirmationModal(f"Update service '{self.service}' to use new revision?"),
            self._handle_update_confirm
        )

    def _handle_update_confirm(self, confirm: bool) -> None:
        if not confirm:
            return

        self._set_status("Updating service...")
        try:
            self.aws.update_service(
                self.cluster,
                self.service,
                self.new_task_def_arn
            )
            self._set_status("Service update initiated. Deployment started.")
        except Exception as e:
            self._set_status(f"Error updating service: {e}", is_error=True)


def run_env_viewer(aws_client, cluster: str, service: str, task_def_arn: str,
                   container_name: str, env_vars: dict):
    """Run the environment variable editor"""
    app = EnvEditorApp(aws_client, cluster, service, task_def_arn, container_name, env_vars)
    app.run()
