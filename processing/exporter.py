"""MapSync - KMZ export using pure Python.

Converts a georeferenced TIFF to KMZ (KML + JPEG in ZIP) using Pillow
instead of GDAL command-line tools. Reads bounding box from a sidecar
JSON file saved by the georeferencer.
"""

import json
import os
import tempfile
import zipfile

import numpy as np
from PIL import Image

# Allow large images
Image.MAX_IMAGE_PIXELS = 500_000_000


def generate_kmz(georef_tiff, kmz_path, rotation=0):
    """Generate a KMZ file from a georeferenced TIFF.

    The KMZ contains a KML ground overlay and a JPEG image,
    suitable for opening in Google Earth.

    Reads geographic bounds from a sidecar JSON file
    ({image_id}_georef_bounds.json) saved by the georeferencer.

    Args:
        georef_tiff: Path to the georeferenced TIFF.
        kmz_path: Output path for the KMZ file.
        rotation: Optional rotation in degrees for KML LatLonBox.

    Returns:
        Dict with 'success' and 'bounds', or 'error'.
    """
    try:
        # Step 1: Get bounding box from sidecar JSON
        bounds = _read_bounds(georef_tiff)
        if not bounds:
            return {'error': 'Could not find geographic bounds for the georeferenced image.'}

        # Step 2: Convert TIFF to JPEG, removing borders
        fd, jpeg_path = tempfile.mkstemp(suffix='.jpg')
        os.close(fd)

        try:
            crop_box = _tiff_to_jpeg(georef_tiff, jpeg_path)
        except Exception as e:
            return {'error': f'JPEG conversion failed: {e}'}

        # Step 2b: Adjust bounds if border was cropped
        if crop_box is not None:
            bounds = _adjust_bounds_for_crop(bounds, crop_box)

        # Step 3: Build KML (with optional rotation)
        kml_content = build_kml(bounds, rotation=rotation)

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
    """Convert a TIFF to JPEG, removing black borders and logo areas.

    Returns a crop_box tuple (left, top, right, bottom) as fractions
    of the original dimensions if cropping occurred, or None if no
    cropping was needed.
    """
    img = Image.open(tiff_path)
    orig_w, orig_h = img.size

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

    # Detect and remove borders
    crop_box = _find_content_bounds(img)
    if crop_box is not None:
        left, top, right, bottom = crop_box
        img = img.crop((left, top, right, bottom))
        # Convert to fractional box for bounds adjustment
        crop_box = (left / orig_w, top / orig_h, right / orig_w, bottom / orig_h)

    img.save(jpeg_path, 'JPEG', quality=quality)
    return crop_box


def _find_content_bounds(img):
    """Find the bounding box of actual map content, excluding borders.

    Detects black borders (from warping fill), white/grey borders
    (from scanning), and USGS logo bars. Returns (left, top, right, bottom)
    pixel coordinates, or None if no significant border detected.
    """
    arr = np.array(img)
    h, w = arr.shape[:2]

    # A pixel is "border" if it's very dark (black fill from warp)
    # or very bright and uniform (white scanning border / logo bar)
    grey = np.mean(arr, axis=2)

    # Content pixels are neither near-black nor near-white
    dark_thresh = 15
    bright_thresh = 245
    content_mask = (grey > dark_thresh) & (grey < bright_thresh)

    # Find rows and columns that have enough content pixels
    min_content_fraction = 0.05  # At least 5% of the row/col must be content

    row_content = np.mean(content_mask, axis=1)
    col_content = np.mean(content_mask, axis=0)

    content_rows = np.where(row_content > min_content_fraction)[0]
    content_cols = np.where(col_content > min_content_fraction)[0]

    if len(content_rows) == 0 or len(content_cols) == 0:
        return None

    top = int(content_rows[0])
    bottom = int(content_rows[-1]) + 1
    left = int(content_cols[0])
    right = int(content_cols[-1]) + 1

    # Only crop if we're removing a meaningful border (>1% on any side)
    margin = 0.01
    if (top < h * margin and bottom > h * (1 - margin) and
            left < w * margin and right > w * (1 - margin)):
        return None

    # Add a small padding (2px) to avoid cutting into content
    pad = 2
    top = max(0, top - pad)
    bottom = min(h, bottom + pad)
    left = max(0, left - pad)
    right = min(w, right + pad)

    return (left, top, right, bottom)


def _adjust_bounds_for_crop(bounds, crop_frac):
    """Adjust geographic bounds after cropping the image.

    crop_frac is (left, top, right, bottom) as fractions [0..1]
    of the original image dimensions.
    """
    frac_left, frac_top, frac_right, frac_bottom = crop_frac

    lon_span = bounds['east'] - bounds['west']
    lat_span = bounds['north'] - bounds['south']

    return {
        'west': bounds['west'] + frac_left * lon_span,
        'east': bounds['west'] + frac_right * lon_span,
        'north': bounds['north'] - frac_top * lat_span,
        'south': bounds['north'] - frac_bottom * lat_span,
    }


def build_kml(bounds, rotation=0):
    """Build KML XML for a ground overlay.

    Args:
        bounds: Dict with north, south, east, west.
        rotation: Rotation angle in degrees (counter-clockwise).
    """
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
        <rotation>{rotation}</rotation>
      </LatLonBox>
    </GroundOverlay>
  </Document>
</kml>'''
