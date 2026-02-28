"""MapSync - Pure Python georeferencing pipeline.

Uses numpy least-squares affine fitting + OpenCV warp instead of GDAL.
For 10+ GCPs, uses scipy thin-plate spline (TPS) for better accuracy
with lens distortion and oblique angles.
No external command-line dependencies required.
"""

import json
import math
import os

import cv2
import numpy as np
from PIL import Image

import processing.config  # noqa: F401 — sets Image.MAX_IMAGE_PIXELS

try:
    from scipy.interpolate import RBFInterpolator
    _HAS_SCIPY = True
except ImportError:
    _HAS_SCIPY = False

TPS_MIN_GCPS = 10  # use TPS when this many GCPs are available


def run_georeferencing(input_tiff, output_tiff, gcps):
    """Run georeferencing pipeline.

    Automatically selects thin-plate spline (TPS) when >= 10 GCPs are
    provided, otherwise uses affine (6-parameter least-squares).

    Args:
        input_tiff: Path to the original TIFF file.
        output_tiff: Path for the georeferenced output TIFF.
        gcps: List of dicts with keys: pixel_x, pixel_y, lat, lon.

    Returns:
        Dict with 'success', 'residuals', 'rms_error', 'bounds',
        'transform_type', or 'error'.
    """
    if len(gcps) < 5:
        return {'error': 'At least 5 GCPs are required for georeferencing.'}

    use_tps = len(gcps) >= TPS_MIN_GCPS and _HAS_SCIPY

    try:
        img = Image.open(input_tiff)
        orig_w, orig_h = img.size
        img.close()

        if use_tps:
            result = _run_tps(input_tiff, output_tiff, gcps, orig_w, orig_h)
        else:
            result = _run_affine(input_tiff, output_tiff, gcps, orig_w, orig_h)

        return result

    except Exception as e:
        return {'error': f'Georeferencing failed: {e}'}


# ─── Affine pipeline ───────────────────────────────────────────────

def _run_affine(input_tiff, output_tiff, gcps, orig_w, orig_h):
    affine = _compute_affine(gcps)
    if affine is None:
        return {'error': 'Could not compute affine transform from GCPs.'}

    bounds = _compute_bounds_affine(orig_w, orig_h, affine)
    if bounds is None:
        return {'error': 'Could not compute geographic bounds.'}

    _warp_image_affine(input_tiff, output_tiff, affine, bounds)
    _save_bounds(output_tiff, bounds)

    residuals = _compute_residuals_affine(affine, gcps)

    print(f'[georeferencer] Affine georeferencing complete: '
          f'RMS={residuals["rms"]:.1f}m, '
          f'bounds=N{bounds["north"]:.4f} S{bounds["south"]:.4f} '
          f'E{bounds["east"]:.4f} W{bounds["west"]:.4f}')

    return {
        'success': True,
        'residuals': residuals['per_point'],
        'rms_error': residuals['rms'],
        'bounds': bounds,
        'transform_type': 'affine',
    }


def _compute_affine(gcps):
    """Fit a 6-parameter affine transform: pixel (x,y) -> geographic (lon,lat)."""
    n = len(gcps)
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
        'lon_coeffs': lon_coeffs.tolist(),
        'lat_coeffs': lat_coeffs.tolist(),
    }


def _pixel_to_geo_affine(px, py, affine):
    a0, a1, a2 = affine['lon_coeffs']
    b0, b1, b2 = affine['lat_coeffs']
    lon = a0 + a1 * px + a2 * py
    lat = b0 + b1 * px + b2 * py
    return lon, lat


def _compute_bounds_affine(width, height, affine):
    corners_px = [(0, 0), (width, 0), (width, height), (0, height)]
    lons, lats = [], []
    for px, py in corners_px:
        lon, lat = _pixel_to_geo_affine(px, py, affine)
        lons.append(lon)
        lats.append(lat)
    return {
        'north': max(lats), 'south': min(lats),
        'east': max(lons), 'west': min(lons),
    }


