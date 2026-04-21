"""
Version management for EzPrint Agent
"""
from datetime import datetime

# Application version (Semantic Versioning: MAJOR.MINOR.PATCH)
VERSION = "1.0.0"

# Build metadata
BUILD_DATE = "2024-04-08"
BUILD_NUMBER = "1"

# Release channel (stable, beta, dev)
CHANNEL = "stable"

# Full version string
VERSION_STRING = f"v{VERSION}"
FULL_VERSION = f"v{VERSION}-{CHANNEL}"

# Application metadata
APP_NAME = "EzPrint Agent"
APP_DESCRIPTION = "Print shop management and printing agent"
COMPANY_NAME = "EzPrint"
COPYRIGHT = f"Copyright © {datetime.now().year} {COMPANY_NAME}"

# Minimum supported version for updates
MIN_SUPPORTED_VERSION = "1.0.0"


def get_version_info():
    """
    Get complete version information as dictionary

    Returns:
        dict: Version information
    """
    return {
        'version': VERSION,
        'build_date': BUILD_DATE,
        'build_number': BUILD_NUMBER,
        'channel': CHANNEL,
        'app_name': APP_NAME,
        'full_version': FULL_VERSION
    }


def compare_versions(version1, version2):
    """
    Compare two semantic version strings

    Args:
        version1 (str): First version (e.g., "1.0.0")
        version2 (str): Second version (e.g., "1.0.1")

    Returns:
        int: -1 if version1 < version2, 0 if equal, 1 if version1 > version2
    """
    def parse_version(v):
        # Remove 'v' prefix if present
        v = v.lstrip('v')
        # Split and convert to integers
        return tuple(map(int, v.split('.')))

    try:
        v1 = parse_version(version1)
        v2 = parse_version(version2)

        if v1 < v2:
            return -1
        elif v1 > v2:
            return 1
        else:
            return 0
    except Exception:
        # If parsing fails, assume versions are incomparable
        return 0


def is_newer_version(current, latest):
    """
    Check if latest version is newer than current

    Args:
        current (str): Current version
        latest (str): Latest version

    Returns:
        bool: True if latest is newer
    """
    return compare_versions(current, latest) < 0


# Version for display in UI
DISPLAY_VERSION = f"{APP_NAME} {VERSION_STRING} ({CHANNEL})"
