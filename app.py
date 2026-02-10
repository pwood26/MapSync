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
TEMP_EXTRACT_FOLDER = os.path.join(BASE_DIR, 'static', 'temp_extract')
ALLOWED_EXTENSIONS = {'.tif', '.tiff', '.zip'}
ALLOWED_OVERLAY_EXTENSIONS = set(SUPPORTED_EXTENSIONS.keys())

app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500 MB

for folder in [UPLOAD_FOLDER, PREVIEW_FOLDER, EXPORT_FOLDER, OVERLAY_FOLDER, TEMP_EXTRACT_FOLDER]:
    os.makedirs(folder, exist_ok=True)


# Global error handlers — always return JSON, never HTML
@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': f'Internal server error: {str(e)}'}), 500


@app.errorhandler(413)
def too_large(e):
    return jsonify({'error': 'File too large (max 500 MB)'}), 413


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
        return jsonify({'error': 'Only .tif/.tiff/.zip files are allowed'}), 400

    image_id = str(uuid.uuid4())

    # Handle ZIP files (USGS download packages)
    if ext == '.zip':
        from processing.zip_handler import extract_usgs_package, get_package_info
        import shutil

        # Save uploaded ZIP
        zip_path = os.path.join(UPLOAD_FOLDER, f'{image_id}.zip')
        f.save(zip_path)

        # Extract to temporary directory
        extract_dir = os.path.join(TEMP_EXTRACT_FOLDER, image_id)
        os.makedirs(extract_dir, exist_ok=True)

        extracted = extract_usgs_package(zip_path, extract_dir)

        if not extracted or 'tiff' not in extracted:
            # Clean up
            os.remove(zip_path)
            if os.path.exists(extract_dir):
                shutil.rmtree(extract_dir)
            return jsonify({'error': 'No valid TIFF found in ZIP package'}), 400

        # Move TIFF to upload folder
        tiff_path = os.path.join(UPLOAD_FOLDER, f'{image_id}.tiff')
        shutil.copy2(extracted['tiff'], tiff_path)

        # Move companion files if they exist
        if extracted.get('worldfile'):
            worldfile_dest = os.path.join(UPLOAD_FOLDER, f'{image_id}.tfw')
            shutil.copy2(extracted['worldfile'], worldfile_dest)

        if extracted.get('footprint'):
            footprint_dest = os.path.join(UPLOAD_FOLDER, f'{image_id}_footprint.geojson')
            shutil.copy2(extracted['footprint'], footprint_dest)

        # Clean up ZIP and extraction directory
        os.remove(zip_path)
        shutil.rmtree(extract_dir)

    else:
        # Handle regular TIFF upload
        tiff_path = os.path.join(UPLOAD_FOLDER, f'{image_id}.tiff')
        f.save(tiff_path)

    # Validate TIFF
    valid, info = validate_tiff(tiff_path)
    if not valid:
        os.remove(tiff_path)
        return jsonify({'error': info}), 400

    # Generate preview
    preview_path = os.path.join(PREVIEW_FOLDER, f'{image_id}.png')
    try:
        preview_info = convert_to_preview(tiff_path, preview_path)
    except Exception as e:
        os.remove(tiff_path)
        return jsonify({'error': f'Failed to generate preview: {str(e)}'}), 500

    # Extract metadata for potential auto-georeferencing
    try:
        metadata = extract_metadata(tiff_path)
    except Exception as e:
        # Metadata extraction is non-critical — proceed without it
        metadata = {
            'has_georeference': False,
            'has_gps': False,
            'has_usgs_metadata': False,
            'center_lat': None,
            'center_lon': None,
            'corners': None,
            'gsd': None,
            'source': None,
        }

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

    print(f'[auto-georeference] image_id={image_id}, '
          f'force_feature_matching={force_feature_matching}, '
          f'has_bounds={bounds is not None}, '
          f'metadata: has_georef={metadata.get("has_georeference")}, '
          f'has_gps={metadata.get("has_gps")}, '
          f'corners={metadata.get("corners") is not None}, '
          f'source={metadata.get("source")}')

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
        print(f'[auto-georeference] Running with bounds: '
              f'N={bounds.get("north")}, S={bounds.get("south")}, '
              f'E={bounds.get("east")}, W={bounds.get("west")}')

        result = run_auto_georeferencing(image_id, tiff_path, bounds)

        if result.get('error'):
            print(f'[auto-georeference] Failed: {result["error"]}')
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
    port = int(os.environ.get('PORT', 5051))
    app.run(debug=True, host='0.0.0.0', port=port)
