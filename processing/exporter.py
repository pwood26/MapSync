import json
import os
import subprocess
import tempfile
import zipfile


def generate_kmz(georef_tiff, kmz_path):
    """Generate a KMZ file from a georeferenced GeoTIFF.

    The KMZ contains a KML ground overlay and a JPEG image,
    suitable for opening in Google Earth.

    Returns:
        Dict with 'success' and 'bounds', or 'error'.
    """
    try:
        # Step 1: Get bounding box from the georeferenced TIFF
        bounds = get_bounds(georef_tiff)
        if not bounds:
            return {'error': 'Could not extract bounds from georeferenced TIFF'}

        # Step 2: Convert georeferenced TIFF to JPEG
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp:
            jpeg_path = tmp.name

        cmd = [
            'gdal_translate',
            '-of', 'JPEG',
            '-co', 'QUALITY=85',
            '-b', '1', '-b', '2', '-b', '3',  # Ensure RGB bands only
            georef_tiff,
            jpeg_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            # Try without explicit band selection (some images have fewer bands)
            cmd = [
                'gdal_translate',
                '-of', 'JPEG',
                '-co', 'QUALITY=85',
                georef_tiff,
                jpeg_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0:
                return {'error': f'JPEG conversion failed: {result.stderr}'}

        # Step 3: Build KML
        kml_content = build_kml(bounds)

        # Step 4: Package into KMZ (ZIP containing doc.kml + overlay.jpg)
        with zipfile.ZipFile(kmz_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            zf.writestr('doc.kml', kml_content)
            zf.write(jpeg_path, 'overlay.jpg')

        return {
            'success': True,
            'bounds': bounds,
        }

    except subprocess.TimeoutExpired:
        return {'error': 'JPEG conversion timed out'}
    except FileNotFoundError:
        return {'error': 'GDAL not found. Install with: brew install gdal'}
    except Exception as e:
        return {'error': str(e)}
    finally:
        if 'jpeg_path' in locals() and os.path.exists(jpeg_path):
            os.remove(jpeg_path)


def get_bounds(georef_tiff):
    """Extract geographic bounding box from a georeferenced GeoTIFF."""
    try:
        result = subprocess.run(
            ['gdalinfo', '-json', georef_tiff],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return None

        info = json.loads(result.stdout)
        corners = info.get('cornerCoordinates', {})

        upper_left = corners.get('upperLeft')
        lower_right = corners.get('lowerRight')
        upper_right = corners.get('upperRight')
        lower_left = corners.get('lowerLeft')

        if not all([upper_left, lower_right, upper_right, lower_left]):
            return None

        # Compute bounding box from all corners
        all_lons = [upper_left[0], lower_right[0], upper_right[0], lower_left[0]]
        all_lats = [upper_left[1], lower_right[1], upper_right[1], lower_left[1]]

        return {
            'north': max(all_lats),
            'south': min(all_lats),
            'east': max(all_lons),
            'west': min(all_lons),
        }
    except Exception:
        return None


def build_kml(bounds):
    """Build KML XML for a ground overlay."""
    return f'''<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>MapSync Export</name>
    <GroundOverlay>
      <name>Georeferenced Aerial Photo</name>
      <Icon>
        <href>overlay.jpg</href>
      </Icon>
      <LatLonBox>
        <north>{bounds['north']}</north>
        <south>{bounds['south']}</south>
        <east>{bounds['east']}</east>
        <west>{bounds['west']}</west>
        <rotation>0</rotation>
      </LatLonBox>
    </GroundOverlay>
  </Document>
</kml>'''
