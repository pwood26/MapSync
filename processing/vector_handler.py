import json
import os
import subprocess
import tempfile

# Map of file extensions to format type
SUPPORTED_EXTENSIONS = {
    '.zip': 'shapefile',
    '.kmz': 'kmz',
    '.kml': 'kml',
    '.geojson': 'geojson',
    '.json': 'geojson',
    '.gpx': 'gpx',
    '.shp': 'shapefile',
}

# Formats that commonly have multiple internal layers
MULTI_LAYER_FORMATS = {'.gpx', '.kmz', '.kml'}


def convert_to_geojson(input_path, original_filename):
    """Convert a vector file to GeoJSON in EPSG:4326 using ogr2ogr.

    Handles multi-layer sources (GPX, KMZ) by listing layers,
    converting each one, and merging into a single FeatureCollection.

    Args:
        input_path: Path to the uploaded file on disk.
        original_filename: Original filename (used for extension detection).

    Returns:
        Dict with 'geojson' (parsed dict) and 'feature_count', or 'error'.
    """
    ext = os.path.splitext(original_filename)[1].lower()

    if ext not in SUPPORTED_EXTENSIONS:
        return {'error': f'Unsupported format: {ext}'}

    # For zipped shapefiles, use /vsizip/ virtual filesystem
    if ext == '.zip':
        source = f'/vsizip/{input_path}'
    else:
        source = input_path

    try:
        # First try a simple single-pass conversion
        result = _try_simple_convert(source)
        if result is not None:
            return result

        # If that failed, try multi-layer approach (list layers, convert each)
        return _try_multilayer_convert(source)

    except subprocess.TimeoutExpired:
        return {'error': 'Vector conversion timed out'}
    except FileNotFoundError:
        return {'error': 'GDAL/ogr2ogr not found. Install with: brew install gdal'}
    except json.JSONDecodeError:
        return {'error': 'Failed to parse converted GeoJSON output'}
    except Exception as e:
        return {'error': str(e)}


def _try_simple_convert(source):
    """Attempt a single-pass ogr2ogr conversion. Returns result dict or None on failure."""
    output_path = _make_temp_path()
    try:
        cmd = [
            'ogr2ogr',
            '-f', 'GeoJSON',
            '-t_srs', 'EPSG:4326',
            output_path,
            source,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

        if result.returncode != 0:
            return None  # Signal to try multi-layer approach

        with open(output_path, 'r') as f:
            geojson_data = json.load(f)

        feature_count = len(geojson_data.get('features', []))
        if feature_count == 0:
            return None

        return {
            'geojson': geojson_data,
            'feature_count': feature_count,
        }
    finally:
        if os.path.exists(output_path):
            os.remove(output_path)


def _try_multilayer_convert(source):
    """Handle multi-layer sources by listing layers and converting each one."""
    # List available layers
    result = subprocess.run(
        ['ogrinfo', '-so', '-al', source],
        capture_output=True, text=True, timeout=30
    )

    # Parse layer names from ogrinfo output
    layer_names = []
    for line in result.stdout.split('\n'):
        if line.startswith('Layer name: '):
            layer_names.append(line.split('Layer name: ')[1].strip())

    if not layer_names:
        return {'error': 'No layers found in the uploaded file'}

    # Convert each layer to GeoJSON and merge all features
    all_features = []
    for layer_name in layer_names:
        output_path = _make_temp_path()
        try:
            cmd = [
                'ogr2ogr',
                '-f', 'GeoJSON',
                '-t_srs', 'EPSG:4326',
                output_path,
                source,
                layer_name,
            ]
            lr = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if lr.returncode != 0:
                continue  # Skip layers that fail (e.g. empty layers)

            with open(output_path, 'r') as f:
                layer_geojson = json.load(f)

            features = layer_geojson.get('features', [])
            all_features.extend(features)
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    if not all_features:
        return {'error': 'No features found in any layer of the uploaded file'}

    merged = {
        'type': 'FeatureCollection',
        'features': all_features,
    }

    return {
        'geojson': merged,
        'feature_count': len(all_features),
    }


def _make_temp_path():
    """Create a temporary file path for GeoJSON output (file does not exist)."""
    fd, path = tempfile.mkstemp(suffix='.geojson')
    os.close(fd)
    os.remove(path)
    return path
