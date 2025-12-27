"""Interactive CLI prompts using simple-term-menu"""

from simple_term_menu import TerminalMenu
from typing import List, Optional, Union
from .aws_client import extract_name_from_arn


# Sentinel value for "go back"
class BackSignal:
    """Sentinel class to indicate user wants to go back."""
    pass


BACK = BackSignal()
BACK_OPTION = "← Back"


def _create_menu(entries: List[str], title: str, show_back: bool = True) -> TerminalMenu:
    """Create a terminal menu with search enabled."""
    menu_entries = [BACK_OPTION] + entries if show_back else entries
    return TerminalMenu(
        menu_entries,
        title=title,
        menu_cursor_style=("fg_cyan", "bold"),
        menu_highlight_style=("bg_cyan", "fg_black"),
        search_key="/",
        search_highlight_style=("fg_yellow", "bold"),
        quit_keys=("escape", "q", "\x04"),
    )


def select_region(regions: dict) -> Optional[str]:
    """Prompt user to select AWS region (no back option - first menu)"""
    if not regions:
        return None

    region_codes = list(regions.keys())
    display_names = [f"{name} ({code})" for code, name in regions.items()]

    menu = TerminalMenu(
        display_names,
        title="Select AWS region:",
        menu_cursor_style=("fg_cyan", "bold"),
        menu_highlight_style=("bg_cyan", "fg_black"),
        search_key="/",
        search_highlight_style=("fg_yellow", "bold"),
        quit_keys=("escape", "q", "\x04"),
    )
    idx = menu.show()
    return region_codes[idx] if idx is not None else None


def select_cluster(clusters: List[str]) -> Union[str, BackSignal, None]:
    """Prompt user to select ECS cluster"""
    if not clusters:
        print("No clusters found in this region")
        return None

    display_names = [extract_name_from_arn(c) for c in clusters]
    menu = _create_menu(display_names, "Select ECS cluster (type to search):")
    idx = menu.show()

    if idx is None:
        return None
    if idx == 0:
        return BACK
    return clusters[idx - 1]


def select_service(services: List[str]) -> Union[str, BackSignal, None]:
    """Prompt user to select ECS service"""
    if not services:
        print("No services found in this cluster")
        return None

    display_names = [extract_name_from_arn(s) for s in services]
    menu = _create_menu(display_names, "Select ECS service (type to search):")
    idx = menu.show()

    if idx is None:
        return None
    if idx == 0:
        return BACK
    return services[idx - 1]


def fuzzy_select_service(services: List[str]) -> Union[str, BackSignal, None]:
    """Fuzzy search prompt for service selection."""
    if not services:
        print("No matching services found.")
        return None

    display_names = [extract_name_from_arn(s) for s in services]
    menu = _create_menu(display_names, "Multiple services found (type to search):")
    idx = menu.show()

    if idx is None:
        return None
    if idx == 0:
        return BACK
    return services[idx - 1]


def select_task(tasks: List[dict]) -> Union[dict, BackSignal, None]:
    """Prompt user to select task (if multiple running)"""
    if not tasks:
        print("No running tasks found for this service")
        return None

    if len(tasks) == 1:
        return tasks[0]

    display_names = [
        f"{extract_name_from_arn(t['taskArn'])} (started: {t.get('startedAt', 'unknown')})"
        for t in tasks
    ]
    menu = _create_menu(display_names, "Multiple tasks running (type to search):")
    idx = menu.show()

    if idx is None:
        return None
    if idx == 0:
        return BACK
    return tasks[idx - 1]


def select_container(containers: List[dict]) -> Union[dict, BackSignal, None]:
    """Prompt user to select container"""
    if not containers:
        print("No service containers found in this task")
        return None

    if len(containers) == 1:
        return containers[0]

    display_names = [
        f"{c['name']} (status: {c.get('lastStatus', 'unknown')})"
        for c in containers
    ]
    menu = _create_menu(display_names, "Multiple containers found (type to search):")
    idx = menu.show()

    if idx is None:
        return None
    if idx == 0:
        return BACK
    return containers[idx - 1]


def confirm_container_exec() -> Union[bool, BackSignal]:
    """Ask user if they want to exec into container"""
    options = [BACK_OPTION, "Yes - connect to container", "No - SSH to host only"]

    menu = TerminalMenu(
        options,
        title="Connect to container?",
        menu_cursor_style=("fg_cyan", "bold"),
        menu_highlight_style=("bg_cyan", "fg_black"),
        cursor_index=1,
        quit_keys=("escape", "\x04"),
    )
    idx = menu.show()

    if idx is None or idx == 0:
        return BACK
    return idx == 1
