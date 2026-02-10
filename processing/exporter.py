"""MapSync - KMZ export using pure Python.

Converts a georeferenced TIFF to KMZ (KML + JPEG in ZIP) using Pillow
instead of GDAL command-line tools. Reads bounding box from a sidecar
JSON file saved by the georeferencer.
"""

import json
import os
import tempfile
import zipfile

from PIL import Image

# Allow large images
Image.MAX_IMAGE_PIXELS = 500_000_000


def generate_kmz(georef_tiff, kmz_path):
    """Generate a KMZ file from a georeferenced TIFF.

    The KMZ contains a KML ground overlay and a JPEG image,
    suitable for opening in Google Earth.

    Reads geographic bounds from a sidecar JSON file
    ({image_id}_georef_bounds.json) saved by the georeferencer.

    Returns:
        Dict with 'success' and 'bounds', or 'error'.
    """
    try:
        # Step 1: Get bounding box from sidecar JSON
        bounds = _read_bounds(georef_tiff)
        if not bounds:
            return {'error': 'Could not find geographic bounds for the georeferenced image.'}

        # Step 2: Convert TIFF to JPEG using Pillow
        fd, jpeg_path = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)

        try:
            _tiff_to_jpeg(georef_tiff, jpeg_path)
        except Exception as e:
            return {'error': f'JPEG conversion failed: {e}'}

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

    except Exception as e:
        return {'error': str(e)}
    finally:
        if 'jpeg_path' in locals() and os.path.exists(jpeg_path):
            os.remove(jpeg_path)


def _read_bounds(georef_tiff):
    """Read geographic bounds from the sidecar JSON file."""
    # Try common naming patterns
    for suffix in ['_bounds.json']:
        bounds_path = georef_tiff.replace('.tiff', suffix).replace('.tif', suffix)
        if os.path.exists(bounds_path):
            try:
                with open(bounds_path, 'r') as f:
                    bounds = json.load(f)
                if all(k in bounds for k in ('north', 'south', 'east', 'west')):
                    return bounds
            except (json.JSONDecodeError, KeyError):
                continue

    return None


def _tiff_to_jpeg(tiff_path, jpeg_path, quality=85):
    """Convert a TIFF to JPEG using Pillow."""
    img = Image.open(tiff_path)

    # Handle various modes
    if img.mode == 'RGBA':
        # Composite onto white background
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != 'RGB':
        try:
            img = img.convert('RGB')
        except Exception:
            img = img.convert('L').convert('RGB')

    img.save(jpeg_path, 'JPEG', quality=quality)


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