def _warp_image_affine(input_tiff, output_tiff, affine, bounds):
    src_img = Image.open(input_tiff)
    if src_img.mode not in ('RGB', 'RGBA'):
        try:
            src_img = src_img.convert('RGB')
        except Exception:
            src_img = src_img.convert('L').convert('RGB')

    src_arr = np.array(src_img)

    a1 = affine['lon_coeffs'][1]
    b1 = affine['lat_coeffs'][1]
    px_size_deg = math.sqrt(a1**2 + b1**2)
    if px_size_deg == 0:
        px_size_deg = 1e-6

    lon_span = bounds['east'] - bounds['west']
    lat_span = bounds['north'] - bounds['south']
    out_w = max(100, min(8000, int(lon_span / px_size_deg)))
    out_h = max(100, min(8000, int(lat_span / px_size_deg)))

    a0 = affine['lon_coeffs'][0]
    a2 = affine['lon_coeffs'][2]
    b0 = affine['lat_coeffs'][0]
    b2 = affine['lat_coeffs'][2]

    M_fwd = np.array([[a1, a2], [b1, b2]])
    try:
        M_inv = np.linalg.inv(M_fwd)
    except np.linalg.LinAlgError:
        src_img.save(output_tiff, 'TIFF')
        return

    ox_grid, oy_grid = np.meshgrid(np.arange(out_w), np.arange(out_h))
    lon_grid = bounds['west'] + ox_grid * (lon_span / out_w)
    lat_grid = bounds['north'] - oy_grid * (lat_span / out_h)

    dlon = lon_grid - a0
    dlat = lat_grid - b0
    map_x = (M_inv[0, 0] * dlon + M_inv[0, 1] * dlat).astype(np.float32)
    map_y = (M_inv[1, 0] * dlon + M_inv[1, 1] * dlat).astype(np.float32)

    warped = cv2.remap(src_arr, map_x, map_y,
                       interpolation=cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_CONSTANT,
                       borderValue=(0, 0, 0))

    Image.fromarray(warped).save(output_tiff, 'TIFF', compression='tiff_lzw')


def _compute_residuals_affine(affine, gcps):
    per_point = []
    sum_sq = 0
    for gcp in gcps:
        pred_lon, pred_lat = _pixel_to_geo_affine(gcp['pixel_x'], gcp['pixel_y'], affine)
        error_m = haversine(gcp['lat'], gcp['lon'], pred_lat, pred_lon)
        per_point.append({
            'gcp_id': gcp.get('id', len(per_point) + 1),
            'error_m': round(error_m, 1),
        })
        sum_sq += error_m ** 2
    rms = math.sqrt(sum_sq / len(gcps)) if gcps else 0
    return {'per_point': per_point, 'rms': round(rms, 1)}


# ─── TPS (thin-plate spline) pipeline ──────────────────────────────

def _run_tps(input_tiff, output_tiff, gcps, orig_w, orig_h):
    # Build forward (pixel → geo) and inverse (geo → pixel) interpolators
    px_coords = np.array([[g['pixel_x'], g['pixel_y']] for g in gcps])
    geo_coords = np.array([[g['lon'], g['lat']] for g in gcps])

    # Forward: pixel → geo (for bounds computation and residuals)
    fwd_lon = RBFInterpolator(px_coords, geo_coords[:, 0], kernel='thin_plate_spline')
    fwd_lat = RBFInterpolator(px_coords, geo_coords[:, 1], kernel='thin_plate_spline')

    # Inverse: geo → pixel (for image warping)
    inv_px = RBFInterpolator(geo_coords, px_coords[:, 0], kernel='thin_plate_spline')
    inv_py = RBFInterpolator(geo_coords, px_coords[:, 1], kernel='thin_plate_spline')

    tps = {
        'fwd_lon': fwd_lon, 'fwd_lat': fwd_lat,
        'inv_px': inv_px, 'inv_py': inv_py,
    }

    # Compute bounds from image corners + edge midpoints for better coverage
    sample_pts = [
        (0, 0), (orig_w, 0), (orig_w, orig_h), (0, orig_h),
        (orig_w / 2, 0), (orig_w, orig_h / 2),
        (orig_w / 2, orig_h), (0, orig_h / 2),
    ]
    pts = np.array(sample_pts)
    lons = fwd_lon(pts)
    lats = fwd_lat(pts)
    bounds = {
        'north': float(np.max(lats)), 'south': float(np.min(lats)),
        'east': float(np.max(lons)), 'west': float(np.min(lons)),
    }

    # Estimate pixel size from affine (for output dimensions)
    affine = _compute_affine(gcps)
    a1 = affine['lon_coeffs'][1] if affine else 1e-6
    b1 = affine['lat_coeffs'][1] if affine else 1e-6
    px_size_deg = math.sqrt(a1**2 + b1**2)
    if px_size_deg == 0:
        px_size_deg = 1e-6

    _warp_image_tps(input_tiff, output_tiff, tps, bounds, px_size_deg)
    _save_bounds(output_tiff, bounds)

    residuals = _compute_residuals_tps(tps, gcps)

    print(f'[georeferencer] TPS georeferencing complete ({len(gcps)} GCPs): '
          f'RMS={residuals["rms"]:.1f}m, '
          f'bounds=N{bounds["north"]:.4f} S{bounds["south"]:.4f} '
          f'E{bounds["east"]:.4f} W{bounds["west"]:.4f}')

    return {
        'success': True,
        'residuals': residuals['per_point'],
        'rms_error': residuals['rms'],
        'bounds': bounds,
        'transform_type': 'tps',
    }


