"""Configuration manager for EZS"""

import os
import yaml
import boto3
from pathlib import Path
from typing import List, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
from rich.console import Console

console = Console()

CONFIG_DIR = Path.home() / ".config" / "ezs"
CONFIG_FILE = CONFIG_DIR / "config.yaml"

# Fallback regions if config doesn't exist and user skips setup
DEFAULT_REGIONS = {
    "us-east-1": "N.Virginia",
    "eu-west-1": "Ireland",
    "eu-west-2": "London",
}

# Full list of AWS region display names
REGION_NAMES = {
    "us-east-1": "N.Virginia",
    "us-east-2": "Ohio",
    "us-west-1": "N.California",
    "us-west-2": "Oregon",
    "af-south-1": "Cape Town",
    "ap-east-1": "Hong Kong",
    "ap-south-1": "Mumbai",
    "ap-south-2": "Hyderabad",
    "ap-southeast-1": "Singapore",
    "ap-southeast-2": "Sydney",
    "ap-southeast-3": "Jakarta",
    "ap-southeast-4": "Melbourne",
    "ap-northeast-1": "Tokyo",
    "ap-northeast-2": "Seoul",
    "ap-northeast-3": "Osaka",
    "ca-central-1": "Canada",
    "ca-west-1": "Calgary",
    "eu-central-1": "Frankfurt",
    "eu-central-2": "Zurich",
    "eu-west-1": "Ireland",
    "eu-west-2": "London",
    "eu-west-3": "Paris",
    "eu-south-1": "Milan",
    "eu-south-2": "Spain",
    "eu-north-1": "Stockholm",
    "il-central-1": "Tel Aviv",
    "me-south-1": "Bahrain",
    "me-central-1": "UAE",
    "sa-east-1": "São Paulo",
}


def config_exists() -> bool:
    """Check if config file exists"""
    return CONFIG_FILE.exists()


def load_config() -> Dict:
    """Load config from file"""
    if not CONFIG_FILE.exists():
        return {}

    try:
        with open(CONFIG_FILE, 'r') as f:
            return yaml.safe_load(f) or {}
    except Exception as e:
        console.print(f"[yellow]Warning: Could not load config: {e}[/yellow]")
        return {}


def save_config(config: Dict) -> bool:
    """Save config to file"""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        return True
    except Exception as e:
        console.print(f"[red]Error saving config: {e}[/red]")
        return False


def get_configured_regions() -> Dict[str, str]:
    """Get regions from config or return defaults"""
    config = load_config()
    region_codes = config.get('regions', [])

    if not region_codes:
        return DEFAULT_REGIONS

    # Build dict with display names
    return {
        code: REGION_NAMES.get(code, code)
        for code in region_codes
    }


def save_regions(region_codes: List[str]) -> bool:
    """Save selected regions to config"""
    config = load_config()
    config['regions'] = region_codes
    return save_config(config)


def get_all_aws_regions(profile: Optional[str] = None) -> List[str]:
    """Get all opted-in AWS regions for the account"""
    try:
        session = boto3.Session(profile_name=profile)
        ec2 = session.client('ec2', region_name='us-east-1')

        response = ec2.describe_regions(
            AllRegions=True,
            Filters=[
                {
                    'Name': 'opt-in-status',
                    'Values': ['opt-in-not-required', 'opted-in']
                }
            ]
        )

        regions = [r['RegionName'] for r in response.get('Regions', [])]
        return sorted(regions)

    except Exception as e:
        console.print(f"[red]Error fetching regions: {e}[/red]")
        return list(DEFAULT_REGIONS.keys())


def detect_ecs_regions(profile: Optional[str] = None, progress_callback=None) -> List[str]:
    """
    Scan all regions for ECS clusters.
    Returns list of regions that have at least one cluster.
    progress_callback(current, total, region) is called for each region scanned.
    """
    all_regions = get_all_aws_regions(profile)
    regions_with_ecs = []

    def check_region(region: str) -> Optional[str]:
        """Check if region has ECS clusters"""
        try:
            session = boto3.Session(region_name=region, profile_name=profile)
            ecs = session.client('ecs')
            response = ecs.list_clusters()
            if response.get('clusterArns'):
                return region
        except Exception:
            pass
        return None

    total = len(all_regions)
    completed = 0

    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = {executor.submit(check_region, r): r for r in all_regions}

        for future in as_completed(futures):
            completed += 1
            region = futures[future]

            if progress_callback:
                progress_callback(completed, total, region)

            result = future.result()
            if result:
                regions_with_ecs.append(result)

    return sorted(regions_with_ecs)


def get_region_display_name(region_code: str) -> str:
    """Get display name for region code"""
    return REGION_NAMES.get(region_code, region_code)
