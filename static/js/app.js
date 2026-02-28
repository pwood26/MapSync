// MapSync - Application State & Initialization

var AppState = {
    imageId: null,
    previewUrl: null,
    originalWidth: null,
    originalHeight: null,
    previewWidth: null,
    previewHeight: null,
    scaleFactor: 1.0,
    metadata: null,
    gcps: [],
    currentMode: 'navigate', // 'navigate' | 'place_aerial' | 'place_map'
    pendingGcp: null,
    aerialViewer: null,
    mapInstance: null,
    aerialOverlays: [],
    mapMarkers: [],
    isGeoreferenced: false,
    lastGeorefBounds: null,
    vectorOverlays: [],
};

document.addEventListener('DOMContentLoaded', function () {
    // Initialize the map
    AppState.mapInstance = initMapViewer('map-viewer');

    // File upload handler
    var fileInput = document.getElementById('fileInput');
    fileInput.addEventListener('change', handleFileUpload);

    // Vector overlay upload handler
    var overlayInput = document.getElementById('overlayFileInput');
    overlayInput.addEventListener('change', handleOverlayUpload);

    // Keyboard shortcuts
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            cancelGcpPlacement();
        }
        if (e.key === 'g' || e.key === 'G') {
            if (AppState.currentMode === 'navigate' && AppState.imageId) {
                startGcpPlacement();
            }
        }
    });
});

function _formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(0) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
}

function handleFileUpload(e) {
    var file = e.target.files[0];
    if (!file) return;

    var formData = new FormData();
    formData.append('file', file);

    var sizeLabel = _formatFileSize(file.size);
    showLoading('Uploading ' + sizeLabel + '...');

    // Show progress bar
    var progressWrap = document.getElementById('uploadProgressWrap');
    var progressFill = document.getElementById('uploadProgressFill');
    var progressLabel = document.getElementById('uploadProgressLabel');
    if (progressWrap) progressWrap.style.display = 'block';
    if (progressFill) progressFill.style.width = '0%';
    if (progressLabel) progressLabel.textContent = '0% of ' + sizeLabel;

    var xhr = new XMLHttpRequest();
    xhr.open('POST', '/api/upload');

    xhr.upload.addEventListener('progress', function (ev) {
        if (ev.lengthComputable) {
            var pct = Math.round((ev.loaded / ev.total) * 100);
            if (progressFill) progressFill.style.width = pct + '%';
            if (progressLabel) progressLabel.textContent = pct + '% of ' + sizeLabel;
            if (pct >= 100) {
                var loadingText = document.getElementById('loadingText');
                if (loadingText) loadingText.textContent = 'Processing image...';
            }
        }
    });

    xhr.addEventListener('load', function () {
        if (progressWrap) progressWrap.style.display = 'none';

        if (xhr.status < 200 || xhr.status >= 300) {
            hideLoading();
            try {
                var d = JSON.parse(xhr.responseText);
                alert('Upload failed: ' + (d.error || 'Unknown error'));
            } catch (_e) {
                alert('Upload failed: Server error (' + xhr.status + ')');
            }
            return;
        }

        var data;
        try { data = JSON.parse(xhr.responseText); } catch (_e) {
            hideLoading();
            alert('Upload failed: Invalid response from server');
            return;
        }

        AppState.imageId = data.image_id;
        AppState.previewUrl = data.preview_url;
        AppState.originalWidth = data.original_width;
        AppState.originalHeight = data.original_height;
        AppState.previewWidth = data.preview_width;
        AppState.previewHeight = data.preview_height;
        AppState.scaleFactor = data.scale_factor;
        AppState.metadata = data.metadata;
        AppState.gcps = [];
        AppState.isGeoreferenced = false;

        // Clear any existing GCP data
        clearAllGcps();

        // Initialize the aerial viewer
        var placeholder = document.getElementById('aerialPlaceholder');
        if (placeholder) placeholder.style.display = 'none';
        AppState.aerialViewer = initAerialViewer('aerial-viewer', data.preview_url);

        // Enable the Add GCP button
        var addGcpEl = document.getElementById('addGcpBtn');
        var rotCtrl = document.getElementById('rotationControls');
        if (addGcpEl) addGcpEl.disabled = false;
        if (rotCtrl) rotCtrl.style.display = 'flex';

        // Display metadata info if available
        displayMetadataInfo(data.metadata);

        updateGcpStatus('Click "Add GCP" to start placing control points');
        updateExportButton();

        hideLoading();
    });

    xhr.addEventListener('error', function () {
        if (progressWrap) progressWrap.style.display = 'none';
        hideLoading();
        alert('Upload failed: Network error');
    });

    xhr.send(formData);

    // Reset file input so the same file can be re-uploaded
    e.target.value = '';
}

function handleOverlayUpload(e) {
    var file = e.target.files[0];
    if (!file) return;

    var formData = new FormData();
    formData.append('file', file);

    showLoading('Processing vector overlay...');

    fetch('/api/overlay/upload', {
        method: 'POST',
        body: formData,
    })
        .then(function (resp) {
            if (!resp.ok) return resp.json().then(function (d) { throw new Error(d.error); });
            return resp.json();
        })
        .then(function (data) {
            hideLoading();
            addVectorOverlay(data.overlay_id, data.name, data.geojson);
            updateGcpStatus(
                'Overlay "' + data.name + '" loaded with ' +
                data.feature_count + ' feature(s).'
            );
        })
        .catch(function (err) {
            hideLoading();
            alert('Overlay upload failed: ' + err.message);
        });

    e.target.value = '';
}

