import os
import uuid
from flask import Flask, render_template, request, jsonify, send_file

from processing.tiff_handler import validate_tiff, convert_to_preview, extract_metadata
from processing.georeferencer import run_georeferencing
from processing.exporter import generate_kmz
from processing.vector_handler import convert_to_geojson, SUPPORTED_EXTENSIONS
from processing.auto_georeferencer import run_auto_georeferencing
from processing.metadata_georeferencer import georeference_from_metadata

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
PREVIEW_FOLDER = os.path.join(BASE_DIR, 'static', 'previews')
EXPORT_FOLDER = os.path.join(BASE_DIR, 'static', 'exports')
OVERLAY_FOLDER = os.path.join(BASE_DIR, 'static', 'overlays')
ALLOWED_EXTENSIONS = {'.tif', '.tiff'}
ALLOWED_OVERLAY_EXTENSIONS = set(SUPPORTED_EXTENSIONS.keys())

app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB

for folder in [UPLOAD_FOLDER, PREVIEW_FOLDER, EXPORT_FOLDER, OVERLAY_FOLDER]:
    os.makedirs(folder, exist_ok=True)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'No file selected'}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return jsonify({'error': 'Only .tif/.tiff files are allowed'}), 400

    image_id = str(uuid.uuid4())
    tiff_path = os.path.join(UPLOAD_FOLDER, f'{image_id}.tiff')
    f.save(tiff_path)

    valid, info = validate_tiff(tiff_path)
    if not valid:
        os.remove(tiff_path)
        return jsonify({'error': info}), 400

    preview_path = os.path.join(PREVIEW_FOLDER, f'{image_id}.png')
    preview_info = convert_to_preview(tiff_path, preview_path)

    # Extract metadata for potential auto-georeferencing
    metadata = extract_metadata(tiff_path)

    return jsonify({
        'image_id': image_id,
        'preview_url': f'/static/previews/{image_id}.png',
        'original_width': preview_info['original_width'],
        'original_height': preview_info['original_height'],
        'preview_width': preview_info['preview_width'],
        'preview_height': preview_info['preview_height'],
        'scale_factor': preview_info['scale_factor'],
        'metadata': metadata,
    })


@app.route('/api/overlay/upload', methods=['POST'])
def upload_overlay():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400

    f = request.files['file']
    if not f.filename:
        return jsonify({'error': 'No file selected'}), 400

    ext = os.path.splitext(f.filename)[1].lower()
    if ext not in ALLOWED_OVERLAY_EXTENSIONS:
        allowed = ', '.join(sorted(ALLOWED_OVERLAY_EXTENSIONS))
        return jsonify({'error': f'Unsupported format. Allowed: {allowed}'}), 400

    overlay_id = str(uuid.uuid4())
    saved_path = os.path.join(OVERLAY_FOLDER, f'{overlay_id}{ext}')
    f.save(saved_path)

    result = convert_to_geojson(saved_path, f.filename)

    # Clean up the uploaded file — we only need the GeoJSON in the browser
    if os.path.exists(saved_path):
        os.remove(saved_path)

    if result.get('error'):
        return jsonify({'error': result['error']}), 400

    return jsonify({
        'overlay_id': overlay_id,
        'name': os.path.splitext(f.filename)[0],
        'feature_count': result['feature_count'],
        'geojson': result['geojson'],
    })


