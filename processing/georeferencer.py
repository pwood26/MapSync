"""MapSync - Pure Python georeferencing pipeline.

Uses numpy least-squares affine fitting + OpenCV warp instead of GDAL.
No external command-line dependencies required.
"""

import json
import math
import os

import cv2
import numpy as np
from PIL import Image

# Allow large USGS aerial frames
Image.MAX_IMAGE_PIXELS = 500_000_000


def run_georeferencing(input_tiff, output_tiff, gcps):
    """Run georeferencing pipeline using affine transformation.

    Fits an affine transform from pixel coordinates to geographic
    coordinates using the provided GCPs, warps the image to an
    axis-aligned geographic rectangle, and saves the result.

    Args:
        input_tiff: Path to the original TIFF file.
        output_tiff: Path for the georeferenced output TIFF.
        gcps: List of dicts with keys: pixel_x, pixel_y, lat, lon.

    Returns:
        Dict with 'success', 'residuals', 'rms_error', 'bounds',
        or 'error'.
    """
    if len(gcps) < 5:
        return {'error': 'At least 5 GCPs are required for georeferencing.'}

    try:
        # Step 1: Compute affine transform from GCPs
        affine = _compute_affine(gcps)
        if affine is None:
            return {'error': 'Could not compute affine transform from GCPs.'}

        # Step 2: Compute geographic bounds of the warped image
        img = Image.open(input_tiff)
        orig_w, orig_h = img.size
        img.close()

        bounds = _compute_bounds(orig_w, orig_h, affine)
        if bounds is None:
            return {'error': 'Could not compute geographic bounds.'}

        # Step 3: Warp the image
        _warp_image(input_tiff, output_tiff, affine, bounds)

        # Step 4: Save bounds as sidecar JSON for the exporter
        bounds_path = output_tiff.replace('.tiff', '_bounds.json').replace('.tif', '_bounds.json')
        with open(bounds_path, 'w') as f:
            json.dump(bounds, f)

        # Step 5: Compute residuals
        residuals = _compute_residuals(affine, gcps)

        print(f'[georeferencer] Affine georeferencing complete: '
              f'RMS={residuals["rms"]:.1f}m, '
              f'bounds=N{bounds["north"]:.4f} S{bounds["south"]:.4f} '
              f'E{bounds["east"]:.4f} W{bounds["west"]:.4f}')

        return {
            'success': True,
            'residuals': residuals['per_point'],
            'rms_error': residuals['rms'],
            'bounds': bounds,
        }

    except Exception as e:
        return {'error': f'Georeferencing failed: {e}'}


def _compute_affine(gcps):
    """Fit a 6-parameter affine transform: pixel (x,y) → geographic (lon,lat).

    Solves the least-squares system:
        lon = a0 + a1*px + a2*py
        lat = b0 + b1*px + b2*py

    Returns dict with 'lon_coeffs' [a0, a1, a2] and 'lat_coeffs' [b0, b1, b2],
    or None if the system is singular.
    """
    n = len(gcps)
    # Build the design matrix: [1, pixel_x, pixel_y]
    A = np.zeros((n, 3))
    lon_vec = np.zeros(n)
    lat_vec = np.zeros(n)

    for i, gcp in enumerate(gcps):
        A[i] = [1.0, gcp['pixel_x'], gcp['pixel_y']]
        lon_vec[i] = gcp['lon']
        lat_vec[i] = gcp['lat']

    try:
        lon_coeffs, _, _, _ = np.linalg.lstsq(A, lon_vec, rcond=None)
        lat_coeffs, _, _, _ = np.linalg.lstsq(A, lat_vec, rcond=None)
    except np.linalg.LinAlgError:
        return None

    return {
        'lon_coeffs': lon_coeffs.tolist(),  # [a0, a1, a2]
        'lat_coeffs': lat_coeffs.tolist(),  # [b0, b1, b2]
    }


def _pixel_to_geo(px, py, affine):
    """Convert pixel coordinates to geographic coordinates using affine."""
    a0, a1, a2 = affine['lon_coeffs']
    b0, b1, b2 = affine['lat_coeffs']
    lon = a0 + a1 * px + a2 * py
    lat = b0 + b1 * px + b2 * py
    return lon, lat


def _compute_bounds(width, height, affine):
    """Compute geographic bounding box of the image after affine transform.

    Transforms all four corners and takes the min/max lat/lon.
    """
    corners_px = [
        (0, 0),               # top-left
        (width, 0),           # top-right
        (width, height),      # bottom-right
        (0, height),          # bottom-left
    ]

    lons = []
    lats = []
    for px, py in corners_px:
        lon, lat = _pixel_to_geo(px, py, affine)
        lons.append(lon)
        lats.append(lat)

    return {
        'north': max(lats),
        'south': min(lats),
        'east': max(lons),
        'west': min(lons),
    }


