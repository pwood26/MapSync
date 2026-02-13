// MapSync - Preview
// Overlays the aerial photo as a Leaflet image overlay so it zooms and pans
// together with the satellite tiles.  View-only — the user inspects alignment
// via opacity, then exports or goes back to edit GCPs.

var PreviewAdjust = {
    imageOverlay: null,      // L.imageOverlay on the map
    active: false,
    opacity: 0.65,
    originalBounds: null,    // {north, south, east, west} from georeferencing
    originalCenter: null,    // L.LatLng saved when entering preview mode
    originalZoom: null,      // Zoom level saved when entering preview mode
    savedZoomSnap: null,     // Original map zoomSnap (to restore later)
    savedZoomDelta: null,    // Original map zoomDelta
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

        // Enable fractional zoom for precise inspection
        PreviewAdjust.savedZoomSnap = map.options.zoomSnap;
        PreviewAdjust.savedZoomDelta = map.options.zoomDelta;
        map.options.zoomSnap = 0;
        map.options.zoomDelta = 0.25;

        // Save the fitted view so we can restore on close
        setTimeout(function () {
            PreviewAdjust.originalCenter = map.getCenter();
            PreviewAdjust.originalZoom = map.getZoom();
        }, 350);

        // Create the aerial overlay as a Leaflet image overlay
        _createAerialOverlay(bounds);

        // Show the preview panel
        _showPreviewPanel();
    }, 50);
}


function removePreviewOverlay() {
    var map = AppState.mapInstance;

    // Remove image overlay from map
    if (PreviewAdjust.imageOverlay) {
        map.removeLayer(PreviewAdjust.imageOverlay);
        PreviewAdjust.imageOverlay = null;
    }

    // Restore original zoom behaviour
    if (PreviewAdjust.savedZoomSnap !== null) {
        map.options.zoomSnap = PreviewAdjust.savedZoomSnap;
        map.options.zoomDelta = PreviewAdjust.savedZoomDelta;
    }

    PreviewAdjust.active = false;

    // Hide preview panel
    var panel = document.getElementById('adjustPanel');
    if (panel) panel.style.display = 'none';

    // Exit full-screen mode
    _exitFullScreen();

    // Invalidate map size after layout change
    setTimeout(function () {
        map.invalidateSize();
    }, 50);
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

    var overlay = L.imageOverlay(AppState.previewUrl, llBounds, {
        opacity: PreviewAdjust.opacity,
        interactive: false,
        zIndex: 600,
    }).addTo(map);

    PreviewAdjust.imageOverlay = overlay;

    // If the aerial viewer has rotation applied, mirror it on the overlay
    if (AppState.aerialViewer) {
        var osdRot = AppState.aerialViewer.viewport.getRotation();
        if (osdRot !== 0) {
            var imgEl = overlay.getElement();
            if (imgEl) {
                imgEl.style.transformOrigin = 'center center';
                imgEl.style.transform = 'rotate(' + osdRot + 'deg)';
            }
        }
    }
}


// ============================================================
// Preview panel UI
// ============================================================

function _showPreviewPanel() {
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

    // Bind control events
    _bindPreviewControls();
}


function _bindPreviewControls() {
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

    // --- Export button → download KMZ with original georeferenced bounds ---
    var acceptBtn = document.getElementById('adjustAccept');
    if (acceptBtn) {
        acceptBtn.onclick = function () {
            _downloadKmz();
        };
    }

    // --- Edit GCPs button → close preview, return to GCP editing ---
    var cancelBtn = document.getElementById('adjustCancel');
    if (cancelBtn) {
        cancelBtn.onclick = function () {
            removePreviewOverlay();
        };
    }
}


// ============================================================
// Export KMZ (uses original georeferenced bounds, no adjustments)
// ============================================================

function _downloadKmz() {
    showLoading('Generating KMZ...');

    fetch('/api/export', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            image_id: AppState.imageId,
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

            updateGcpStatus('KMZ downloaded! Open it in Google Earth.');
        })
        .catch(function (err) {
            hideLoading();
            alert('Export failed: ' + err.message);
        });
}
