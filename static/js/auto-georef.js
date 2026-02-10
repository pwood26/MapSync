// MapSync - Auto-Georeferencing
// Handles bounding box drawing on the Leaflet map and the auto-match API call.

document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('autoGeorefBtn');
    if (btn) {
        btn.addEventListener('click', onAutoGeorefClick);
    }
});

// ============================================================
// State
// ============================================================

var AutoGeoref = {
    drawing: false,
    startLatLng: null,
    rect: null,
    bounds: null,
    // Store handlers so we can remove them later
    _onMouseDown: null,
    _onMouseMove: null,
    _onMouseUp: null,
};

// ============================================================
// Button click → start bbox drawing
// ============================================================

function onAutoGeorefClick() {
    if (!AppState.imageId) return;

    // If already drawing, cancel
    if (AutoGeoref.drawing) {
        cancelBboxDrawing();
        return;
    }

    // Clear any existing auto-georef rectangle
    if (AutoGeoref.rect) {
        AppState.mapInstance.removeLayer(AutoGeoref.rect);
        AutoGeoref.rect = null;
    }

    // Check if metadata is available
    var metadata = AppState.metadata;
    if (metadata && (metadata.has_georeference || metadata.has_gps)) {
        // Try metadata-based georeferencing first
        runAutoGeoreferenceWithMetadata();
    } else {
        // Fall back to bounding box drawing for feature matching
        startBboxDrawing();
    }
}

// ============================================================
// Bounding box drawing on the Leaflet map
// ============================================================

function startBboxDrawing() {
    var map = AppState.mapInstance;
    AutoGeoref.drawing = true;
    AutoGeoref.startLatLng = null;
    AutoGeoref.bounds = null;

    // Update UI
    var btn = document.getElementById('autoGeorefBtn');
    btn.textContent = 'Cancel';
    btn.classList.add('active');
    updateGcpStatus('Draw a rectangle on the map covering the approximate area of the aerial photo.');

    // Show mode indicator
    var indicator = document.getElementById('modeIndicator');
    indicator.textContent = 'Draw a bounding box on the map';
    indicator.style.display = 'block';

    // Disable map dragging so mousedown starts the rectangle
    map.dragging.disable();
    map.getContainer().style.cursor = 'crosshair';

    // Create handlers
    AutoGeoref._onMouseDown = function (e) {
        AutoGeoref.startLatLng = e.latlng;
        AutoGeoref.rect = L.rectangle(
            [e.latlng, e.latlng],
            { color: '#48dbfb', weight: 2, dashArray: '6,4', fillOpacity: 0.1 }
        ).addTo(map);
    };

    AutoGeoref._onMouseMove = function (e) {
        if (!AutoGeoref.startLatLng || !AutoGeoref.rect) return;
        AutoGeoref.rect.setBounds(
            L.latLngBounds(AutoGeoref.startLatLng, e.latlng)
        );
    };

    AutoGeoref._onMouseUp = function (e) {
        if (!AutoGeoref.startLatLng) return;

        var latlngBounds = L.latLngBounds(AutoGeoref.startLatLng, e.latlng);

        // Reject tiny accidental clicks (< ~100m)
        var latSpan = latlngBounds.getNorth() - latlngBounds.getSouth();
        var lonSpan = latlngBounds.getEast() - latlngBounds.getWest();
        if (latSpan < 0.001 && lonSpan < 0.001) {
            // Too small — ignore this click, keep drawing mode active
            if (AutoGeoref.rect) {
                map.removeLayer(AutoGeoref.rect);
                AutoGeoref.rect = null;
            }
            AutoGeoref.startLatLng = null;
            return;
        }

        AutoGeoref.bounds = {
            north: latlngBounds.getNorth(),
            south: latlngBounds.getSouth(),
            east: latlngBounds.getEast(),
            west: latlngBounds.getWest(),
        };

        finishBboxDrawing();
        runAutoGeoreference();
    };

    map.on('mousedown', AutoGeoref._onMouseDown);
    map.on('mousemove', AutoGeoref._onMouseMove);
    map.on('mouseup', AutoGeoref._onMouseUp);
}

function finishBboxDrawing() {
    var map = AppState.mapInstance;
    AutoGeoref.drawing = false;

    // Remove event handlers
    if (AutoGeoref._onMouseDown) map.off('mousedown', AutoGeoref._onMouseDown);
    if (AutoGeoref._onMouseMove) map.off('mousemove', AutoGeoref._onMouseMove);
    if (AutoGeoref._onMouseUp) map.off('mouseup', AutoGeoref._onMouseUp);

    // Restore map
    map.dragging.enable();
    map.getContainer().style.cursor = '';

    // Reset button
    var btn = document.getElementById('autoGeorefBtn');
    btn.textContent = 'Auto-Georeference';
    btn.classList.remove('active');

    // Hide mode indicator
    document.getElementById('modeIndicator').style.display = 'none';
}

