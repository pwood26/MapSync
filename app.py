import os
import uuid
from flask import Flask, render_template, request, jsonify, send_file

from processing.tiff_handler import validate_tiff, convert_to_preview, extract_metadata
from processing.georeferencer import run_georeferencing
from processing.exporter import generate_kmz
from processing.vector_handler import convert_to_geojson, SUPPORTED_EXTENSIONS
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
    """Generate GCPs directly from USGS metadata (world file, footprint, GDAL geotransform).

    No AI matching — just uses the metadata coordinates to place corner + center
    GCPs that the user can then fine-tune manually.
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No JSON data provided'}), 400

    image_id = data.get('image_id')
    if not image_id:
        return jsonify({'error': 'Missing image_id'}), 400

    tiff_path = os.path.join(UPLOAD_FOLDER, f'{image_id}.tiff')
    if not os.path.exists(tiff_path):
        return jsonify({'error': 'Image not found'}), 404

    # Extract metadata
    metadata = extract_metadata(tiff_path)

    print(f'[auto-georeference] image_id={image_id}, '
          f'metadata: has_georef={metadata.get("has_georeference")}, '
          f'has_gps={metadata.get("has_gps")}, '
          f'corners={metadata.get("corners") is not None}, '
          f'source={metadata.get("source")}')

    if not metadata.get('has_georeference') and not metadata.get('has_gps'):
        return jsonify({
            'error': (
                'No location metadata found in this image. '
                'Upload a USGS ZIP package (with .tfw world file or footprint GeoJSON) '
                'or use manual GCP placement.'
            )
        }), 400

    # Get image dimensions
    from PIL import Image
    try:
        with Image.open(tiff_path) as img:
            width, height = img.size
    except Exception as e:
        return jsonify({'error': f'Could not read image dimensions: {e}'}), 500

    # Generate GCPs from metadata
    result = georeference_from_metadata(metadata, width, height)

    if result.get('error'):
        print(f'[auto-georeference] Failed: {result["error"]}')
        return jsonify({'error': result['error']}), 422

    gcps = result['gcps']
    print(f'[auto-georeference] Generated {len(gcps)} GCPs from {result["method"]}')

    return jsonify({
        'success': True,
        'gcps': [
            {
                'pixel_x': g['pixel_x'],
                'pixel_y': g['pixel_y'],
                'lat': g['lat'],
                'lon': g['lon'],
            }
            for g in gcps
        ],
        'match_count': len(gcps),
        'confidence': 1.0,
        'method': 'metadata',
        'metadata_source': metadata.get('source'),
    })


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


@app.route('/api/preview-overlay/<image_id>')
def preview_overlay(image_id):
    """Serve the georeferenced image as a JPEG for Leaflet overlay preview.

    Also returns the bounds as JSON if requested with ?bounds=1.
    """
    georef_path = os.path.join(EXPORT_FOLDER, f'{image_id}_georef.tiff')
    if not os.path.exists(georef_path):
        return jsonify({'error': 'Georeferenced image not found'}), 404

    # Check if caller wants just the bounds
    if request.args.get('bounds'):
        bounds_path = georef_path.replace('.tiff', '_bounds.json').replace('.tif', '_bounds.json')
        if os.path.exists(bounds_path):
            import json as json_mod
            with open(bounds_path, 'r') as f:
                bounds = json_mod.load(f)
            return jsonify(bounds)
        return jsonify({'error': 'Bounds not found'}), 404

    # Convert georeferenced TIFF to JPEG for browser display
    preview_jpg = os.path.join(EXPORT_FOLDER, f'{image_id}_preview_overlay.jpg')
    if not os.path.exists(preview_jpg):
        try:
            from PIL import Image as PILImage
            PILImage.MAX_IMAGE_PIXELS = 500_000_000
            img = PILImage.open(georef_path)
            if img.mode == 'RGBA':
                # Keep transparency by converting to PNG instead
                preview_png = os.path.join(EXPORT_FOLDER, f'{image_id}_preview_overlay.png')
                img.save(preview_png, 'PNG')
                return send_file(preview_png, mimetype='image/png')
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            img.save(preview_jpg, 'JPEG', quality=85)
        except Exception as e:
            return jsonify({'error': f'Preview generation failed: {e}'}), 500

    return send_file(preview_jpg, mimetype='image/jpeg')


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

    # Check for user-adjusted bounds (from the Preview & Adjust step)
    adjusted_bounds = data.get('adjusted_bounds')
    rotation = data.get('rotation', 0)

    if adjusted_bounds:
        # Write adjusted bounds to the sidecar JSON so exporter picks them up
        import json as json_mod
        bounds_path = georef_path.replace('.tiff', '_bounds.json').replace('.tif', '_bounds.json')
        with open(bounds_path, 'w') as f:
            json_mod.dump(adjusted_bounds, f)

    kmz_path = os.path.join(EXPORT_FOLDER, f'{image_id}.kmz')
    result = generate_kmz(georef_path, kmz_path, rotation=rotation)

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