@app.route('/api/auto-georeference', methods=['POST'])
def auto_georeference():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400

    image_id = data.get('image_id')
    bounds = data.get('bounds')
    force_feature_matching = data.get('force_feature_matching', False)

    if not image_id:
        return jsonify({'error': 'Missing image_id'}), 400

    tiff_path = os.path.join(UPLOAD_FOLDER, f'{image_id}.tiff')
    if not os.path.exists(tiff_path):
        return jsonify({'error': 'Image not found'}), 404

    # Extract metadata to determine bounding box automatically
    metadata = extract_metadata(tiff_path)

    # If metadata provides location, use it to auto-generate bounding box for AI matching
    if not force_feature_matching and metadata.get('corners'):
        # Already georeferenced - use metadata corners as bounding box for AI refinement
        bounds = metadata['corners']
    elif not force_feature_matching and metadata.get('has_gps') and metadata.get('center_lat'):
        # GPS center point - estimate bounds for AI matching
        from PIL import Image
        with Image.open(tiff_path) as img:
            width, height = img.size

        # Estimate coverage area (conservative estimate: ~0.05 degrees if no GSD)
        if metadata.get('gsd'):
            from processing.metadata_georeferencer import estimate_gsd_from_bounds
            import math

            # Calculate approximate coverage from center + GSD
            half_width_px = width / 2
            half_height_px = height / 2
            half_width_m = half_width_px * metadata['gsd']
            half_height_m = half_height_px * metadata['gsd']

            # Convert to degrees
            center_lat = metadata['center_lat']
            meters_per_degree_lat = 111111
            meters_per_degree_lon = 111111 * math.cos(math.radians(center_lat))

            lat_span = half_height_m / meters_per_degree_lat
            lon_span = half_width_m / meters_per_degree_lon

            bounds = {
                'north': center_lat + lat_span,
                'south': center_lat - lat_span,
                'east': metadata['center_lon'] + lon_span,
                'west': metadata['center_lon'] - lon_span,
            }
        else:
            # No GSD - use conservative default (~5km span)
            span = 0.05
            bounds = {
                'north': metadata['center_lat'] + span,
                'south': metadata['center_lat'] - span,
                'east': metadata['center_lon'] + span,
                'west': metadata['center_lon'] - span,
            }

    # If we have bounds (from metadata or user), run AI feature matching
    if bounds:
        result = run_auto_georeferencing(image_id, tiff_path, bounds)

        if result.get('error'):
            return jsonify(result), 422

        # Indicate whether metadata helped or if purely manual
        result['method'] = 'ai_feature_matching'
        result['used_metadata'] = metadata.get('has_georeference') or metadata.get('has_gps')
        result['metadata_source'] = metadata.get('source') if result['used_metadata'] else None
        return jsonify(result)

    # No metadata and no user-provided bounds
    return jsonify({'error': 'No location metadata found. Please draw a bounding box on the map.'}), 400


@app.route('/api/georeference', methods=['POST'])
def georeference():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400

    image_id = data.get('image_id')
    gcps = data.get('gcps', [])

    if not image_id:
        return jsonify({'error': 'Missing image_id'}), 400
    if len(gcps) < 5:
        return jsonify({'error': 'At least 5 GCPs are required'}), 400

    tiff_path = os.path.join(UPLOAD_FOLDER, f'{image_id}.tiff')
    if not os.path.exists(tiff_path):
        return jsonify({'error': 'Image not found'}), 404

    output_path = os.path.join(EXPORT_FOLDER, f'{image_id}_georef.tiff')
    result = run_georeferencing(tiff_path, output_path, gcps)

    if result.get('error'):
        return jsonify({'error': result['error']}), 500

    return jsonify(result)


@app.route('/api/export', methods=['POST'])
def export():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400

    image_id = data.get('image_id')
    if not image_id:
        return jsonify({'error': 'Missing image_id'}), 400

    georef_path = os.path.join(EXPORT_FOLDER, f'{image_id}_georef.tiff')
    if not os.path.exists(georef_path):
        return jsonify({'error': 'Georeferenced image not found. Run georeferencing first.'}), 404

    kmz_path = os.path.join(EXPORT_FOLDER, f'{image_id}.kmz')
    result = generate_kmz(georef_path, kmz_path)

    if result.get('error'):
        return jsonify({'error': result['error']}), 500

    return jsonify({
        'download_url': f'/api/download/{image_id}.kmz',
        'bounds': result.get('bounds'),
    })


@app.route('/api/download/<filename>')
def download(filename):
    filepath = os.path.join(EXPORT_FOLDER, filename)
    if not os.path.exists(filepath):
        return jsonify({'error': 'File not found'}), 404
    return send_file(filepath, as_attachment=True, download_name=filename)


if __name__ == '__main__':
    app.run(debug=True, port=5051)
