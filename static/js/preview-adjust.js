// MapSync - Preview & Adjust
// Overlays the aerial photo on top of the Leaflet map as a static,
// semi-transparent image.  The user drags / zooms / rotates the satellite
// map underneath until it aligns with the aerial, then exports.

var PreviewAdjust = {
    aerialOverlayEl: null,   // <img> element overlaid on the map pane
    active: false,
    opacity: 0.65,
    rotation: 0,             // CSS rotation applied to the Leaflet map pane
    originalBounds: null,    // {north, south, east, west} from georeferencing
    originalCenter: null,    // L.LatLng saved when entering adjust mode
    originalZoom: null,      // Zoom level saved when entering adjust mode
    savedZoomSnap: null,     // Original map zoomSnap (to restore later)
    savedZoomDelta: null,    // Original map zoomDelta
    aerialRotation: 0,       // OSD rotation applied to the aerial overlay img
};


// ============================================================
// Public API  (called from export-handler.js)
// ============================================================

function showPreviewOverlay(imageId, bounds) {
    /**
     * Show the aerial photo as a fixed overlay on top of the Leaflet map.
     * The user then manipulates the map underneath to align.
     *
     * @param {string} imageId - The image ID
     * @param {object} bounds  - {north, south, east, west} from georeferencing
     */
    var map = AppState.mapInstance;

    PreviewAdjust.originalBounds = {
        north: bounds.north,
        south: bounds.south,
        east: bounds.east,
        west: bounds.west,
    };
    PreviewAdjust.rotation = 0;
    PreviewAdjust.opacity = 0.65;
    PreviewAdjust.active = true;

    // Fit the map to the georeferenced bounds first so the satellite is
    // roughly aligned before we overlay the aerial photo.
    var llBounds = L.latLngBounds(
        [bounds.south, bounds.west],
        [bounds.north, bounds.east]
    );
    map.fitBounds(llBounds, { padding: [40, 40] });

    // Enable fractional zoom for precise alignment
    PreviewAdjust.savedZoomSnap = map.options.zoomSnap;
    PreviewAdjust.savedZoomDelta = map.options.zoomDelta;
    map.options.zoomSnap = 0;
    map.options.zoomDelta = 0.25;

    // Save the fitted view so Reset can restore it
    // (use timeout to let fitBounds settle)
    setTimeout(function () {
        PreviewAdjust.originalCenter = map.getCenter();
        PreviewAdjust.originalZoom = map.getZoom();
    }, 350);

    // Create the aerial overlay <img> on top of the map
    _createAerialOverlay();

    // Show the adjustment controls panel
    _showAdjustPanel();
}


function removePreviewOverlay() {
    /**
     * Remove the aerial overlay and clean up all preview state.
     */
    // Remove aerial overlay element
    if (PreviewAdjust.aerialOverlayEl && PreviewAdjust.aerialOverlayEl.parentNode) {
        PreviewAdjust.aerialOverlayEl.parentNode.removeChild(PreviewAdjust.aerialOverlayEl);
    }
    PreviewAdjust.aerialOverlayEl = null;

    // Clear CSS rotation from the map pane
    _setMapRotation(0);

    // Restore original zoom behaviour
    var map = AppState.mapInstance;
    if (PreviewAdjust.savedZoomSnap !== null) {
        map.options.zoomSnap = PreviewAdjust.savedZoomSnap;
        map.options.zoomDelta = PreviewAdjust.savedZoomDelta;
    }

    PreviewAdjust.active = false;
    PreviewAdjust.rotation = 0;

    // Hide adjustment panel
    var panel = document.getElementById('adjustPanel');
    if (panel) panel.style.display = 'none';
}


