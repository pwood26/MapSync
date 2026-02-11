// MapSync - Auto-Georeferencing
// Handles bounding box drawing on the Leaflet map, the "AI Match This View"
// shortcut, vector overlay context collection, and the auto-match API call.

document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('autoGeorefBtn');
    if (btn) {
        btn.addEventListener('click', onAutoGeorefClick);
    }

    var aiMatchBtn = document.getElementById('aiMatchViewBtn');
    if (aiMatchBtn) {
        aiMatchBtn.addEventListener('click', onAiMatchViewClick);
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
// "AI Match This View" — use current map viewport as bounds
// ============================================================

function onAiMatchViewClick() {
    if (!AppState.imageId) return;
    if (!AppState.mapInstance) return;

    var mapBounds = AppState.mapInstance.getBounds();
    var bounds = {
        north: mapBounds.getNorth(),
        south: mapBounds.getSouth(),
        east: mapBounds.getEast(),
        west: mapBounds.getWest(),
    };

    // Validate that the viewport is a reasonable size
    var latSpan = bounds.north - bounds.south;
    var lonSpan = bounds.east - bounds.west;
    if (latSpan > 0.5 || lonSpan > 0.5) {
        alert(
            'The current map view is too large for AI matching.\n\n' +
            'Zoom in closer to the area where the aerial photo was taken.'
        );
        return;
    }
    if (latSpan < 0.001 && lonSpan < 0.001) {
        alert(
            'The current map view is too small.\n\n' +
            'Zoom out a bit so the view covers the approximate extent ' +
            'of the aerial photo.'
        );
        return;
    }

    // Collect vector overlay context for features within the bounds
    var overlayContext = collectOverlayContext(bounds);

    // Show the bounding box on the map as a visual indicator
    if (AutoGeoref.rect) {
        AppState.mapInstance.removeLayer(AutoGeoref.rect);
    }
    AutoGeoref.rect = L.rectangle(
        [[bounds.south, bounds.west], [bounds.north, bounds.east]],
        { color: '#4ecca3', weight: 2, dashArray: '6,4', fillOpacity: 0.08 }
    ).addTo(AppState.mapInstance);

    AutoGeoref.bounds = bounds;

    // Run the API call
    showMapLoading('Matching aerial photo to current map view...');

    var payload = {
        image_id: AppState.imageId,
        bounds: bounds,
        force_feature_matching: true,
    };
    if (overlayContext && overlayContext.length > 0) {
        payload.overlay_context = overlayContext;
    }

    fetch('/api/auto-georeference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
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
            hideMapLoading();

            if (AutoGeoref.rect) {
                AppState.mapInstance.removeLayer(AutoGeoref.rect);
                AutoGeoref.rect = null;
            }

            var confidence = Math.round(data.confidence * 100);
            var overlayNote = (overlayContext && overlayContext.length > 0)
                ? ', with overlay context' : '';
            updateGcpStatus(
                'AI matched ' + data.gcps.length + ' control points ' +
                '(confidence: ' + confidence + '%, ' +
                data.match_count + ' feature matches' + overlayNote + '). ' +
                'Review and adjust, then click Export KMZ.'
            );
        })
        .catch(function (err) {
            hideMapLoading();
            if (AutoGeoref.rect) {
                AppState.mapInstance.removeLayer(AutoGeoref.rect);
                AutoGeoref.rect = null;
            }
            updateGcpStatus('AI matching failed: ' + err.message);
            alert('AI matching failed:\n\n' + err.message);
        });
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
    if (btn) { btn.textContent = 'Cancel'; btn.classList.add('active'); }
    updateGcpStatus('Draw a rectangle on the map covering the approximate area of the aerial photo.');

    // Show mode indicator
    var indicator = document.getElementById('modeIndicator');
    if (indicator) { indicator.textContent = 'Draw a bounding box on the map'; indicator.style.display = 'block'; }

    // Disable map dragging so mousedown starts the rectangle
    map.dragging.disable();
    var mapContainer = map.getContainer();
    if (mapContainer) mapContainer.style.cursor = 'crosshair';

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
    var mapContainer = map.getContainer();
    if (mapContainer) mapContainer.style.cursor = '';

    // Reset button
    var btn = document.getElementById('autoGeorefBtn');
    if (btn) { btn.textContent = 'Auto-Georeference'; btn.classList.remove('active'); }

    // Hide mode indicator
    var indicator = document.getElementById('modeIndicator');
    if (indicator) indicator.style.display = 'none';
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
    // Hide the metadata bar immediately — its hint is no longer relevant
    var metaInfo = document.getElementById('metadataInfo');
    if (metaInfo) metaInfo.style.display = 'none';

    showMapLoading('Using metadata location to guide AI feature matching...');

    // Collect overlay context from current map view if zoomed in reasonably
    var overlayContext = [];
    if (AppState.mapInstance) {
        var mapBounds = AppState.mapInstance.getBounds();
        var viewBounds = {
            north: mapBounds.getNorth(),
            south: mapBounds.getSouth(),
            east: mapBounds.getEast(),
            west: mapBounds.getWest(),
        };
        var latSpan = viewBounds.north - viewBounds.south;
        if (latSpan < 0.5) {
            overlayContext = collectOverlayContext(viewBounds);
        }
    }

    var payload = {
        image_id: AppState.imageId,
        // Bounds will be auto-generated from metadata
    };
    if (overlayContext && overlayContext.length > 0) {
        payload.overlay_context = overlayContext;
    }

    fetch('/api/auto-georeference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
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
            hideMapLoading();

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
            hideMapLoading();

            // If metadata-guided matching fails, offer manual bounding box
            if (confirm('Automatic georeferencing failed:\n\n' + err.message + '\n\nWould you like to manually draw a bounding box for AI matching?')) {
                startBboxDrawing();
            } else {
                updateGcpStatus('Auto-georeferencing cancelled.');
            }
        });
}

