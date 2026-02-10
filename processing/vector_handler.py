import json
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

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

# Formats we can handle in pure Python (no GDAL needed)
PYTHON_NATIVE_FORMATS = {'.kmz', '.kml', '.geojson', '.json'}

# Formats that commonly have multiple internal layers
MULTI_LAYER_FORMATS = {'.gpx', '.kmz', '.kml'}


def convert_to_geojson(input_path, original_filename):
    """Convert a vector file to GeoJSON in EPSG:4326.

    Tries Python-native conversion first for KMZ/KML/GeoJSON,
    falls back to ogr2ogr (GDAL) for shapefiles and other formats.

    Args:
        input_path: Path to the uploaded file on disk.
        original_filename: Original filename (used for extension detection).

    Returns:
        Dict with 'geojson' (parsed dict) and 'feature_count', or 'error'.
    """
    ext = os.path.splitext(original_filename)[1].lower()

    if ext not in SUPPORTED_EXTENSIONS:
        return {'error': f'Unsupported format: {ext}'}

    # Try Python-native conversion for supported formats
    if ext in PYTHON_NATIVE_FORMATS:
        try:
            result = _convert_native(input_path, ext)
            if result is not None:
                return result
        except Exception as e:
            print(f'[vector_handler] Native conversion failed for {ext}: {e}')
            # Fall through to ogr2ogr

    # Fall back to ogr2ogr for shapefiles and anything native couldn't handle
    return _convert_with_ogr2ogr(input_path, ext)


def _convert_native(input_path, ext):
    """Convert KMZ/KML/GeoJSON using pure Python. Returns result dict or None."""
    if ext == '.kmz':
        return _convert_kmz(input_path)
    elif ext == '.kml':
        with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
            kml_text = f.read()
        return _convert_kml_text(kml_text)
    elif ext in ('.geojson', '.json'):
        return _convert_geojson_file(input_path)
    return None


# ============================================================
# KMZ / KML conversion (pure Python)
# ============================================================

def _convert_kmz(input_path):
    """Extract KML from a KMZ (ZIP) archive and convert to GeoJSON."""
    try:
        with zipfile.ZipFile(input_path, 'r') as zf:
            kml_names = [n for n in zf.namelist()
                         if n.lower().endswith('.kml')]
            if not kml_names:
                return {'error': 'No KML file found inside KMZ archive'}

            all_features = []
            for kml_name in kml_names:
                kml_text = zf.read(kml_name).decode('utf-8', errors='replace')
                result = _convert_kml_text(kml_text)
                if result and 'geojson' in result:
                    all_features.extend(
                        result['geojson'].get('features', [])
                    )

            if not all_features:
                return {'error': 'No geographic features found in KMZ'}

            geojson = {
                'type': 'FeatureCollection',
                'features': all_features,
            }
            return {
                'geojson': geojson,
                'feature_count': len(all_features),
            }

    except zipfile.BadZipFile:
        return {'error': 'Invalid KMZ file (not a valid ZIP archive)'}


def _convert_kml_text(kml_text):
    """Parse KML XML text and convert placemarks to GeoJSON."""
    try:
        root = ET.fromstring(kml_text)
    except ET.ParseError as e:
        return {'error': f'Failed to parse KML: {e}'}

    # KML namespace
    ns = ''
    tag = root.tag
    if tag.startswith('{'):
        ns = tag[1:tag.index('}')]

    def ns_tag(local):
        return f'{{{ns}}}{local}' if ns else local

    features = []

    # Find all Placemark elements (recursively)
    for pm in root.iter(ns_tag('Placemark')):
        feature = _placemark_to_feature(pm, ns_tag)
        if feature is not None:
            features.append(feature)

    if not features:
        return None  # Signal to try ogr2ogr fallback

    geojson = {
        'type': 'FeatureCollection',
        'features': features,
    }
    return {
        'geojson': geojson,
        'feature_count': len(features),
    }


def _placemark_to_feature(pm, ns_tag):
    """Convert a single KML Placemark to a GeoJSON Feature."""
    properties = {}

    # Name
    name_el = pm.find(ns_tag('name'))
    if name_el is not None and name_el.text:
        properties['name'] = name_el.text.strip()

    # Description
    desc_el = pm.find(ns_tag('description'))
    if desc_el is not None and desc_el.text:
        properties['description'] = desc_el.text.strip()

    # ExtendedData / SimpleData
    ext_data = pm.find(ns_tag('ExtendedData'))
    if ext_data is not None:
        for sd in ext_data.iter(ns_tag('SimpleData')):
            attr_name = sd.get('name', '')
            if attr_name and sd.text:
                properties[attr_name] = sd.text.strip()
        # Also handle Data elements
        for data_el in ext_data.iter(ns_tag('Data')):
            attr_name = data_el.get('name', '')
            value_el = data_el.find(ns_tag('value'))
            if attr_name and value_el is not None and value_el.text:
                properties[attr_name] = value_el.text.strip()

    # Geometry
    geometry = _extract_geometry(pm, ns_tag)
    if geometry is None:
        return None

    return {
        'type': 'Feature',
        'properties': properties,
        'geometry': geometry,
    }


