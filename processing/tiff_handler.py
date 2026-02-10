import os
import subprocess
import json
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

# Allow very large images (USGS aerials can be 100+ megapixels)
Image.MAX_IMAGE_PIXELS = 500_000_000

PREVIEW_MAX_DIM = 4096


def validate_tiff(filepath):
    """Validate that the file is a readable TIFF image."""
    try:
        with Image.open(filepath) as img:
            img.verify()
        # Re-open after verify (verify can leave the file in a bad state)
        with Image.open(filepath) as img:
            w, h = img.size
            if w < 10 or h < 10:
                return False, 'Image is too small'
        return True, {'width': w, 'height': h}
    except Exception as e:
        return False, f'Invalid TIFF file: {str(e)}'


def convert_to_preview(tiff_path, preview_path, max_dim=PREVIEW_MAX_DIM):
    """Convert a TIFF to a PNG preview suitable for browser display.

    Returns dict with original and preview dimensions plus scale factor.
    """
    with Image.open(tiff_path) as img:
        orig_w, orig_h = img.size

        # Convert to RGB if necessary (some TIFFs are 16-bit or have extra channels)
        if img.mode not in ('RGB', 'RGBA'):
            img = img.convert('RGB')

        # Compute resize dimensions
        if max(orig_w, orig_h) > max_dim:
            if orig_w >= orig_h:
                new_w = max_dim
                new_h = int(orig_h * (max_dim / orig_w))
            else:
                new_h = max_dim
                new_w = int(orig_w * (max_dim / orig_h))
            img = img.resize((new_w, new_h), Image.LANCZOS)
        else:
            new_w, new_h = orig_w, orig_h

        img.save(preview_path, 'PNG', optimize=True)

    scale_factor = orig_w / new_w

    return {
        'original_width': orig_w,
        'original_height': orig_h,
        'preview_width': new_w,
        'preview_height': new_h,
        'scale_factor': scale_factor,
    }


def extract_metadata(tiff_path):
    """Extract georeferencing metadata from TIFF file.

    Checks multiple sources:
    1. GDAL geotransform (already georeferenced TIFF)
    2. EXIF GPS tags (from aerial camera)
    3. TIFF tags with coordinate info

    Returns dict with:
    - 'has_georeference': bool (if GDAL geotransform exists)
    - 'has_gps': bool (if GPS EXIF tags exist)
    - 'center_lat', 'center_lon': float (if available)
    - 'corners': dict with north/south/east/west (if available)
    - 'gsd': float (ground sample distance in meters, if available)
    - 'source': str describing metadata source
    """
    metadata = {
        'has_georeference': False,
        'has_gps': False,
        'center_lat': None,
        'center_lon': None,
        'corners': None,
        'gsd': None,
        'source': None,
    }

    # Check for GDAL geotransform first (already georeferenced)
    gdal_meta = _extract_gdal_metadata(tiff_path)
    if gdal_meta:
        metadata.update(gdal_meta)
        metadata['has_georeference'] = True
        metadata['source'] = 'GDAL GeoTransform'
        return metadata

    # Check for GPS EXIF tags
    gps_meta = _extract_gps_exif(tiff_path)
    if gps_meta:
        metadata.update(gps_meta)
        metadata['has_gps'] = True
        metadata['source'] = 'EXIF GPS'
        return metadata

    return metadata


