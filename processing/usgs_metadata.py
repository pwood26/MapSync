"""USGS EarthExplorer metadata retrieval via M2M API.

Fetches corner coordinates and metadata for aerial single frame imagery
when Entity ID is detected in the TIFF filename.
"""

import os
import re
import requests
import json
from typing import Optional, Dict


# USGS M2M API endpoint
M2M_API_URL = "https://m2m.cr.usgs.gov/api/api/json/stable/"

# Entity ID patterns for different USGS aerial collections
# Examples: AR1131860010276, CA1234567890123, etc.
ENTITY_ID_PATTERN = re.compile(r'[A-Z]{2}\d{13}')


def extract_entity_id_from_filename(filename: str) -> Optional[str]:
    """Extract USGS Entity ID from filename.

    Args:
        filename: The TIFF filename (e.g., "AR1131860010276.tif")

    Returns:
        Entity ID string if found, None otherwise
    """
    # Remove extension and path
    basename = os.path.splitext(os.path.basename(filename))[0]

    # Search for Entity ID pattern
    match = ENTITY_ID_PATTERN.search(basename)
    if match:
        return match.group(0)

    return None


def fetch_metadata_from_usgs(entity_id: str, api_key: Optional[str] = None) -> Optional[Dict]:
    """Fetch metadata from USGS M2M API for a given Entity ID.

    Args:
        entity_id: USGS Entity ID (e.g., "AR1131860010276")
        api_key: Optional USGS M2M API key (if None, tries public access)

    Returns:
        Dict with corner coordinates and metadata, or None if unavailable
    """
    # Note: USGS M2M API requires authentication for most operations
    # For now, we'll try the metadata endpoint which may work without auth
    # Users can optionally configure API key in environment variable

    if not api_key:
        api_key = os.environ.get('USGS_M2M_API_KEY')

    # First, we need to login if we have credentials
    session_token = None
    username = os.environ.get('USGS_USERNAME')
    password = os.environ.get('USGS_PASSWORD')

    if username and password:
        session_token = _login_to_usgs(username, password)

    if not session_token:
        # Without authentication, we cannot access the API
        # Fall back to parsing from EarthExplorer metadata XML if available
        return None

    try:
        # Use scene-metadata endpoint to get details
        url = M2M_API_URL + "scene-metadata"

        payload = {
            "datasetName": "aerial_combin",  # Combined aerial dataset
            "entityId": entity_id,
            "metadataType": "full"
        }

        headers = {
            "Content-Type": "application/json",
            "X-Auth-Token": session_token
        }

        response = requests.post(url, json=payload, headers=headers, timeout=30)

        if response.status_code != 200:
            return None

        data = response.json()

        if not data.get('data'):
            return None

        # Extract corner coordinates from metadata
        return _parse_usgs_metadata(data['data'])

    except Exception:
        return None
    finally:
        if session_token:
            _logout_from_usgs(session_token)


def _login_to_usgs(username: str, password: str) -> Optional[str]:
    """Login to USGS M2M API and get session token."""
    try:
        url = M2M_API_URL + "login"
        payload = {
            "username": username,
            "password": password
        }

        response = requests.post(url, json=payload, timeout=10)

        if response.status_code == 200:
            data = response.json()
            return data.get('data')

        return None
    except Exception:
        return None


def _logout_from_usgs(session_token: str):
    """Logout from USGS M2M API."""
    try:
        url = M2M_API_URL + "logout"
        headers = {"X-Auth-Token": session_token}
        requests.post(url, headers=headers, timeout=5)
    except Exception:
        pass


def _parse_usgs_metadata(metadata: Dict) -> Optional[Dict]:
    """Parse USGS metadata response to extract corner coordinates.

    Args:
        metadata: Raw metadata dict from M2M API

    Returns:
        Dict with 'corners', 'center_lat', 'center_lon', 'entity_id'
    """
    try:
        # Look for spatial coverage in metadata
        spatial = metadata.get('spatialCoverage', {})

        if not spatial:
            # Try alternative metadata structure
            browse = metadata.get('browse', [])
            if browse and len(browse) > 0:
                spatial = browse[0].get('spatialCoverage', {})

        # Extract corner coordinates
        # Format may vary - check for common field names
        coordinates = spatial.get('coordinates') or spatial.get('boundingBox')

        if not coordinates:
            return None

        # Parse coordinates (format varies by dataset)
        # Typical format: {"north": 34.5, "south": 34.4, "east": -90.1, "west": -90.2}
        if isinstance(coordinates, dict):
            north = coordinates.get('north') or coordinates.get('maxY')
            south = coordinates.get('south') or coordinates.get('minY')
            east = coordinates.get('east') or coordinates.get('maxX')
            west = coordinates.get('west') or coordinates.get('minX')

            if all([north, south, east, west]):
                center_lat = (north + south) / 2
                center_lon = (east + west) / 2

                return {
                    'corners': {
                        'north': north,
                        'south': south,
                        'east': east,
                        'west': west,
                    },
                    'center_lat': center_lat,
                    'center_lon': center_lon,
                    'entity_id': metadata.get('entityId'),
                    'source': 'USGS M2M API',
                }

        return None

    except Exception:
        return None


def try_fetch_usgs_metadata(tiff_path: str) -> Optional[Dict]:
    """Convenience function to extract Entity ID and fetch metadata.

    Args:
        tiff_path: Path to TIFF file

    Returns:
        Metadata dict with corners if successful, None otherwise
    """
    entity_id = extract_entity_id_from_filename(tiff_path)

    if not entity_id:
        return None

    return fetch_metadata_from_usgs(entity_id)
