"""Configuration constants"""

from .config_manager import get_configured_regions

# Dynamic regions from config (or defaults)
REGIONS = get_configured_regions()

ECS_AGENT_CONTAINER_NAME = "ecs-agent"


def reload_regions():
    """Reload regions from config after setup"""
    global REGIONS
    REGIONS = get_configured_regions()
    return REGIONS