function getAdjustedBounds() {
    /**
     * Compute the geographic bounds that correspond to the aerial image
     * as currently displayed over the map.
     *
     * The image uses object-fit: contain, so we calculate its rendered
     * rectangle, optionally account for CSS rotation, and convert the
     * four corners to lat/lng via Leaflet's containerPointToLatLng.
     *
     * @returns {object} {north, south, east, west}
     */
    var map = AppState.mapInstance;
    var container = map.getContainer();
    var containerW = container.clientWidth;
    var containerH = container.clientHeight;

    // Calculate the rendered image rectangle (object-fit: contain)
    var imgEl = PreviewAdjust.aerialOverlayEl;
    if (!imgEl) return PreviewAdjust.originalBounds;

    var imgNatW = imgEl.naturalWidth || 1;
    var imgNatH = imgEl.naturalHeight || 1;
    var imgAspect = imgNatW / imgNatH;
    var containerAspect = containerW / containerH;

    var renderW, renderH, offsetX, offsetY;
    if (imgAspect > containerAspect) {
        // Image wider than container → letterbox top/bottom
        renderW = containerW;
        renderH = containerW / imgAspect;
        offsetX = 0;
        offsetY = (containerH - renderH) / 2;
    } else {
        // Image taller than container → letterbox left/right
        renderH = containerH;
        renderW = containerH * imgAspect;
        offsetX = (containerW - renderW) / 2;
        offsetY = 0;
    }

    // Four corners of the rendered aerial image in container-pixel coords
    var corners = [
        { x: offsetX,            y: offsetY },              // top-left
        { x: offsetX + renderW,  y: offsetY },              // top-right
        { x: offsetX,            y: offsetY + renderH },    // bottom-left
        { x: offsetX + renderW,  y: offsetY + renderH },    // bottom-right
    ];

    // If the map pane is CSS-rotated, transform the corners through the
    // inverse rotation so Leaflet's containerPointToLatLng gives correct
    // geographic positions.
    var rot = PreviewAdjust.rotation;
    if (rot !== 0) {
        var cx = containerW / 2;
        var cy = containerH / 2;
        for (var i = 0; i < corners.length; i++) {
            corners[i] = _rotatePoint(corners[i].x, corners[i].y, cx, cy, -rot);
        }
    }

    // Convert to geographic coordinates
    var lats = [];
    var lngs = [];
    for (var j = 0; j < corners.length; j++) {
        var ll = map.containerPointToLatLng(L.point(corners[j].x, corners[j].y));
        lats.push(ll.lat);
        lngs.push(ll.lng);
    }

    return {
        north: Math.max.apply(null, lats),
        south: Math.min.apply(null, lats),
        east:  Math.max.apply(null, lngs),
        west:  Math.min.apply(null, lngs),
    };
}


function getAdjustedRotation() {
    return PreviewAdjust.rotation;
}


// ============================================================
// Aerial overlay creation
// ============================================================

function _createAerialOverlay() {
    // Remove existing if any
    if (PreviewAdjust.aerialOverlayEl && PreviewAdjust.aerialOverlayEl.parentNode) {
        PreviewAdjust.aerialOverlayEl.parentNode.removeChild(PreviewAdjust.aerialOverlayEl);
    }

    var img = document.createElement('img');
    img.className = 'aerial-preview-overlay';
    img.src = AppState.previewUrl;
    img.style.opacity = PreviewAdjust.opacity;
    img.draggable = false;

    // If the aerial viewer has rotation applied, mirror it on the overlay
    // so the overlay matches what the user sees in the aerial pane.
    PreviewAdjust.aerialRotation = 0;
    if (AppState.aerialViewer) {
        var osdRot = AppState.aerialViewer.viewport.getRotation();
        if (osdRot !== 0) {
            PreviewAdjust.aerialRotation = osdRot;
            img.style.transform = 'rotate(' + osdRot + 'deg)';
        }
    }

    // Append to the map viewer container so it sits on top of the map
    var mapViewer = document.getElementById('map-viewer');
    if (mapViewer) {
        mapViewer.appendChild(img);
    }

    PreviewAdjust.aerialOverlayEl = img;
}


// ============================================================
// Map rotation via CSS transform
// ============================================================

function _setMapRotation(degrees) {
    var map = AppState.mapInstance;
    if (!map) return;

    var mapPane = map.getPane('mapPane');
    if (!mapPane) return;

    if (degrees === 0) {
        mapPane.style.transform = '';
        mapPane.style.transformOrigin = '';
    } else {
        mapPane.style.transformOrigin = 'center center';
        mapPane.style.transform = 'rotate(' + degrees + 'deg)';
    }
}


// ============================================================
// Nudge helpers (pan the map, inverted so arrows show satellite direction)
// ============================================================

function _getNudgeStep() {
    /**
     * Calculate a nudge step in pixels based on current map zoom.
     * Returns a pixel amount suitable for map.panBy().
     */
    return 30; // 30 pixels per nudge press — consistent and intuitive
}

function _nudgeMap(dx, dy) {
    /**
     * Pan the map by pixel offsets.
     * Positive dx = pan right, positive dy = pan down.
     */
    AppState.mapInstance.panBy([dx, dy], { animate: false });
}