def _warp_image(input_tiff, output_tiff, affine, bounds):
    """Warp the image to an axis-aligned geographic rectangle.

    The output image covers the bounding box, with each pixel
    mapped back to the source image via the inverse affine transform.
    """
    # Load source image
    src_img = Image.open(input_tiff)
    if src_img.mode not in ('RGB', 'RGBA'):
        try:
            src_img = src_img.convert('RGB')
        except Exception:
            src_img = src_img.convert('L').convert('RGB')

    src_w, src_h = src_img.size
    src_arr = np.array(src_img)

    # Determine output dimensions
    # Use similar pixel density as the input (preserve resolution roughly)
    a1 = affine['lon_coeffs'][1]  # degrees per pixel in x
    a2 = affine['lon_coeffs'][2]  # degrees per pixel in y
    b1 = affine['lat_coeffs'][1]
    b2 = affine['lat_coeffs'][2]

    # Approximate pixel size in degrees
    px_size_deg = math.sqrt(a1**2 + b1**2)
    if px_size_deg == 0:
        px_size_deg = 1e-6  # guard against zero

    lon_span = bounds['east'] - bounds['west']
    lat_span = bounds['north'] - bounds['south']

    out_w = max(100, min(8000, int(lon_span / px_size_deg)))
    out_h = max(100, min(8000, int(lat_span / px_size_deg)))

    # Build inverse mapping: for each output pixel, find source pixel
    # Output pixel (ox, oy) maps to geographic:
    #   lon = west + ox * (lon_span / out_w)
    #   lat = north - oy * (lat_span / out_h)  # Y flipped: top=north
    #
    # Then invert the affine to get source pixel:
    #   [1, px, py] → [lon, lat]  means  A * [1, px, py]^T = [lon, lat]^T
    #   We need to invert: given lon, lat, find px, py

    # Forward affine matrix (2x3):
    # [lon] = [a0 + a1*px + a2*py]
    # [lat] = [b0 + b1*px + b2*py]
    #
    # In matrix form: [lon - a0] = [[a1, a2]] * [px]
    #                 [lat - b0]   [[b1, b2]]   [py]

    a0 = affine['lon_coeffs'][0]
    b0 = affine['lat_coeffs'][0]

    M_fwd = np.array([
        [a1, a2],
        [b1, b2],
    ])

    try:
        M_inv = np.linalg.inv(M_fwd)
    except np.linalg.LinAlgError:
        # Singular matrix — fallback: just save the original image
        src_img.save(output_tiff, 'TIFF')
        return

    # Build coordinate grids for the output image
    ox = np.arange(out_w)
    oy = np.arange(out_h)
    ox_grid, oy_grid = np.meshgrid(ox, oy)

    # Output pixel → geographic coordinates
    lon_grid = bounds['west'] + ox_grid * (lon_span / out_w)
    lat_grid = bounds['north'] - oy_grid * (lat_span / out_h)

    # Geographic → source pixel (using inverse affine)
    dlon = lon_grid - a0
    dlat = lat_grid - b0

    src_px_x = M_inv[0, 0] * dlon + M_inv[0, 1] * dlat
    src_px_y = M_inv[1, 0] * dlon + M_inv[1, 1] * dlat

    # Remap using OpenCV (float32 maps)
    map_x = src_px_x.astype(np.float32)
    map_y = src_px_y.astype(np.float32)

    warped = cv2.remap(
        src_arr, map_x, map_y,
        interpolation=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(0, 0, 0),
    )

    # Save output
    out_img = Image.fromarray(warped)
    out_img.save(output_tiff, 'TIFF', compression='tiff_lzw')


def _compute_residuals(affine, gcps):
    """Compute residual errors for each GCP.

    For each GCP, predicts the geographic coordinate from its pixel
    position using the affine transform, then computes the Haversine
    distance to the actual GCP coordinate.
    """
    per_point = []
    sum_sq = 0

    for gcp in gcps:
        pred_lon, pred_lat = _pixel_to_geo(
            gcp['pixel_x'], gcp['pixel_y'], affine
        )
        error_m = haversine(gcp['lat'], gcp['lon'], pred_lat, pred_lon)
        per_point.append({
            'gcp_id': gcp.get('id', len(per_point) + 1),
            'error_m': round(error_m, 1),
        })
        sum_sq += error_m ** 2

    rms = math.sqrt(sum_sq / len(gcps)) if gcps else 0

    return {
        'per_point': per_point,
        'rms': round(rms, 1),
    }


def haversine(lat1, lon1, lat2, lon2):
    """Compute the great-circle distance between two points in meters."""
    R = 6371000  # Earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
