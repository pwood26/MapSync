from processing.tile_downloader import download_reference_image
from processing.vision_matcher import auto_match

MAX_SPAN = 0.5    # degrees – reject bounding boxes larger than ~50 km
MIN_SPAN = 0.001  # degrees – reject bounding boxes smaller than ~100 m


def run_auto_georeferencing(image_id, tiff_path, bounds):
    """Full automatic georeferencing pipeline.

    Args:
        image_id: UUID string for this upload.
        tiff_path: path to the uploaded TIFF on disk.
        bounds: dict with 'north', 'south', 'east', 'west'.

    Returns:
        dict with 'success', 'gcps', 'match_count', 'confidence',
        or 'error'.
    """
    # --- Validate bounds ---
    try:
        north = float(bounds['north'])
        south = float(bounds['south'])
        east = float(bounds['east'])
        west = float(bounds['west'])
    except (KeyError, TypeError, ValueError):
        return {'error': 'Invalid bounding box format.'}

    lat_span = north - south
    lon_span = east - west

    if lat_span <= 0 or lon_span <= 0:
        return {'error': 'Invalid bounding box (north must be > south, east must be > west).'}

    if lat_span > MAX_SPAN or lon_span > MAX_SPAN:
        return {
            'error': (
                'The selected area is too large '
                f'({lat_span:.3f}° × {lon_span:.3f}°, max {MAX_SPAN}°). '
                'Draw a tighter bounding box around the aerial photo area.'
            )
        }

    if lat_span < MIN_SPAN and lon_span < MIN_SPAN:
        return {
            'error': (
                'The selected area is too small. '
                'The bounding box should cover the approximate extent '
                'of the aerial photo.'
            )
        }

    # --- Step 1: Download satellite reference imagery ---
    try:
        ref = download_reference_image(bounds)
    except ValueError as e:
        return {'error': str(e)}
    except RuntimeError as e:
        return {'error': str(e)}
    except Exception as e:
        return {'error': f'Failed to download satellite imagery: {e}'}

    print(f'[auto_georeferencer] Reference imagery: zoom {ref.get("zoom")}, '
          f'{ref.get("tile_count")} tiles, '
          f'{ref.get("failures", 0)} failures')

    # --- Step 2: Feature matching ---
    try:
        result = auto_match(
            tiff_path,
            ref['image'],
            ref['geo_transform'],
        )
    except Exception as e:
        return {'error': f'Feature matching failed: {e}'}

    if 'error' in result:
        return result

    return {
        'success': True,
        'gcps': result['gcps'],
        'match_count': result['match_count'],
        'confidence': result['confidence'],
    }
