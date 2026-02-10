"""Metadata-based georeferencing using embedded location data."""

import math
from PIL import Image


def georeference_from_metadata(metadata, image_width, image_height):
    """Generate GCPs from TIFF metadata.

    Args:
        metadata: Dict from extract_metadata() with center_lat, center_lon, etc.
        image_width: Original image width in pixels.
        image_height: Original image height in pixels.

    Returns:
        Dict with 'success', 'gcps', 'method', or 'error'.
        GCPs are in the format expected by run_georeferencing():
        {'id': int, 'pixel_x': float, 'pixel_y': float, 'lat': float, 'lon': float}
    """
    # Case 1: Already georeferenced with corner coordinates
    if metadata.get('has_georeference') and metadata.get('corners'):
        return _generate_corner_gcps(
            metadata['corners'],
            image_width,
            image_height,
            method='GDAL GeoTransform'
        )

    # Case 2: GPS center point with GSD estimation
    if metadata.get('has_gps') and metadata.get('center_lat') and metadata.get('center_lon'):
        if metadata.get('gsd'):
            # Generate corner coordinates from center + GSD
            return _generate_gcps_from_center_and_gsd(
                metadata['center_lat'],
                metadata['center_lon'],
                metadata['gsd'],
                image_width,
                image_height,
                method='GPS + GSD'
            )
        else:
            # Only center point, no size info - not enough to georeference
            return {
                'error': (
                    'Image contains GPS coordinates but lacks Ground Sample Distance (GSD) data. '
                    'Cannot automatically determine image extent. '
                    'Please use auto-georeferencing or manual GCP placement.'
                )
            }

    # No usable metadata
    return {
        'error': 'No georeferencing metadata found in image.'
    }


def _generate_corner_gcps(corners, width, height, method):
    """Generate GCPs at the four corners and center of the image."""
    north = corners['north']
    south = corners['south']
    east = corners['east']
    west = corners['west']

    center_lat = (north + south) / 2
    center_lon = (east + west) / 2

    gcps = [
        # Four corners
        {'id': 1, 'pixel_x': 0, 'pixel_y': 0, 'lat': north, 'lon': west},
        {'id': 2, 'pixel_x': width, 'pixel_y': 0, 'lat': north, 'lon': east},
        {'id': 3, 'pixel_x': 0, 'pixel_y': height, 'lat': south, 'lon': west},
        {'id': 4, 'pixel_x': width, 'pixel_y': height, 'lat': south, 'lon': east},
        # Center for additional control
        {'id': 5, 'pixel_x': width / 2, 'pixel_y': height / 2, 'lat': center_lat, 'lon': center_lon},
    ]

    return {
        'success': True,
        'gcps': gcps,
        'method': method,
    }


def _generate_gcps_from_center_and_gsd(center_lat, center_lon, gsd, width, height, method):
    """Generate corner GCPs from center point and ground sample distance.

    Args:
        center_lat, center_lon: Geographic center of the image.
        gsd: Ground sample distance in meters per pixel.
        width, height: Image dimensions in pixels.
    """
    # Calculate the geographic extent covered by the image
    # Half dimensions in pixels
    half_width_px = width / 2
    half_height_px = height / 2

    # Distance from center to edge in meters
    half_width_m = half_width_px * gsd
    half_height_m = half_height_px * gsd

    # Convert meters to degrees (approximate)
    # At the equator: 1 degree latitude ≈ 111,111 meters
    # Longitude varies by latitude: 1 degree longitude ≈ 111,111 * cos(latitude) meters
    meters_per_degree_lat = 111111
    meters_per_degree_lon = 111111 * math.cos(math.radians(center_lat))

    lat_span = half_height_m / meters_per_degree_lat
    lon_span = half_width_m / meters_per_degree_lon

    # Calculate corner coordinates
    # Note: In image coordinates, Y increases downward, but latitude increases upward
    north = center_lat + lat_span
    south = center_lat - lat_span
    east = center_lon + lon_span
    west = center_lon - lon_span

    corners = {
        'north': north,
        'south': south,
        'east': east,
        'west': west,
    }

    return _generate_corner_gcps(corners, width, height, method)


def estimate_gsd_from_bounds(bounds, width, height):
    """Estimate ground sample distance from user-provided bounding box.

    Args:
        bounds: Dict with 'north', 'south', 'east', 'west'.
        width, height: Image dimensions in pixels.

    Returns:
        Float: Estimated GSD in meters per pixel.
    """
    center_lat = (bounds['north'] + bounds['south']) / 2

    # Calculate geographic spans
    lat_span = bounds['north'] - bounds['south']
    lon_span = bounds['east'] - bounds['west']

    # Convert to meters
    meters_per_degree_lat = 111111
    meters_per_degree_lon = 111111 * math.cos(math.radians(center_lat))

    height_m = lat_span * meters_per_degree_lat
    width_m = lon_span * meters_per_degree_lon

    # Average GSD from both dimensions
    gsd_y = height_m / height
    gsd_x = width_m / width

    return (gsd_x + gsd_y) / 2
