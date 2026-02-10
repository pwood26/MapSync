// MapSync - Preview & Adjust
// Shows georeferenced image on the Leaflet map as a draggable overlay
// with controls for nudging position, adjusting opacity, and rotation.

var PreviewAdjust = {
    overlay: null,          // Leaflet image overlay
    bounds: null,           // Current L.LatLngBounds
    originalBounds: null,   // Original bounds from georeferencing
    rotation: 0,            // Rotation in degrees
    opacity: 0.65,          // Overlay opacity
    imageUrl: null,         // URL of the preview image
    active: false,          // Whether preview mode is active
    dragStartLatLng: null,  // For drag handling
    isDragging: false,
};


function showPreviewOverlay(imageId, bounds) {
    /**
     * Show the georeferenced image on the Leaflet map for adjustment.
     * Called after georeferencing completes successfully.
     *
     * @param {string} imageId - The image ID
     * @param {object} bounds - {north, south, east, west} from georeferencing
     */
    PreviewAdjust.imageUrl = '/api/preview-overlay/' + imageId;
    PreviewAdjust.originalBounds = {
        north: bounds.north,
        south: bounds.south,
        east: bounds.east,
        west: bounds.west,
    };
    PreviewAdjust.bounds = L.latLngBounds(
        [bounds.south, bounds.west],  // SW corner
        [bounds.north, bounds.east]   // NE corner
    );
    PreviewAdjust.rotation = 0;
    PreviewAdjust.opacity = 0.65;
    PreviewAdjust.active = true;

    // Create image overlay on Leaflet map
    if (PreviewAdjust.overlay) {
        AppState.mapInstance.removeLayer(PreviewAdjust.overlay);
    }

    PreviewAdjust.overlay = L.imageOverlay(
        PreviewAdjust.imageUrl,
        PreviewAdjust.bounds,
        {
            opacity: PreviewAdjust.opacity,
            interactive: true,
            zIndex: 500,
        }
    ).addTo(AppState.mapInstance);

    // Fit map to show the overlay
    AppState.mapInstance.fitBounds(PreviewAdjust.bounds, { padding: [40, 40] });

    // Setup drag interaction on the overlay
    _setupOverlayDrag();

    // Show the adjustment controls panel
    _showAdjustPanel();
}


function removePreviewOverlay() {
    /**
     * Remove the preview overlay and adjustment controls.
     */
    if (PreviewAdjust.overlay) {
        AppState.mapInstance.removeLayer(PreviewAdjust.overlay);
        PreviewAdjust.overlay = null;
    }
    PreviewAdjust.active = false;

    // Remove drag handlers
    _removeOverlayDrag();

    // Hide adjustment panel
    var panel = document.getElementById('adjustPanel');
    if (panel) panel.style.display = 'none';
}


function getAdjustedBounds() {
    /**
     * Get the current adjusted bounds as a plain object.
     * @returns {object} {north, south, east, west}
     */
    if (!PreviewAdjust.bounds) return null;

    return {
        north: PreviewAdjust.bounds.getNorth(),
        south: PreviewAdjust.bounds.getSouth(),
        east: PreviewAdjust.bounds.getEast(),
        west: PreviewAdjust.bounds.getWest(),
    };
}


function getAdjustedRotation() {
    return PreviewAdjust.rotation;
}


// ============================================================
// Nudge / shift controls
// ============================================================

function _nudgeOverlay(dLat, dLon) {
    /**
     * Shift the overlay by the given lat/lon offsets.
     */
    if (!PreviewAdjust.bounds || !PreviewAdjust.overlay) return;

    var sw = PreviewAdjust.bounds.getSouthWest();
    var ne = PreviewAdjust.bounds.getNorthEast();

    PreviewAdjust.bounds = L.latLngBounds(
        [sw.lat + dLat, sw.lng + dLon],
        [ne.lat + dLat, ne.lng + dLon]
    );

    PreviewAdjust.overlay.setBounds(PreviewAdjust.bounds);
}