// ============================================================
// Geometry helper
// ============================================================

function _rotatePoint(px, py, cx, cy, angleDeg) {
    /**
     * Rotate point (px, py) around center (cx, cy) by angleDeg degrees.
     * Returns {x, y}.
     */
    var rad = angleDeg * Math.PI / 180;
    var cosA = Math.cos(rad);
    var sinA = Math.sin(rad);
    var dx = px - cx;
    var dy = py - cy;
    return {
        x: cx + dx * cosA - dy * sinA,
        y: cy + dx * sinA + dy * cosA,
    };
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

    // Bind control events
    _bindAdjustControls();
}


function _bindAdjustControls() {
    // --- Opacity slider → aerial overlay transparency ---
    var opacitySlider = document.getElementById('adjustOpacity');
    var opacityVal = document.getElementById('adjustOpacityVal');
    if (opacitySlider) {
        opacitySlider.oninput = function () {
            var val = parseInt(this.value) / 100;
            PreviewAdjust.opacity = val;
            if (PreviewAdjust.aerialOverlayEl) {
                PreviewAdjust.aerialOverlayEl.style.opacity = val;
            }
            if (opacityVal) opacityVal.textContent = this.value + '%';
        };
    }

    // --- Rotation input → CSS rotation on the map pane ---
    var rotInput = document.getElementById('adjustRotation');
    if (rotInput) {
        rotInput.oninput = function () {
            var deg = parseFloat(this.value) || 0;
            PreviewAdjust.rotation = deg;
            _setMapRotation(deg);
        };
    }

    // --- Nudge buttons (arrows show satellite movement direction) ---
    // ↑ = satellite moves up = map pans down (positive panBy Y)
    var nudgeN = document.getElementById('nudgeN');
    var nudgeS = document.getElementById('nudgeS');
    var nudgeE = document.getElementById('nudgeE');
    var nudgeW = document.getElementById('nudgeW');
    var step = _getNudgeStep;

    // panBy([dx, dy]): positive dy shifts viewport down → content/satellite moves UP
    if (nudgeN) nudgeN.onclick = function () { _nudgeMap(0, step()); };
    if (nudgeS) nudgeS.onclick = function () { _nudgeMap(0, -step()); };
    if (nudgeE) nudgeE.onclick = function () { _nudgeMap(-step(), 0); };
    if (nudgeW) nudgeW.onclick = function () { _nudgeMap(step(), 0); };

    // --- Scale (zoom) buttons ---
    var scaleUp = document.getElementById('scaleUp');
    var scaleDn = document.getElementById('scaleDn');

    if (scaleUp) scaleUp.onclick = function () { AppState.mapInstance.zoomIn(0.5); };
    if (scaleDn) scaleDn.onclick = function () { AppState.mapInstance.zoomOut(0.5); };

    // --- Reset button → restore original map view ---
    var resetBtn = document.getElementById('adjustReset');
    if (resetBtn) {
        resetBtn.onclick = function () {
            // Clear rotation
            PreviewAdjust.rotation = 0;
            _setMapRotation(0);
            var rotInput2 = document.getElementById('adjustRotation');
            if (rotInput2) rotInput2.value = 0;

            // Restore original map view
            if (PreviewAdjust.originalCenter && PreviewAdjust.originalZoom !== null) {
                AppState.mapInstance.setView(
                    PreviewAdjust.originalCenter,
                    PreviewAdjust.originalZoom,
                    { animate: true }
                );
            } else if (PreviewAdjust.originalBounds) {
                var ob = PreviewAdjust.originalBounds;
                AppState.mapInstance.fitBounds(
                    L.latLngBounds([ob.south, ob.west], [ob.north, ob.east]),
                    { padding: [40, 40] }
                );
            }
        };
    }

    // --- Accept button (export with adjusted bounds) ---
    var acceptBtn = document.getElementById('adjustAccept');
    if (acceptBtn) {
        acceptBtn.onclick = function () {
            downloadKmzWithAdjustments();
        };
    }

    // --- Cancel button (discard adjustments, close preview) ---
    var cancelBtn = document.getElementById('adjustCancel');
    if (cancelBtn) {
        cancelBtn.onclick = function () {
            removePreviewOverlay();
        };
    }
}


// ============================================================
// Export with adjustments
// ============================================================

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
