import json
import math
import os
import subprocess
import tempfile


def run_georeferencing(input_tiff, output_tiff, gcps):
    """Run GDAL georeferencing pipeline.

    Args:
        input_tiff: Path to the original TIFF file.
        output_tiff: Path for the georeferenced output GeoTIFF.
        gcps: List of dicts with keys: pixel_x, pixel_y, lat, lon.

    Returns:
        Dict with 'success', 'residuals', 'rms_error', or 'error'.
    """
    try:
        # Step 1: Embed GCPs into a temporary TIFF using gdal_translate
        with tempfile.NamedTemporaryFile(suffix='.tiff', delete=False) as tmp:
            tmp_with_gcps = tmp.name

        cmd_translate = ['gdal_translate', '-of', 'GTiff']
        for gcp in gcps:
            cmd_translate.extend([
                '-gcp',
                str(gcp['pixel_x']),
                str(gcp['pixel_y']),
                str(gcp['lon']),
                str(gcp['lat']),
            ])
        cmd_translate.extend(['-a_srs', 'EPSG:4326'])
        cmd_translate.extend([input_tiff, tmp_with_gcps])

        result = subprocess.run(
            cmd_translate, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            return {'error': f'gdal_translate failed: {result.stderr}'}

        # Step 2: Warp the image using gdalwarp with thin plate spline
        cmd_warp = [
            'gdalwarp',
            '-r', 'bilinear',
            '-tps',
            '-t_srs', 'EPSG:4326',
            '-co', 'COMPRESS=LZW',
            '-overwrite',
            tmp_with_gcps,
            output_tiff,
        ]

        result = subprocess.run(
            cmd_warp, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            return {'error': f'gdalwarp failed: {result.stderr}'}

        # Step 3: Compute residuals by reading back the geotransform
        residuals = compute_residuals(output_tiff, gcps)

        return {
            'success': True,
            'residuals': residuals['per_point'],
            'rms_error': residuals['rms'],
        }

    except subprocess.TimeoutExpired:
        return {'error': 'GDAL processing timed out'}
    except FileNotFoundError:
        return {
            'error': 'GDAL not found. Install with: brew install gdal'
        }
    except Exception as e:
        return {'error': str(e)}
    finally:
        # Clean up temp file
        if 'tmp_with_gcps' in locals() and os.path.exists(tmp_with_gcps):
            os.remove(tmp_with_gcps)


def compute_residuals(georef_tiff, gcps):
    """Compute residual errors for each GCP after georeferencing.

    Uses gdalinfo to read the geotransform, then for each GCP computes
    the predicted geographic coordinate from its pixel position and
    compares against the user-supplied coordinate.
    """
    try:
        result = subprocess.run(
            ['gdalinfo', '-json', georef_tiff],
            capture_output=True, text=True, timeout=30
        )
        if result.returncode != 0:
            return {'per_point': [], 'rms': 0}

        info = json.loads(result.stdout)

        # Get geotransform: [origin_x, pixel_width, 0, origin_y, 0, pixel_height]
        gt = info.get('geoTransform')
        if not gt:
            return {'per_point': [], 'rms': 0}

        per_point = []
        sum_sq = 0

        for gcp in gcps:
            # Apply geotransform to predict geographic coords from pixel coords
            pred_lon = gt[0] + gcp['pixel_x'] * gt[1] + gcp['pixel_y'] * gt[2]
            pred_lat = gt[3] + gcp['pixel_x'] * gt[4] + gcp['pixel_y'] * gt[5]

            # Haversine distance in meters
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
    except Exception:
        return {'per_point': [], 'rms': 0}


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