def _extract_geometry(pm, ns_tag):
    """Extract GeoJSON geometry from a Placemark element."""
    # Point
    point = pm.find('.//' + ns_tag('Point'))
    if point is not None:
        coords = point.find(ns_tag('coordinates'))
        if coords is not None and coords.text:
            parts = coords.text.strip().split(',')
            if len(parts) >= 2:
                lon, lat = float(parts[0]), float(parts[1])
                return {'type': 'Point', 'coordinates': [lon, lat]}

    # LineString
    line = pm.find('.//' + ns_tag('LineString'))
    if line is not None:
        coords_el = line.find(ns_tag('coordinates'))
        if coords_el is not None and coords_el.text:
            coords = _parse_coord_string(coords_el.text)
            if coords:
                return {'type': 'LineString', 'coordinates': coords}

    # Polygon
    polygon = pm.find('.//' + ns_tag('Polygon'))
    if polygon is not None:
        return _parse_polygon(polygon, ns_tag)

    # MultiGeometry
    multi = pm.find('.//' + ns_tag('MultiGeometry'))
    if multi is not None:
        geometries = []
        for child_pm_type in ['Point', 'LineString', 'Polygon']:
            for child in multi.findall(ns_tag(child_pm_type)):
                # Create a temporary wrapper to reuse extraction
                wrapper = ET.Element('tmp')
                wrapper.append(child)
                geom = _extract_geometry(wrapper, ns_tag)
                if geom:
                    geometries.append(geom)
        if geometries:
            return {
                'type': 'GeometryCollection',
                'geometries': geometries,
            }

    return None


def _parse_polygon(polygon_el, ns_tag):
    """Parse a KML Polygon into GeoJSON Polygon geometry."""
    rings = []

    # Outer boundary
    outer = polygon_el.find(ns_tag('outerBoundaryIs'))
    if outer is not None:
        lr = outer.find(ns_tag('LinearRing'))
        if lr is not None:
            coords_el = lr.find(ns_tag('coordinates'))
            if coords_el is not None and coords_el.text:
                coords = _parse_coord_string(coords_el.text)
                if coords:
                    rings.append(coords)

    # Inner boundaries (holes)
    for inner in polygon_el.findall(ns_tag('innerBoundaryIs')):
        lr = inner.find(ns_tag('LinearRing'))
        if lr is not None:
            coords_el = lr.find(ns_tag('coordinates'))
            if coords_el is not None and coords_el.text:
                coords = _parse_coord_string(coords_el.text)
                if coords:
                    rings.append(coords)

    if not rings:
        return None

    return {'type': 'Polygon', 'coordinates': rings}


def _parse_coord_string(text):
    """Parse KML coordinate string 'lon,lat[,alt] lon,lat[,alt] ...' to list of [lon, lat]."""
    coords = []
    for token in text.strip().split():
        parts = token.strip().split(',')
        if len(parts) >= 2:
            try:
                lon, lat = float(parts[0]), float(parts[1])
                coords.append([lon, lat])
            except ValueError:
                continue
    return coords


# ============================================================
# GeoJSON file (just load and validate)
# ============================================================

def _convert_geojson_file(input_path):
    """Load a GeoJSON file and return it."""
    with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
        geojson_data = json.load(f)

    # Handle bare geometry or single feature
    if geojson_data.get('type') == 'Feature':
        geojson_data = {
            'type': 'FeatureCollection',
            'features': [geojson_data],
        }
    elif geojson_data.get('type') not in ('FeatureCollection',):
        # Might be a bare geometry
        if geojson_data.get('type') in (
            'Point', 'MultiPoint', 'LineString', 'MultiLineString',
            'Polygon', 'MultiPolygon', 'GeometryCollection',
        ):
            geojson_data = {
                'type': 'FeatureCollection',
                'features': [{
                    'type': 'Feature',
                    'properties': {},
                    'geometry': geojson_data,
                }],
            }

    feature_count = len(geojson_data.get('features', []))
    if feature_count == 0:
        return None

    return {
        'geojson': geojson_data,
        'feature_count': feature_count,
    }


# ============================================================
# ogr2ogr fallback (for shapefiles and formats native can't handle)
# ============================================================

def _convert_with_ogr2ogr(input_path, ext):
    """Fall back to ogr2ogr for conversion. Used for shapefiles, GPX, etc."""
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

        # If that failed, try multi-layer approach
        return _try_multilayer_convert(source)

    except subprocess.TimeoutExpired:
        return {'error': 'Vector conversion timed out'}
    except FileNotFoundError:
        return {
            'error': (
                'GDAL/ogr2ogr is required for this file format but is not '
                'installed. KMZ, KML, and GeoJSON files are supported without '
                'GDAL. For shapefiles and GPX, install GDAL: brew install gdal'
            )
        }
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
