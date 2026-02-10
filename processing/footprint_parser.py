"""Parse GeoJSON footprint files for georeferencing metadata.

USGS provides {entityId}_footprint.geojson files that contain
the exact spatial footprint of aerial photographs.
"""

import os
import json
from typing import Optional, Dict


def find_footprint_file(tiff_path: str) -> Optional[str]:
    """Find GeoJSON footprint file for a TIFF image.

    Looks for {entityId}_footprint.geojson in the same directory.

    Args:
        tiff_path: Path to TIFF file

    Returns:
        Path to footprint file if found, None otherwise
    """
    base_path = os.path.splitext(tiff_path)[0]

    # Check for _footprint.geojson
    footprint_path = base_path + '_footprint.geojson'
    if os.path.exists(footprint_path):
        return footprint_path

    # Also check without underscore
    footprint_path = base_path + 'footprint.geojson'
    if os.path.exists(footprint_path):
        return footprint_path

    return None


def parse_footprint_geojson(footprint_path: str) -> Optional[Dict]:
    """Parse GeoJSON footprint file to extract bounding coordinates.

    Args:
        footprint_path: Path to _footprint.geojson file

    Returns:
        Dict with corners, center coordinates
    """
    try:
        with open(footprint_path, 'r') as f:
            geojson = json.load(f)

        # GeoJSON can be FeatureCollection or single Feature
        if geojson.get('type') == 'FeatureCollection':
            features = geojson.get('features', [])
            if not features:
                return None
            feature = features[0]  # Use first feature
        elif geojson.get('type') == 'Feature':
            feature = geojson
        else:
            return None

        geometry = feature.get('geometry')
        if not geometry:
            return None

        # Extract coordinates from geometry
        geom_type = geometry.get('type')
        coords = geometry.get('coordinates')

        if not coords:
            return None

        # Handle different geometry types
        if geom_type == 'Polygon':
            # Polygon coordinates are [[[lon, lat], [lon, lat], ...]]
            points = coords[0]  # Exterior ring
        elif geom_type == 'MultiPolygon':
            # MultiPolygon coordinates are [[[[lon, lat], ...]], ...]
            points = coords[0][0]  # First polygon, exterior ring
        else:
            return None

        # Extract all lon/lat values
        lons = [point[0] for point in points]
        lats = [point[1] for point in points]

        # Calculate bounding box
        west = min(lons)
        east = max(lons)
        south = min(lats)
        north = max(lats)

        # Calculate center
        center_lon = (west + east) / 2
        center_lat = (north + south) / 2

        return {
            'corners': {
                'north': north,
                'south': south,
                'east': east,
                'west': west,
            },
            'center_lat': center_lat,
            'center_lon': center_lon,
            'source': 'GeoJSON Footprint',
        }

    except (json.JSONDecodeError, FileNotFoundError, KeyError, Exception):
        return None


def try_extract_from_footprint(tiff_path: str) -> Optional[Dict]:
    """Convenience function to find and parse footprint GeoJSON.

    Args:
        tiff_path: Path to TIFF file

    Returns:
        Metadata dict if successful, None otherwise
    """
    footprint_path = find_footprint_file(tiff_path)

    if not footprint_path:
        return None

    return parse_footprint_geojson(footprint_path)
