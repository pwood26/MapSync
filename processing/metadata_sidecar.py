"""Parse USGS metadata from sidecar files.

USGS aerial imagery often comes with metadata XML/TXT files.
This module parses those files to extract corner coordinates.

Common metadata file formats:
- .xml (FGDC metadata)
- _meta.txt (EarthExplorer metadata export)
- .met (metadata file)
"""

import os
import re
import xml.etree.ElementTree as ET
from typing import Optional, Dict


def find_metadata_sidecar(tiff_path: str) -> Optional[str]:
    """Find metadata sidecar file for a TIFF.

    Looks for common metadata file patterns:
    - same_name.xml
    - same_name_meta.txt
    - same_name.met

    Args:
        tiff_path: Path to TIFF file

    Returns:
        Path to metadata file if found, None otherwise
    """
    base_path = os.path.splitext(tiff_path)[0]
    dir_path = os.path.dirname(tiff_path)
    basename = os.path.basename(base_path)

    # Common metadata file patterns
    patterns = [
        base_path + '.xml',
        base_path + '_meta.txt',
        base_path + '.met',
        os.path.join(dir_path, basename + '.xml'),
        os.path.join(dir_path, 'metadata', basename + '.xml'),
    ]

    for path in patterns:
        if os.path.exists(path):
            return path

    return None


def parse_metadata_file(metadata_path: str) -> Optional[Dict]:
    """Parse metadata file to extract corner coordinates.

    Args:
        metadata_path: Path to metadata file (.xml, .txt, .met)

    Returns:
        Dict with corners, center, source info
    """
    if metadata_path.endswith('.xml'):
        return _parse_xml_metadata(metadata_path)
    elif metadata_path.endswith('.txt') or metadata_path.endswith('.met'):
        return _parse_text_metadata(metadata_path)

    return None


def _parse_xml_metadata(xml_path: str) -> Optional[Dict]:
    """Parse FGDC XML metadata file.

    USGS FGDC metadata contains:
    - <bounding><westbc>, <eastbc>, <northbc>, <southbc>
    """
    try:
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # Look for bounding coordinates (FGDC standard)
        # Try multiple path variations
        bounding = root.find('.//bounding')

        # If not found, try direct search for coordinate elements
        if bounding is None:
            west_elem = root.find('.//westbc')
            east_elem = root.find('.//eastbc')
            north_elem = root.find('.//northbc')
            south_elem = root.find('.//southbc')
        else:
            west_elem = bounding.find('westbc')
            east_elem = bounding.find('eastbc')
            north_elem = bounding.find('northbc')
            south_elem = bounding.find('southbc')

            if all([west_elem is not None, east_elem is not None,
                    north_elem is not None, south_elem is not None]):
                west = float(west_elem.text)
                east = float(east_elem.text)
                north = float(north_elem.text)
                south = float(south_elem.text)

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
                    'source': 'FGDC XML Metadata',
                }

        # Alternative: Look for corner coordinates in different format
        # Some metadata uses <G-Polygon> with corner points
        gpolygon = root.find('.//G-Polygon')
        if gpolygon is not None:
            coords = []
            for point in gpolygon.findall('.//G-Ring_Point'):
                lat_elem = point.find('Latitude')
                lon_elem = point.find('Longitude')
                if lat_elem is not None and lon_elem is not None:
                    coords.append({
                        'lat': float(lat_elem.text),
                        'lon': float(lon_elem.text)
                    })

            if len(coords) >= 4:
                lats = [c['lat'] for c in coords]
                lons = [c['lon'] for c in coords]

                north = max(lats)
                south = min(lats)
                east = max(lons)
                west = min(lons)

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
                    'source': 'XML G-Polygon',
                }

        return None

    except Exception:
        return None


def _parse_text_metadata(txt_path: str) -> Optional[Dict]:
    """Parse text-based metadata file.

    Looks for patterns like:
    - Corner Coordinates:
    - NE_CORNER_LAT: 34.567
    - Scene Center: 34.5, -90.1
    """
    try:
        with open(txt_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()

        # Common patterns for corner coordinates
        patterns = {
            'north': r'(?:NORTH|NW_CORNER_LAT|NORTHEAST.*LAT)[:\s]+([+-]?\d+\.?\d*)',
            'south': r'(?:SOUTH|SW_CORNER_LAT|SOUTHWEST.*LAT)[:\s]+([+-]?\d+\.?\d*)',
            'east': r'(?:EAST|NE_CORNER_LON|NORTHEAST.*LON)[:\s]+([+-]?\d+\.?\d*)',
            'west': r'(?:WEST|NW_CORNER_LON|NORTHWEST.*LON)[:\s]+([+-]?\d+\.?\d*)',
        }

        coords = {}
        for key, pattern in patterns.items():
            match = re.search(pattern, content, re.IGNORECASE)
            if match:
                coords[key] = float(match.group(1))

        if len(coords) == 4:
            center_lat = (coords['north'] + coords['south']) / 2
            center_lon = (coords['east'] + coords['west']) / 2

            return {
                'corners': {
                    'north': coords['north'],
                    'south': coords['south'],
                    'east': coords['east'],
                    'west': coords['west'],
                },
                'center_lat': center_lat,
                'center_lon': center_lon,
                'source': 'Text Metadata File',
            }

        # Try alternative pattern: Scene Center
        center_match = re.search(
            r'(?:SCENE.*CENTER|CENTER)[:\s]+([+-]?\d+\.?\d*)[,\s]+([+-]?\d+\.?\d*)',
            content,
            re.IGNORECASE
        )

        if center_match:
            center_lat = float(center_match.group(1))
            center_lon = float(center_match.group(2))

            return {
                'center_lat': center_lat,
                'center_lon': center_lon,
                'source': 'Text Metadata (Center Only)',
            }

        return None

    except Exception:
        return None


def try_extract_from_sidecar(tiff_path: str) -> Optional[Dict]:
    """Convenience function to find and parse metadata sidecar.

    Args:
        tiff_path: Path to TIFF file

    Returns:
        Metadata dict if successful, None otherwise
    """
    metadata_file = find_metadata_sidecar(tiff_path)

    if not metadata_file:
        return None

    return parse_metadata_file(metadata_file)