def _extract_gdal_metadata(tiff_path):
    """Extract georeference info using gdalinfo if available."""
    try:
        result = subprocess.run(
            ['gdalinfo', '-json', tiff_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            return None

        info = json.loads(result.stdout)

        # Check if geotransform exists and is not identity
        gt = info.get('geoTransform')
        if not gt or gt == [0, 1, 0, 0, 0, 1]:
            return None

        # Get corner coordinates
        corner_coords = info.get('cornerCoordinates', {})
        if not corner_coords:
            return None

        # Extract lat/lon from corners
        upper_left = corner_coords.get('upperLeft', [])
        upper_right = corner_coords.get('upperRight', [])
        lower_left = corner_coords.get('lowerLeft', [])
        lower_right = corner_coords.get('lowerRight', [])

        if len(upper_left) < 2 or len(lower_right) < 2:
            return None

        # Calculate center and bounds
        west = upper_left[0]
        east = upper_right[0]
        north = upper_left[1]
        south = lower_left[1]

        center_lon = (west + east) / 2
        center_lat = (north + south) / 2

        # Estimate GSD from geotransform (pixel width in degrees, convert to meters)
        # At equator: 1 degree ≈ 111,111 meters
        pixel_width_deg = abs(gt[1])
        gsd = pixel_width_deg * 111111 * abs(center_lat / 90)  # Rough latitude correction

        return {
            'center_lat': center_lat,
            'center_lon': center_lon,
            'corners': {
                'north': north,
                'south': south,
                'east': east,
                'west': west,
            },
            'gsd': gsd,
        }

    except (subprocess.TimeoutExpired, FileNotFoundError, json.JSONDecodeError, Exception):
        return None


def _extract_gps_exif(tiff_path):
    """Extract GPS coordinates from EXIF tags."""
    try:
        with Image.open(tiff_path) as img:
            exif_data = img._getexif()
            if not exif_data:
                return None

            # Find GPSInfo tag
            gps_info = None
            for tag_id, value in exif_data.items():
                tag_name = TAGS.get(tag_id, tag_id)
                if tag_name == 'GPSInfo':
                    gps_info = value
                    break

            if not gps_info:
                return None

            # Decode GPS tags
            gps_data = {}
            for gps_tag_id, value in gps_info.items():
                gps_tag_name = GPSTAGS.get(gps_tag_id, gps_tag_id)
                gps_data[gps_tag_name] = value

            # Extract latitude
            if 'GPSLatitude' not in gps_data or 'GPSLatitudeRef' not in gps_data:
                return None

            lat = _convert_gps_coords(gps_data['GPSLatitude'])
            if gps_data['GPSLatitudeRef'] == 'S':
                lat = -lat

            # Extract longitude
            if 'GPSLongitude' not in gps_data or 'GPSLongitudeRef' not in gps_data:
                return None

            lon = _convert_gps_coords(gps_data['GPSLongitude'])
            if gps_data['GPSLongitudeRef'] == 'W':
                lon = -lon

            # Try to get altitude for better GSD estimation
            altitude = None
            if 'GPSAltitude' in gps_data:
                alt_value = gps_data['GPSAltitude']
                if isinstance(alt_value, tuple) and len(alt_value) == 2:
                    altitude = alt_value[0] / alt_value[1]

            # Estimate GSD if we have focal length and sensor info
            # This is a rough estimate - real calculation needs camera specs
            gsd = None
            focal_length = exif_data.get(37386)  # FocalLength tag
            if focal_length and altitude:
                # Very rough estimate: GSD ≈ (altitude * sensor_pixel_size) / focal_length
                # Assume typical 4-5 micron pixel size for aerial cameras
                sensor_pixel_size = 0.000005  # 5 microns in meters
                if isinstance(focal_length, tuple):
                    focal_length = focal_length[0] / focal_length[1]
                focal_length_m = focal_length / 1000  # Convert mm to meters
                if focal_length_m > 0:
                    gsd = (altitude * sensor_pixel_size) / focal_length_m

            return {
                'center_lat': lat,
                'center_lon': lon,
                'gsd': gsd,
            }

    except (AttributeError, KeyError, TypeError, Exception):
        return None


def _convert_gps_coords(gps_coord_tuple):
    """Convert GPS coordinate from EXIF format (degrees, minutes, seconds) to decimal."""
    degrees = gps_coord_tuple[0]
    minutes = gps_coord_tuple[1]
    seconds = gps_coord_tuple[2]

    # Handle rational numbers (stored as tuples)
    if isinstance(degrees, tuple):
        degrees = degrees[0] / degrees[1]
    if isinstance(minutes, tuple):
        minutes = minutes[0] / minutes[1]
    if isinstance(seconds, tuple):
        seconds = seconds[0] / seconds[1]

    return degrees + (minutes / 60.0) + (seconds / 3600.0)