function _scaleOverlay(factor) {
    /**
     * Scale the overlay bounds from center by the given factor.
     */
    if (!PreviewAdjust.bounds || !PreviewAdjust.overlay) return;

    var center = PreviewAdjust.bounds.getCenter();
    var sw = PreviewAdjust.bounds.getSouthWest();
    var ne = PreviewAdjust.bounds.getNorthEast();

    var halfLatSpan = (ne.lat - sw.lat) / 2;
    var halfLonSpan = (ne.lng - sw.lng) / 2;

    PreviewAdjust.bounds = L.latLngBounds(
        [center.lat - halfLatSpan * factor, center.lng - halfLonSpan * factor],
        [center.lat + halfLatSpan * factor, center.lng + halfLonSpan * factor]
    );

    PreviewAdjust.overlay.setBounds(PreviewAdjust.bounds);
}


function _getNudgeStep() {
    /**
     * Calculate a nudge step based on current map zoom level.
     * At high zoom (close up), smaller steps; at low zoom, larger steps.
     */
    var zoom = AppState.mapInstance.getZoom();
    // Base step in degrees, halved for each zoom level above 10
    var baseDeg = 0.001;  // ~111 meters at equator
    var step = baseDeg * Math.pow(2, 14 - zoom);
    return Math.max(0.0000001, step);
}


// ============================================================
// Drag interaction
// ============================================================

var _dragHandlers = {};

function _setupOverlayDrag() {
    var map = AppState.mapInstance;

    _dragHandlers.mousedown = function (e) {
        if (!PreviewAdjust.active) return;

        // Check if click is within overlay bounds
        if (!PreviewAdjust.bounds.contains(e.latlng)) return;

        // Don't intercept if in GCP placement mode
        if (AppState.currentMode !== 'navigate') return;

        PreviewAdjust.isDragging = true;
        PreviewAdjust.dragStartLatLng = e.latlng;
        map.dragging.disable();

        L.DomUtil.addClass(map.getContainer(), 'preview-dragging');
    };

    _dragHandlers.mousemove = function (e) {
        if (!PreviewAdjust.isDragging || !PreviewAdjust.dragStartLatLng) return;

        var dLat = e.latlng.lat - PreviewAdjust.dragStartLatLng.lat;
        var dLon = e.latlng.lng - PreviewAdjust.dragStartLatLng.lng;

        _nudgeOverlay(dLat, dLon);
        PreviewAdjust.dragStartLatLng = e.latlng;
    };

    _dragHandlers.mouseup = function () {
        if (!PreviewAdjust.isDragging) return;

        PreviewAdjust.isDragging = false;
        PreviewAdjust.dragStartLatLng = null;
        map.dragging.enable();

        L.DomUtil.removeClass(map.getContainer(), 'preview-dragging');
    };

    map.on('mousedown', _dragHandlers.mousedown);
    map.on('mousemove', _dragHandlers.mousemove);
    map.on('mouseup', _dragHandlers.mouseup);
}

function _removeOverlayDrag() {
    var map = AppState.mapInstance;
    if (_dragHandlers.mousedown) map.off('mousedown', _dragHandlers.mousedown);
    if (_dragHandlers.mousemove) map.off('mousemove', _dragHandlers.mousemove);
    if (_dragHandlers.mouseup) map.off('mouseup', _dragHandlers.mouseup);

    L.DomUtil.removeClass(map.getContainer(), 'preview-dragging');
    _dragHandlers = {};
}


// ============================================================
// Adjustment panel UI
// ============================================================

function _showAdjustPanel() {
    var panel = document.getElementById('adjustPanel');
    if (!panel) return;

    panel.style.display = 'block';

    // Set initial opacity value
    var opacitySlider = document.getElementById('adjustOpacity');
    var opacityVal = document.getElementById('adjustOpacityVal');
    if (opacitySlider) {
        opacitySlider.value = Math.round(PreviewAdjust.opacity * 100);
        if (opacityVal) opacityVal.textContent = Math.round(PreviewAdjust.opacity * 100) + '%';
    }

    // Set initial rotation value
    var rotInput = document.getElementById('adjustRotation');
    if (rotInput) rotInput.value = 0;

    // Bind control events (remove old ones first to avoid duplicates)
    _bindAdjustControls();
}