function cancelBboxDrawing() {
    if (AutoGeoref.rect) {
        AppState.mapInstance.removeLayer(AutoGeoref.rect);
        AutoGeoref.rect = null;
    }
    AutoGeoref.startLatLng = null;
    AutoGeoref.bounds = null;
    finishBboxDrawing();
    updateGcpStatus('Auto-georeference cancelled.');
}

// ============================================================
// API call and GCP population
// ============================================================

function runAutoGeoreferenceWithMetadata() {
    showLoading('Using metadata location to guide AI feature matching...');

    fetch('/api/auto-georeference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            image_id: AppState.imageId,
            // Bounds will be auto-generated from metadata
        }),
    })
        .then(function (resp) {
            return resp.json().then(function (data) {
                if (!resp.ok) {
                    throw new Error(data.error || 'Auto-georeferencing failed.');
                }
                return data;
            });
        })
        .then(function (data) {
            populateGcpsFromAutoResult(data);
            hideLoading();

            var confidence = Math.round(data.confidence * 100);
            var statusMsg = 'AI auto-detected ' + data.gcps.length + ' control points ';
            statusMsg += '(confidence: ' + confidence + '%, ' + data.match_count + ' feature matches';

            if (data.used_metadata && data.metadata_source) {
                statusMsg += ', guided by ' + data.metadata_source;
            }

            statusMsg += '). Review and click Export KMZ.';
            updateGcpStatus(statusMsg);
        })
        .catch(function (err) {
            hideLoading();
            // If metadata-guided matching fails, offer manual bounding box
            if (confirm('Automatic georeferencing failed:\n\n' + err.message + '\n\nWould you like to manually draw a bounding box for AI matching?')) {
                startBboxDrawing();
            } else {
                updateGcpStatus('Auto-georeferencing cancelled.');
            }
        });
}

function runAutoGeoreference() {
    showLoading('Downloading satellite imagery and matching features...');

    fetch('/api/auto-georeference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            image_id: AppState.imageId,
            bounds: AutoGeoref.bounds,
            force_feature_matching: true,
        }),
    })
        .then(function (resp) {
            return resp.json().then(function (data) {
                if (!resp.ok) {
                    throw new Error(data.error || 'Auto-georeferencing failed.');
                }
                return data;
            });
        })
        .then(function (data) {
            populateGcpsFromAutoResult(data);
            hideLoading();

            // Remove the bounding box rectangle
            if (AutoGeoref.rect) {
                AppState.mapInstance.removeLayer(AutoGeoref.rect);
                AutoGeoref.rect = null;
            }

            var confidence = Math.round(data.confidence * 100);
            updateGcpStatus(
                'Auto-detected ' + data.gcps.length + ' control points ' +
                '(confidence: ' + confidence + '%, ' +
                data.match_count + ' feature matches). ' +
                'Review and adjust, then click Export KMZ.'
            );
        })
        .catch(function (err) {
            hideLoading();

            // Remove the bounding box rectangle on error too
            if (AutoGeoref.rect) {
                AppState.mapInstance.removeLayer(AutoGeoref.rect);
                AutoGeoref.rect = null;
            }

            updateGcpStatus('Auto-matching failed: ' + err.message);
            alert('Auto-georeferencing failed:\n\n' + err.message);
        });
}

// Helper function to populate GCPs from auto-georeferencing result
function populateGcpsFromAutoResult(data) {
    // Remove the bounding box rectangle if it exists
    if (AutoGeoref.rect) {
        AppState.mapInstance.removeLayer(AutoGeoref.rect);
        AutoGeoref.rect = null;
    }

    // Clear any existing GCPs first
    clearAllGcps();

    // Populate GCPs from the auto-match result
    var gcps = data.gcps;
    for (var i = 0; i < gcps.length; i++) {
        var gcp = {
            id: i + 1,
            pixelX: gcps[i].pixel_x,
            pixelY: gcps[i].pixel_y,
            lat: gcps[i].lat,
            lon: gcps[i].lon,
        };
        AppState.gcps.push(gcp);

        // Add markers on the aerial viewer (needs preview coordinates)
        var previewX = gcp.pixelX / AppState.scaleFactor;
        var previewY = gcp.pixelY / AppState.scaleFactor;
        addAerialMarker(AppState.aerialViewer, previewX, previewY, gcp.id);

        // Add markers on the map
        addMapMarker(AppState.mapInstance, gcp.lat, gcp.lon, gcp.id);
    }

    AppState.isGeoreferenced = false;
    updateGcpTable();
    updateExportButton();
}