function setMode(mode) {
    AppState.currentMode = mode;
    var indicator = document.getElementById('modeIndicator');
    var aerialPane = document.getElementById('aerial-pane');
    var mapPane = document.getElementById('map-pane');
    var addBtn = document.getElementById('addGcpBtn');
    var cancelBtn = document.getElementById('cancelGcpBtn');

    if (aerialPane) aerialPane.classList.remove('active-target');
    if (mapPane) mapPane.classList.remove('active-target');

    if (mode === 'navigate') {
        if (indicator) indicator.style.display = 'none';
        if (addBtn) { addBtn.classList.remove('active'); addBtn.textContent = 'Add GCP'; }
        if (cancelBtn) cancelBtn.style.display = 'none';
        // Re-enable map and aerial navigation
        if (AppState.mapInstance) AppState.mapInstance.dragging.enable();
        if (AppState.aerialViewer) AppState.aerialViewer.setMouseNavEnabled(true);
    } else if (mode === 'place_aerial') {
        if (indicator) { indicator.style.display = 'block'; indicator.textContent = 'Step 1: Click a point on the aerial photo'; }
        if (aerialPane) aerialPane.classList.add('active-target');
        if (addBtn) { addBtn.classList.add('active'); addBtn.textContent = 'Placing...'; }
        if (cancelBtn) cancelBtn.style.display = 'inline-block';
        updateGcpStatus('Click a recognizable point on the aerial photo (road intersection, building corner, etc.)');
    } else if (mode === 'place_map') {
        if (indicator) { indicator.style.display = 'block'; indicator.textContent = 'Step 2: Click the same point on the map'; }
        if (mapPane) mapPane.classList.add('active-target');
        if (addBtn) { addBtn.classList.add('active'); addBtn.textContent = 'Placing...'; }
        if (cancelBtn) cancelBtn.style.display = 'inline-block';
        updateGcpStatus('Click the corresponding point on the satellite map');
    }
}

function updateGcpStatus(text) {
    var el = document.getElementById('gcpStatus');
    if (el) el.textContent = text;
}

function updateExportButton() {
    var btn = document.getElementById('exportBtn');
    if (btn) btn.disabled = AppState.gcps.length < 5;
    var counter = document.getElementById('gcpCounter');
    if (!counter) return;
    if (AppState.imageId) {
        counter.textContent = AppState.gcps.length + '/5 minimum GCPs';
        counter.style.color = AppState.gcps.length >= 5 ? '#15803D' : '#B91C1C';
    } else {
        counter.textContent = '';
    }
}

function showLoading(text) {
    var loadingText = document.getElementById('loadingText');
    var overlay = document.getElementById('loadingOverlay');
    if (loadingText) loadingText.textContent = text || 'Processing...';
    if (overlay) overlay.style.display = 'flex';
}

function hideLoading() {
    var overlay = document.getElementById('loadingOverlay');
    if (overlay) overlay.style.display = 'none';
}

function showMapLoading(text) {
    var loadingText = document.getElementById('mapLoadingText');
    var overlay = document.getElementById('mapLoadingOverlay');
    if (loadingText) loadingText.textContent = text || 'Processing...';
    if (overlay) overlay.style.display = 'flex';
}

function hideMapLoading() {
    var overlay = document.getElementById('mapLoadingOverlay');
    if (overlay) overlay.style.display = 'none';
}

function displayMetadataInfo(metadata) {
    var infoDiv = document.getElementById('metadataInfo');
    if (!infoDiv) return;

    if (!metadata) {
        infoDiv.style.display = 'none';
        return;
    }

    var hasUsableMetadata = metadata.has_georeference || metadata.has_gps;

    if (!hasUsableMetadata) {
        infoDiv.style.display = 'none';
        return;
    }

    var html = '<div class="metadata-badge">';
    html += '<span class="metadata-icon">📍</span>';

    if (metadata.has_georeference) {
        html += '<strong>Location metadata detected</strong>';
        html += '<br><small>Source: ' + (metadata.source || 'GDAL') + '</small>';
        if (metadata.center_lat && metadata.center_lon) {
            html += '<br><small>Center: ' + metadata.center_lat.toFixed(6) + ', ' + metadata.center_lon.toFixed(6) + '</small>';
        }
    } else if (metadata.has_gps) {
        html += '<strong>GPS location found</strong>';
        html += '<br><small>Source: ' + (metadata.source || 'EXIF') + '</small>';
        if (metadata.center_lat && metadata.center_lon) {
            html += '<br><small>Location: ' + metadata.center_lat.toFixed(6) + ', ' + metadata.center_lon.toFixed(6) + '</small>';
        }
        if (metadata.gsd) {
            html += '<br><small>GSD: ~' + metadata.gsd.toFixed(2) + ' m/pixel</small>';
        }
    }

    html += '<br><small class="metadata-hint">Place GCPs manually to georeference this image</small>';
    html += '</div>';

    infoDiv.innerHTML = html;
    infoDiv.style.display = 'block';
}