function _bindAdjustControls() {
    // Opacity slider
    var opacitySlider = document.getElementById('adjustOpacity');
    var opacityVal = document.getElementById('adjustOpacityVal');
    if (opacitySlider) {
        opacitySlider.oninput = function () {
            var val = parseInt(this.value) / 100;
            PreviewAdjust.opacity = val;
            if (PreviewAdjust.overlay) {
                PreviewAdjust.overlay.setOpacity(val);
            }
            if (opacityVal) opacityVal.textContent = this.value + '%';
        };
    }

    // Rotation input
    var rotInput = document.getElementById('adjustRotation');
    if (rotInput) {
        rotInput.onchange = function () {
            PreviewAdjust.rotation = parseFloat(this.value) || 0;
        };
    }

    // Nudge buttons
    var nudgeN = document.getElementById('nudgeN');
    var nudgeS = document.getElementById('nudgeS');
    var nudgeE = document.getElementById('nudgeE');
    var nudgeW = document.getElementById('nudgeW');

    if (nudgeN) nudgeN.onclick = function () { _nudgeOverlay(_getNudgeStep(), 0); };
    if (nudgeS) nudgeS.onclick = function () { _nudgeOverlay(-_getNudgeStep(), 0); };
    if (nudgeE) nudgeE.onclick = function () { _nudgeOverlay(0, _getNudgeStep()); };
    if (nudgeW) nudgeW.onclick = function () { _nudgeOverlay(0, -_getNudgeStep()); };

    // Scale buttons
    var scaleUp = document.getElementById('scaleUp');
    var scaleDn = document.getElementById('scaleDn');

    if (scaleUp) scaleUp.onclick = function () { _scaleOverlay(1.02); };
    if (scaleDn) scaleDn.onclick = function () { _scaleOverlay(0.98); };

    // Reset button
    var resetBtn = document.getElementById('adjustReset');
    if (resetBtn) {
        resetBtn.onclick = function () {
            if (!PreviewAdjust.originalBounds) return;
            var ob = PreviewAdjust.originalBounds;
            PreviewAdjust.bounds = L.latLngBounds(
                [ob.south, ob.west],
                [ob.north, ob.east]
            );
            PreviewAdjust.rotation = 0;
            if (PreviewAdjust.overlay) {
                PreviewAdjust.overlay.setBounds(PreviewAdjust.bounds);
            }
            var rotInput2 = document.getElementById('adjustRotation');
            if (rotInput2) rotInput2.value = 0;
            AppState.mapInstance.fitBounds(PreviewAdjust.bounds, { padding: [40, 40] });
        };
    }

    // Accept button (export with adjusted bounds)
    var acceptBtn = document.getElementById('adjustAccept');
    if (acceptBtn) {
        acceptBtn.onclick = function () {
            downloadKmzWithAdjustments();
        };
    }

    // Cancel button (discard adjustments, close preview)
    var cancelBtn = document.getElementById('adjustCancel');
    if (cancelBtn) {
        cancelBtn.onclick = function () {
            removePreviewOverlay();
        };
    }
}


function downloadKmzWithAdjustments() {
    /**
     * Export KMZ with the user's adjusted bounds and rotation.
     */
    var adjustedBounds = getAdjustedBounds();
    var rotation = getAdjustedRotation();

    showLoading('Generating KMZ with adjustments...');

    fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            image_id: AppState.imageId,
            adjusted_bounds: adjustedBounds,
            rotation: rotation,
        }),
    })
        .then(function (resp) {
            if (!resp.ok) return resp.json().then(function (d) { throw new Error(d.error); });
            return resp.json();
        })
        .then(function (result) {
            hideLoading();

            // Trigger download
            var a = document.createElement('a');
            a.href = result.download_url;
            a.download = '';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);

            // Clean up preview overlay
            removePreviewOverlay();

            updateGcpStatus('KMZ file downloaded with adjustments! Open it in Google Earth.');
        })
        .catch(function (err) {
            hideLoading();
            alert('Export failed: ' + err.message);
        });
}