def _warp_image_tps(input_tiff, output_tiff, tps, bounds, px_size_deg):
    src_img = Image.open(input_tiff)
    if src_img.mode not in ('RGB', 'RGBA'):
        try:
            src_img = src_img.convert('RGB')
        except Exception:
            src_img = src_img.convert('L').convert('RGB')

    src_arr = np.array(src_img)

    lon_span = bounds['east'] - bounds['west']
    lat_span = bounds['north'] - bounds['south']
    out_w = max(100, min(8000, int(lon_span / px_size_deg)))
    out_h = max(100, min(8000, int(lat_span / px_size_deg)))

    ox_grid, oy_grid = np.meshgrid(np.arange(out_w), np.arange(out_h))
    lon_grid = bounds['west'] + ox_grid * (lon_span / out_w)
    lat_grid = bounds['north'] - oy_grid * (lat_span / out_h)

    # Flatten for RBF evaluation, then reshape
    geo_flat = np.column_stack([lon_grid.ravel(), lat_grid.ravel()])
    src_x = tps['inv_px'](geo_flat).reshape(out_h, out_w).astype(np.float32)
    src_y = tps['inv_py'](geo_flat).reshape(out_h, out_w).astype(np.float32)

    warped = cv2.remap(src_arr, src_x, src_y,
                       interpolation=cv2.INTER_LINEAR,
                       borderMode=cv2.BORDER_CONSTANT,
                       borderValue=(0, 0, 0))

    Image.fromarray(warped).save(output_tiff, 'TIFF', compression='tiff_lzw')


def _compute_residuals_tps(tps, gcps):
    per_point = []
    sum_sq = 0
    px_coords = np.array([[g['pixel_x'], g['pixel_y']] for g in gcps])
    pred_lons = tps['fwd_lon'](px_coords)
    pred_lats = tps['fwd_lat'](px_coords)

    for i, gcp in enumerate(gcps):
        error_m = haversine(gcp['lat'], gcp['lon'], float(pred_lats[i]), float(pred_lons[i]))
        per_point.append({
            'gcp_id': gcp.get('id', i + 1),
            'error_m': round(error_m, 1),
        })
        sum_sq += error_m ** 2

    rms = math.sqrt(sum_sq / len(gcps)) if gcps else 0
    return {'per_point': per_point, 'rms': round(rms, 1)}


# ─── Shared helpers ─────────────────────────────────────────────────

def _save_bounds(output_tiff, bounds):
    bounds_path = output_tiff.replace('.tiff', '_bounds.json').replace('.tif', '_bounds.json')
    with open(bounds_path, 'w') as f:
        json.dump(bounds, f)


def haversine(lat1, lon1, lat2, lon2):
    """Compute the great-circle distance between two points in meters."""
    R = 6371000
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
