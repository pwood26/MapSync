"""Parse ESRI World Files (.tfw, .tiffw) for georeferencing metadata.

World files contain affine transformation parameters that define
the spatial reference of raster images.

World file format (6 lines):
Line 1: pixel size in x-direction (width of pixel in map units)
Line 2: rotation about y-axis (typically 0)
Line 3: rotation about x-axis (typically 0)
Line 4: pixel size in y-direction (height of pixel, negative value)
Line 5: x-coordinate of center of upper-left pixel
Line 6: y-coordinate of center of upper-left pixel
"""

import os
from typing import Optional, Dict


def find_worldfile(tiff_path: str) -> Optional[str]:
    """Find world file for a TIFF image.

    Checks for common world file extensions:
    - .tfw (TIFF World File)
    - .tifw
    - .tiffw

    Args:
        tiff_path: Path to TIFF file

    Returns:
        Path to world file if found, None otherwise
    """
    base_path = os.path.splitext(tiff_path)[0]

    # Common world file extensions
    extensions = ['.tfw', '.tifw', '.tiffw', '.TFW', '.TIFW', '.TIFFW']

    for ext in extensions:
        worldfile_path = base_path + ext
        if os.path.exists(worldfile_path):
            return worldfile_path

    return None


def parse_worldfile(worldfile_path: str, image_width: int, image_height: int) -> Optional[Dict]:
    """Parse world file and calculate corner coordinates.

    Args:
        worldfile_path: Path to world file (.tfw)
        image_width: Image width in pixels
        image_height: Image height in pixels

    Returns:
        Dict with corners, center coordinates, and GSD
    """
    try:
        with open(worldfile_path, 'r') as f:
            lines = [line.strip() for line in f.readlines() if line.strip()]

        if len(lines) < 6:
            return None

        # Parse affine transformation parameters
        pixel_size_x = float(lines[0])  # A: pixel width in map units
        rotation_y = float(lines[1])     # D: rotation about y-axis
        rotation_x = float(lines[2])     # B: rotation about x-axis
        pixel_size_y = float(lines[3])   # E: pixel height in map units (negative)
        upper_left_x = float(lines[4])   # C: x of upper-left pixel center
        upper_left_y = float(lines[5])   # F: y of upper-left pixel center

        # Calculate corner coordinates
        # Upper-left corner (already have center of pixel)
        ul_x = upper_left_x - (pixel_size_x / 2)
        ul_y = upper_left_y - (pixel_size_y / 2)

        # Upper-right corner
        ur_x = ul_x + (image_width * pixel_size_x)
        ur_y = ul_y + (image_width * rotation_x)

        # Lower-left corner
        ll_x = ul_x + (image_height * rotation_y)
        ll_y = ul_y + (image_height * pixel_size_y)

        # Lower-right corner
        lr_x = ur_x + (image_height * rotation_y)
        lr_y = ur_y + (image_height * pixel_size_y)

        # Get bounding box (min/max)
        all_x = [ul_x, ur_x, ll_x, lr_x]
        all_y = [ul_y, ur_y, ll_y, lr_y]

        west = min(all_x)
        east = max(all_x)
        north = max(all_y)
        south = min(all_y)

        # Calculate center
        center_lon = (west + east) / 2
        center_lat = (north + south) / 2

        # Estimate GSD (Ground Sample Distance)
        # Average of absolute pixel sizes
        gsd_x = abs(pixel_size_x) * 111111  # Convert degrees to meters (approximate)
        gsd_y = abs(pixel_size_y) * 111111
        gsd = (gsd_x + gsd_y) / 2

        return {
            'corners': {
                'north': north,
                'south': south,
                'east': east,
                'west': west,
            },
            'center_lat': center_lat,
            'center_lon': center_lon,
            'gsd': gsd,
            'source': 'World File (.tfw)',
            'has_rotation': abs(rotation_x) > 0.0001 or abs(rotation_y) > 0.0001,
        }

    except (ValueError, FileNotFoundError, Exception):
        return None


def try_extract_from_worldfile(tiff_path: str, image_width: int, image_height: int) -> Optional[Dict]:
    """Convenience function to find and parse world file.

    Args:
        tiff_path: Path to TIFF file
        image_width: Image width in pixels
        image_height: Image height in pixels

    Returns:
        Metadata dict if successful, None otherwise
    """
    worldfile_path = find_worldfile(tiff_path)

    if not worldfile_path:
        return None

    return parse_worldfile(worldfile_path, image_width, image_height)
