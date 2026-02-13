// MapSync - Preview & Adjust
// Overlays the aerial photo as a Leaflet image overlay so it zooms and pans
// together with the satellite tiles.  The user nudges the overlay bounds,
// adjusts opacity/rotation, then exports.

var PreviewAdjust = {
    imageOverlay: null,      // L.imageOverlay on the map
    active: false,
    opacity: 0.65,
    rotation: 0,             // CSS rotation applied to the Leaflet map pane
    originalBounds: null,    // {north, south, east, west} from georeferencing
    currentBounds: null,     // Current L.LatLngBounds of the overlay (after nudges)
    originalCenter: null,    // L.LatLng saved when entering adjust mode
    originalZoom: null,      // Zoom level saved when entering adjust mode
    savedZoomSnap: null,     // Original map zoomSnap (to restore later)
    savedZoomDelta: null,    // Original map zoomDelta
    aerialRotation: 0,       // OSD rotation applied to the aerial overlay
};


// ============================================================
// Full-screen mode helpers
// ============================================================

function _enterFullScreen() {
    var header = document.getElementById('header');
    var aerialPane = document.getElementById('aerial-pane');
    var gcpPanel = document.getElementById('gcp-panel');
    var metadataInfo = document.getElementById('metadataInfo');
    var mapPane = document.getElementById('map-pane');
    var mainContainer = document.getElementById('main-container');

    if (header) header.style.display = 'none';
    if (aerialPane) aerialPane.style.display = 'none';
    if (gcpPanel) gcpPanel.style.display = 'none';
    if (metadataInfo) metadataInfo.style.display = 'none';

    // Make map pane fill the entire viewport
    if (mainContainer) mainContainer.style.flex = '1';
    if (mapPane) {
        mapPane.style.flex = '1';
        mapPane.style.width = '100%';
    }
}

function _exitFullScreen() {
    var header = document.getElementById('header');
    var aerialPane = document.getElementById('aerial-pane');
    var gcpPanel = document.getElementById('gcp-panel');
    var mapPane = document.getElementById('map-pane');

    if (header) header.style.display = '';
    if (aerialPane) aerialPane.style.display = '';
    if (gcpPanel) gcpPanel.style.display = '';

    // Restore map pane sizing
    if (mapPane) {
        mapPane.style.flex = '';
        mapPane.style.width = '';
    }
}


// ============================================================
// Public API  (called from export-handler.js)
// ============================================================

function showPreviewOverlay(imageId, bounds) {
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

    // Enter full-screen mode
    _enterFullScreen();

    // Invalidate map size after layout change
    setTimeout(function () {
        map.invalidateSize();

        // Fit the map to the georeferenced bounds
        var llBounds = L.latLngBounds(
            [bounds.south, bounds.west],
            [bounds.north, bounds.east]
        );
        map.fitBounds(llBounds, { padding: [60, 60] });

        // Enable fractional zoom for precise alignment
        PreviewAdjust.savedZoomSnap = map.options.zoomSnap;
        PreviewAdjust.savedZoomDelta = map.options.zoomDelta;
        map.options.zoomSnap = 0;
        map.options.zoomDelta = 0.25;

        // Save the fitted view so Reset can restore it
        setTimeout(function () {
            PreviewAdjust.originalCenter = map.getCenter();
            PreviewAdjust.originalZoom = map.getZoom();
        }, 350);

        // Create the aerial overlay as a Leaflet image overlay
        _createAerialOverlay(bounds);

        // Show the adjustment controls panel
        _showAdjustPanel();
    }, 50);
}


function removePreviewOverlay() {
    var map = AppState.mapInstance;

    // Remove image overlay from map
    if (PreviewAdjust.imageOverlay) {
        map.removeLayer(PreviewAdjust.imageOverlay);
        PreviewAdjust.imageOverlay = null;
    }

    // Clear CSS rotation from the map pane
    _setMapRotation(0);

    // Restore original zoom behaviour
    if (PreviewAdjust.savedZoomSnap !== null) {
        map.options.zoomSnap = PreviewAdjust.savedZoomSnap;
        map.options.zoomDelta = PreviewAdjust.savedZoomDelta;
    }

    PreviewAdjust.active = false;
    PreviewAdjust.rotation = 0;
    PreviewAdjust.currentBounds = null;

    // Hide adjustment panel
    var panel = document.getElementById('adjustPanel');
    if (panel) panel.style.display = 'none';

    // Exit full-screen mode
    _exitFullScreen();

    // Invalidate map size after layout change
    setTimeout(function () {
        map.invalidateSize();
    }, 50);
}


function getAdjustedBounds() {
    if (PreviewAdjust.currentBounds) {
        return {
            north: PreviewAdjust.currentBounds.getNorth(),
            south: PreviewAdjust.currentBounds.getSouth(),
            east: PreviewAdjust.currentBounds.getEast(),
            west: PreviewAdjust.currentBounds.getWest(),
        };
    }
    return PreviewAdjust.originalBounds;
}


function getAdjustedRotation() {
    return PreviewAdjust.rotation;
}


// ============================================================
// Aerial overlay creation (Leaflet image overlay)
// ============================================================

