"""Environment Variable Viewer"""

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Static, Footer
from textual.binding import Binding

class EnvViewerApp(App):
    """A simple viewer for environment variables"""

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
        color: #a99fc4;
    }

    #title {
        dock: top;
        height: 1;
        background: #3d3556;
        color: #a99fc4;
        text-style: bold;
        padding: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "quit", "Back"),
        Binding("q", "quit", "Back"),
    ]

    def __init__(self, env_vars: dict, container_name: str):
        super().__init__()
        self.env_vars = env_vars
        self.container_name = container_name

    def compose(self) -> ComposeResult:
        yield Static(f"Environment Variables: {self.container_name}", id="title")
        yield DataTable()
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Key", "Value")

        # Sort keys
        for key in sorted(self.env_vars.keys()):
            table.add_row(key, self.env_vars[key])

        table.focus()

def run_env_viewer(env_vars: dict, container_name: str):
    app = EnvViewerApp(env_vars, container_name)
    app.run()
