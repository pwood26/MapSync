import math
import time

import numpy as np
import requests
from PIL import Image
from io import BytesIO

ESRI_TILE_URL = (
    'https://server.arcgisonline.com/ArcGIS/rest/services/'
    'World_Imagery/MapServer/tile/{z}/{y}/{x}'
)
TILE_SIZE = 256
REQUEST_DELAY = 0.05  # 50ms between tile requests
MAX_RETRIES = 3
USER_AGENT = 'MapSync/1.0 (aerial-georeferencing)'


def download_reference_image(bounds, zoom=17):
    """Download and stitch Esri World Imagery tiles for a bounding box.

    Args:
        bounds: dict with 'north', 'south', 'east', 'west' (WGS84).
        zoom: tile zoom level (default 17 ≈ 1.2 m/px).

    Returns:
        dict with 'image' (numpy BGR array), 'geo_transform'
        (origin_lon, origin_lat, px_size_lon, px_size_lat),
        and 'bounds' (actual bounds of the tile grid).

    Raises:
        ValueError on invalid bounds or excessive tile count.
        RuntimeError if too many tiles fail to download.
    """
    north = bounds['north']
    south = bounds['south']
    east = bounds['east']
    west = bounds['west']

    # Tile indices for the bounding box corners
    x_min, y_min = _lat_lon_to_tile(north, west, zoom)
    x_max, y_max = _lat_lon_to_tile(south, east, zoom)

    num_tiles_x = x_max - x_min + 1
    num_tiles_y = y_max - y_min + 1
    total_tiles = num_tiles_x * num_tiles_y

    if total_tiles > 400:
        raise ValueError(
            f'Bounding box requires {total_tiles} tiles (max 400). '
            'Draw a smaller area.'
        )
    if total_tiles < 1:
        raise ValueError('Bounding box is too small or invalid.')

    # Download all tiles
    tiles = {}
    failures = 0

    for ty in range(y_min, y_max + 1):
        for tx in range(x_min, x_max + 1):
            tile_img = _download_tile(zoom, tx, ty)
            if tile_img is not None:
                tiles[(tx, ty)] = tile_img
            else:
                failures += 1
            time.sleep(REQUEST_DELAY)

    if failures > total_tiles * 0.2:
        raise RuntimeError(
            f'{failures} of {total_tiles} tiles failed to download. '
            'The tile server may be temporarily unavailable.'
        )

    # Stitch tiles into a single image
    img_width = num_tiles_x * TILE_SIZE
    img_height = num_tiles_y * TILE_SIZE
    stitched = np.zeros((img_height, img_width, 3), dtype=np.uint8)

    for ty in range(y_min, y_max + 1):
        for tx in range(x_min, x_max + 1):
            if (tx, ty) not in tiles:
                continue
            row = (ty - y_min) * TILE_SIZE
            col = (tx - x_min) * TILE_SIZE
            stitched[row:row + TILE_SIZE, col:col + TILE_SIZE] = tiles[(tx, ty)]

    # Compute geographic bounds of the stitched image
    actual_west, actual_north = _tile_to_lat_lon(x_min, y_min, zoom)
    actual_east, actual_south = _tile_to_lat_lon(x_max + 1, y_max + 1, zoom)

    px_size_lon = (actual_east - actual_west) / img_width
    px_size_lat = (actual_south - actual_north) / img_height  # negative

    return {
        'image': stitched,
        'geo_transform': (actual_west, actual_north, px_size_lon, px_size_lat),
        'bounds': {
            'north': actual_north,
            'south': actual_south,
            'east': actual_east,
            'west': actual_west,
        },
        'tile_count': total_tiles,
        'failures': failures,
    }


def _lat_lon_to_tile(lat, lon, zoom):
    """Convert WGS84 lat/lon to tile x/y indices."""
    n = 2 ** zoom
    x = int((lon + 180.0) / 360.0 * n)
    lat_rad = math.radians(lat)
    y = int((1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad))
             / math.pi) / 2.0 * n)
    x = max(0, min(n - 1, x))
    y = max(0, min(n - 1, y))
    return x, y


def _tile_to_lat_lon(x, y, zoom):
    """Convert tile x/y to the NW corner lon/lat."""
    n = 2 ** zoom
    lon = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1 - 2 * y / n)))
    lat = math.degrees(lat_rad)
    return lon, lat


def _download_tile(z, x, y):
    """Download a single tile, returning a numpy RGB array or None."""
    url = ESRI_TILE_URL.format(z=z, y=y, x=x)

    for attempt in range(MAX_RETRIES):
        try:
            resp = requests.get(
                url,
                headers={'User-Agent': USER_AGENT},
                timeout=10,
            )
            if resp.status_code == 200:
                img = Image.open(BytesIO(resp.content)).convert('RGB')
                return np.array(img)
            if resp.status_code == 404:
                # No imagery at this location/zoom
                return None
        except (requests.RequestException, Exception):
            pass

        if attempt < MAX_RETRIES - 1:
            time.sleep(0.5 * (attempt + 1))

    return None