function _createAerialOverlay(bounds) {
    var map = AppState.mapInstance;

    // Remove existing if any
    if (PreviewAdjust.imageOverlay) {
        map.removeLayer(PreviewAdjust.imageOverlay);
    }

    var llBounds = L.latLngBounds(
        [bounds.south, bounds.west],
        [bounds.north, bounds.east]
    );
    PreviewAdjust.currentBounds = llBounds;

    var overlay = L.imageOverlay(AppState.previewUrl, llBounds, {
        opacity: PreviewAdjust.opacity,
        interactive: false,
        zIndex: 600,
    }).addTo(map);

    PreviewAdjust.imageOverlay = overlay;

    // If the aerial viewer has rotation applied, mirror it on the overlay
    PreviewAdjust.aerialRotation = 0;
    if (AppState.aerialViewer) {
        var osdRot = AppState.aerialViewer.viewport.getRotation();
        if (osdRot !== 0) {
            PreviewAdjust.aerialRotation = osdRot;
            var imgEl = overlay.getElement();
            if (imgEl) {
                imgEl.style.transformOrigin = 'center center';
                imgEl.style.transform = 'rotate(' + osdRot + 'deg)';
            }
        }
    }
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
// Nudge helpers — shift the overlay bounds
// ============================================================

function _getNudgeStep() {
    // Returns a geographic offset based on current zoom level
    // At higher zooms the step is smaller for finer adjustment
    var map = AppState.mapInstance;
    var zoom = map.getZoom();
    // Approximate meters-per-pixel at this zoom, then convert ~30px worth
    var metersPerPx = 156543.03 * Math.cos(map.getCenter().lat * Math.PI / 180) / Math.pow(2, zoom);
    var metersStep = metersPerPx * 30;
    // Convert meters to approximate degrees
    return metersStep / 111320;
}

function _nudgeOverlay(dLat, dLng) {
    if (!PreviewAdjust.currentBounds || !PreviewAdjust.imageOverlay) return;

    var b = PreviewAdjust.currentBounds;
    var newBounds = L.latLngBounds(
        [b.getSouth() + dLat, b.getWest() + dLng],
        [b.getNorth() + dLat, b.getEast() + dLng]
    );
    PreviewAdjust.currentBounds = newBounds;
    PreviewAdjust.imageOverlay.setBounds(newBounds);
}


// ============================================================
// Geometry helper
// ============================================================

function _rotatePoint(px, py, cx, cy, angleDeg) {
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
// Scale helpers — grow/shrink the overlay bounds from center
// ============================================================

function _scaleOverlay(factor) {
    if (!PreviewAdjust.currentBounds || !PreviewAdjust.imageOverlay) return;

    var b = PreviewAdjust.currentBounds;
    var centerLat = (b.getNorth() + b.getSouth()) / 2;
    var centerLng = (b.getEast() + b.getWest()) / 2;
    var halfLat = (b.getNorth() - b.getSouth()) / 2 * factor;
    var halfLng = (b.getEast() - b.getWest()) / 2 * factor;

    var newBounds = L.latLngBounds(
        [centerLat - halfLat, centerLng - halfLng],
        [centerLat + halfLat, centerLng + halfLng]
    );
    PreviewAdjust.currentBounds = newBounds;
    PreviewAdjust.imageOverlay.setBounds(newBounds);
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
    // --- Opacity slider → image overlay transparency ---
    var opacitySlider = document.getElementById('adjustOpacity');
    var opacityVal = document.getElementById('adjustOpacityVal');
    if (opacitySlider) {
        opacitySlider.oninput = function () {
            var val = parseInt(this.value) / 100;
            PreviewAdjust.opacity = val;
            if (PreviewAdjust.imageOverlay) {
                PreviewAdjust.imageOverlay.setOpacity(val);
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

    // --- Nudge buttons — shift the aerial overlay, not the map ---
    var nudgeN = document.getElementById('nudgeN');
    var nudgeS = document.getElementById('nudgeS');
    var nudgeE = document.getElementById('nudgeE');
    var nudgeW = document.getElementById('nudgeW');

    if (nudgeN) nudgeN.onclick = function () { _nudgeOverlay(_getNudgeStep(), 0); };
    if (nudgeS) nudgeS.onclick = function () { _nudgeOverlay(-_getNudgeStep(), 0); };
    if (nudgeE) nudgeE.onclick = function () { _nudgeOverlay(0, _getNudgeStep()); };
    if (nudgeW) nudgeW.onclick = function () { _nudgeOverlay(0, -_getNudgeStep()); };

    // --- Scale (zoom) buttons — scale the overlay, not the map ---
    var scaleUp = document.getElementById('scaleUp');
    var scaleDn = document.getElementById('scaleDn');

    if (scaleUp) scaleUp.onclick = function () { _scaleOverlay(1.02); };
    if (scaleDn) scaleDn.onclick = function () { _scaleOverlay(0.98); };

    // --- Reset button → restore original overlay bounds and map view ---
    var resetBtn = document.getElementById('adjustReset');
    if (resetBtn) {
        resetBtn.onclick = function () {
            // Clear rotation
            PreviewAdjust.rotation = 0;
            _setMapRotation(0);
            var rotInput2 = document.getElementById('adjustRotation');
            if (rotInput2) rotInput2.value = 0;

            // Restore overlay to original bounds
            if (PreviewAdjust.originalBounds) {
                var ob = PreviewAdjust.originalBounds;
                var llBounds = L.latLngBounds(
                    [ob.south, ob.west],
                    [ob.north, ob.east]
                );
                PreviewAdjust.currentBounds = llBounds;
                if (PreviewAdjust.imageOverlay) {
                    PreviewAdjust.imageOverlay.setBounds(llBounds);
                }
            }

            // Restore original map view
            if (PreviewAdjust.originalCenter && PreviewAdjust.originalZoom !== null) {
                AppState.mapInstance.setView(
                    PreviewAdjust.originalCenter,
                    PreviewAdjust.originalZoom,
                    { animate: true }
                );
            } else if (PreviewAdjust.originalBounds) {
                var ob2 = PreviewAdjust.originalBounds;
                AppState.mapInstance.fitBounds(
                    L.latLngBounds([ob2.south, ob2.west], [ob2.north, ob2.east]),
                    { padding: [60, 60] }
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
