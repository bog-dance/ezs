"""Configuration constants"""

from .config_manager import get_configured_regions, get_configured_accounts

# Dynamic regions from config (or defaults)
REGIONS = get_configured_regions()

ECS_AGENT_CONTAINER_NAME = "ecs-agent"


def reload_regions():
    """Reload regions from config after setup"""
    global REGIONS
    REGIONS = get_configured_regions()
    return REGIONS


def reload_accounts():
    """Reload accounts from config after setup"""
    return get_configured_accounts()