function runAutoGeoreference() {
    showMapLoading('Downloading satellite imagery and matching features...');

    // Collect overlay context for features within the drawn bounds
    var overlayContext = AutoGeoref.bounds ? collectOverlayContext(AutoGeoref.bounds) : [];

    var payload = {
        image_id: AppState.imageId,
        bounds: AutoGeoref.bounds,
        force_feature_matching: true,
    };
    if (overlayContext && overlayContext.length > 0) {
        payload.overlay_context = overlayContext;
    }

    fetch('/api/auto-georeference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
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
            hideMapLoading();

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
            hideMapLoading();

            // Remove the bounding box rectangle on error too
            if (AutoGeoref.rect) {
                AppState.mapInstance.removeLayer(AutoGeoref.rect);
                AutoGeoref.rect = null;
            }

            // Hide the metadata info bar on failure
            var metaInfo = document.getElementById('metadataInfo');
            if (metaInfo) metaInfo.style.display = 'none';

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

// ============================================================
// Vector Overlay Context Collection
// ============================================================

function collectOverlayContext(bounds) {
    /**
     * Extract features from loaded vector overlays that fall within
     * the given bounds. Returns a structured summary suitable for
     * sending to the AI as additional geographic context.
     *
     * @param {object} bounds - {north, south, east, west}
     * @returns {Array} Array of overlay summaries with features
     */
    var results = [];
    var boundsObj = L.latLngBounds(
        [bounds.south, bounds.west],
        [bounds.north, bounds.east]
    );

    for (var i = 0; i < AppState.vectorOverlays.length; i++) {
        var entry = AppState.vectorOverlays[i];
        if (!entry.visible) continue;

        var features = [];
        entry.layer.eachLayer(function (layer) {
            // Check if feature geometry intersects the bounds
            var featureBounds;
            if (layer.getLatLng) {
                // Point feature
                featureBounds = L.latLngBounds(layer.getLatLng(), layer.getLatLng());
            } else if (layer.getBounds) {
                featureBounds = layer.getBounds();
            }

            if (!featureBounds || !boundsObj.intersects(featureBounds)) return;

            var feature = layer.feature;
            if (!feature) return;

            var summary = {};

            // Extract geometry type and coordinates
            if (feature.geometry && feature.geometry.type === 'Point') {
                summary.type = 'point';
                summary.lon = feature.geometry.coordinates[0];
                summary.lat = feature.geometry.coordinates[1];
            } else if (feature.geometry && feature.geometry.type === 'LineString') {
                summary.type = 'line';
            } else if (feature.geometry && feature.geometry.type === 'Polygon') {
                summary.type = 'polygon';
            } else {
                summary.type = feature.geometry ? feature.geometry.type : 'unknown';
            }

            // Extract key properties (prioritize useful identifiers)
            var props = feature.properties || {};
            var keys = Object.keys(props);
            var selectedProps = {};
            var priorityKeys = [
                'name', 'NAME', 'label', 'LABEL', 'type', 'TYPE',
                'id', 'ID', 'status', 'STATUS', 'operator', 'OPERATOR',
                'well_name', 'WELL_NAME', 'api_number', 'API_NUMBER',
                'lease_name', 'LEASE_NAME', 'field_name', 'FIELD_NAME',
            ];

            // First pass: grab priority keys
            for (var k = 0; k < priorityKeys.length; k++) {
                if (props[priorityKeys[k]] !== undefined &&
                    props[priorityKeys[k]] !== null &&
                    props[priorityKeys[k]] !== '') {
                    selectedProps[priorityKeys[k]] = String(props[priorityKeys[k]]);
                }
            }

            // Second pass: fill up to 4 properties total
            var propCount = Object.keys(selectedProps).length;
            if (propCount < 4) {
                for (var j = 0; j < keys.length && propCount < 4; j++) {
                    if (!(keys[j] in selectedProps) &&
                        props[keys[j]] !== null &&
                        props[keys[j]] !== '') {
                        selectedProps[keys[j]] = String(props[keys[j]]);
                        propCount++;
                    }
                }
            }

            summary.properties = selectedProps;
            features.push(summary);
        });

        if (features.length > 0) {
            results.push({
                name: entry.name,
                feature_count: features.length,
                features: features.slice(0, 50),  // Cap at 50 features per overlay
            });
        }
    }

    return results;
}
