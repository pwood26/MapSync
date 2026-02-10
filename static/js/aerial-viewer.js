// MapSync - Aerial Photo Viewer (OpenSeadragon)
// Supports: zoom, pan, free-drag rotation (Shift+drag), and GCP placement

function initAerialViewer(containerId, imageUrl) {
    // Destroy previous viewer if exists
    if (AppState.aerialViewer) {
        AppState.aerialViewer.destroy();
        AppState.aerialOverlays = [];
    }

    var viewer = OpenSeadragon({
        id: containerId,
        tileSources: {
            type: 'image',
            url: imageUrl,
        },
        showRotationControl: false,
        showNavigator: true,
        navigatorPosition: 'BOTTOM_LEFT',
        navigatorSizeRatio: 0.15,
        maxZoomPixelRatio: 6,
        minZoomImageRatio: 0.3,
        visibilityRatio: 0.5,
        constrainDuringPan: false,
        animationTime: 0.3,
        showZoomControl: false,
        showHomeControl: false,
        showFullPageControl: false,
        gestureSettingsMouse: {
            clickToZoom: false,
        },
        gestureSettingsTouch: {
            pinchRotate: true,
        },
    });

    // Add custom fullscreen toggle button
    setupFullscreenToggle(viewer, containerId);

    // GCP placement click handler
    viewer.addHandler('canvas-click', function (event) {
        if (AppState.currentMode !== 'place_aerial') return;
        event.preventDefaultAction = true;

        var webPoint = event.position;
        var viewportPoint = viewer.viewport.pointFromPixel(webPoint);
        var imagePoint = viewer.viewport.viewportToImageCoordinates(viewportPoint);

        // Scale preview coords to original image coords
        var origX = imagePoint.x * AppState.scaleFactor;
        var origY = imagePoint.y * AppState.scaleFactor;

        // Store pending GCP
        AppState.pendingGcp = {
            pixelX: Math.round(origX * 10) / 10,
            pixelY: Math.round(origY * 10) / 10,
            previewX: imagePoint.x,
            previewY: imagePoint.y,
        };

        // Add temporary marker
        addAerialMarker(viewer, imagePoint.x, imagePoint.y, AppState.gcps.length + 1);

        // Switch to map placement mode
        setMode('place_map');
    });

    // Setup all rotation controls (slider, buttons, input, Shift+drag)
    setupRotationControls(viewer);
    setupDragRotation(viewer);

    return viewer;
}

function addAerialMarker(viewer, imgX, imgY, label) {
    var marker = document.createElement('div');
    marker.className = 'gcp-marker';
    marker.textContent = label;

    var point = viewer.viewport.imageToViewportCoordinates(
        new OpenSeadragon.Point(imgX, imgY)
    );

    viewer.addOverlay({
        element: marker,
        location: point,
        placement: OpenSeadragon.Placement.CENTER,
    });

    AppState.aerialOverlays.push({
        element: marker,
        imgX: imgX,
        imgY: imgY,
    });
}

function removeAerialMarker(index) {
    if (index >= 0 && index < AppState.aerialOverlays.length) {
        var overlay = AppState.aerialOverlays[index];
        if (AppState.aerialViewer) {
            AppState.aerialViewer.removeOverlay(overlay.element);
        }
        AppState.aerialOverlays.splice(index, 1);
    }
}

function clearAerialMarkers() {
    for (var i = AppState.aerialOverlays.length - 1; i >= 0; i--) {
        if (AppState.aerialViewer) {
            AppState.aerialViewer.removeOverlay(AppState.aerialOverlays[i].element);
        }
    }
    AppState.aerialOverlays = [];
}

function renumberAerialMarkers() {
    for (var i = 0; i < AppState.aerialOverlays.length; i++) {
        AppState.aerialOverlays[i].element.textContent = i + 1;
    }
}

// --- Synced rotation update for all controls ---

function syncRotationUI(degrees) {
    var slider = document.getElementById('rotationSlider');
    var valueDisplay = document.getElementById('rotationValue');
    var input = document.getElementById('rotationInput');

    var rounded = Math.round(degrees * 10) / 10;
    slider.value = Math.round(rounded);
    valueDisplay.textContent = rounded + '\u00B0';
    input.value = rounded;
}

// --- Toolbar rotation controls (slider, buttons, input) ---

function setupRotationControls(viewer) {
    var slider = document.getElementById('rotationSlider');
    var input = document.getElementById('rotationInput');
    var rotateLeftBtn = document.getElementById('rotateLeft');
    var rotateRightBtn = document.getElementById('rotateRight');
    var resetBtn = document.getElementById('rotateReset');

    function applyRotation(degrees) {
        viewer.viewport.setRotation(degrees);
        syncRotationUI(degrees);
    }

    slider.addEventListener('input', function () {
        applyRotation(parseInt(this.value));
    });

    input.addEventListener('change', function () {
        var val = parseFloat(this.value);
        if (isNaN(val)) val = 0;
        val = Math.max(-180, Math.min(180, val));
        applyRotation(val);
    });

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') {
            this.blur();
        }
    });

    rotateLeftBtn.addEventListener('click', function () {
        var current = viewer.viewport.getRotation();
        applyRotation(current - 90);
    });

    rotateRightBtn.addEventListener('click', function () {
        var current = viewer.viewport.getRotation();
        applyRotation(current + 90);
    });

    resetBtn.addEventListener('click', function () {
        applyRotation(0);
    });
}

// --- Free-drag rotation (Shift + drag) ---

function setupDragRotation(viewer) {
    var container = viewer.canvas;
    var isDragging = false;
    var startAngle = 0;
    var startRotation = 0;

    // Calculate angle in degrees from center of container to a point
    function getAngleFromCenter(x, y) {
        var rect = container.getBoundingClientRect();
        var cx = rect.left + rect.width / 2;
        var cy = rect.top + rect.height / 2;
        return Math.atan2(y - cy, x - cx) * (180 / Math.PI);
    }

    // On mouse down with Shift held, start rotation drag
    container.addEventListener('mousedown', function (e) {
        if (!e.shiftKey) return;

        // Prevent OpenSeadragon from panning
        e.stopPropagation();
        isDragging = true;
        startAngle = getAngleFromCenter(e.clientX, e.clientY);
        startRotation = viewer.viewport.getRotation();
        container.classList.add('aerial-rotating');

        // Disable OSD mouse tracking while we rotate
        viewer.setMouseNavEnabled(false);
    });

    // On mouse move, rotate in real-time
    document.addEventListener('mousemove', function (e) {
        if (!isDragging) return;

        var currentAngle = getAngleFromCenter(e.clientX, e.clientY);
        var delta = currentAngle - startAngle;
        var newRotation = startRotation + delta;

        viewer.viewport.setRotation(newRotation);
        syncRotationUI(newRotation);
    });

    // On mouse up, finish rotation
    document.addEventListener('mouseup', function () {
        if (!isDragging) return;

        isDragging = false;
        container.classList.remove('aerial-rotating');

        // Re-enable OSD mouse navigation
        viewer.setMouseNavEnabled(true);
    });

    // Also handle Shift key release mid-drag (cancel gracefully)
    document.addEventListener('keyup', function (e) {
        if (e.key === 'Shift' && isDragging) {
            isDragging = false;
            container.classList.remove('aerial-rotating');
            viewer.setMouseNavEnabled(true);
        }
    });

    // Show visual hint when Shift is held over the aerial viewer
    container.addEventListener('mouseenter', function () {
        container.addEventListener('keydown', shiftCursorOn);
    });

    container.addEventListener('mouseleave', function () {
        container.removeEventListener('keydown', shiftCursorOn);
        container.classList.remove('aerial-rotating');
    });

    function shiftCursorOn(e) {
        if (e.key === 'Shift') {
            container.classList.add('aerial-rotating');
        }
    }

    // Global Shift keyup removes rotate cursor
    document.addEventListener('keyup', function (e) {
        if (e.key === 'Shift' && !isDragging) {
            container.classList.remove('aerial-rotating');
        }
    });
}

// --- Fullscreen toggle for aerial pane ---

function setupFullscreenToggle(viewer, containerId) {
    var viewerEl = document.getElementById(containerId);
    var pane = document.getElementById('aerial-pane');
    var btn = document.createElement('button');
    btn.className = 'aerial-fullscreen-btn';
    btn.title = 'Toggle full page view';
    btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
        '<polyline points="4,1 1,1 1,4"></polyline>' +
        '<polyline points="12,1 15,1 15,4"></polyline>' +
        '<polyline points="4,15 1,15 1,12"></polyline>' +
        '<polyline points="12,15 15,15 15,12"></polyline>' +
        '</svg>';
    viewerEl.appendChild(btn);

    var isFullPage = false;

    btn.addEventListener('click', function (e) {
        e.stopPropagation();
        isFullPage = !isFullPage;

        if (isFullPage) {
            pane.classList.add('aerial-fullpage');
            btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
                '<polyline points="1,4 4,4 4,1"></polyline>' +
                '<polyline points="15,4 12,4 12,1"></polyline>' +
                '<polyline points="1,12 4,12 4,15"></polyline>' +
                '<polyline points="15,12 12,12 12,15"></polyline>' +
                '</svg>';
            btn.title = 'Exit full page view';
        } else {
            pane.classList.remove('aerial-fullpage');
            btn.innerHTML = '<svg width="16" height="16" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">' +
                '<polyline points="4,1 1,1 1,4"></polyline>' +
                '<polyline points="12,1 15,1 15,4"></polyline>' +
                '<polyline points="4,15 1,15 1,12"></polyline>' +
                '<polyline points="12,15 15,15 15,12"></polyline>' +
                '</svg>';
            btn.title = 'Toggle full page view';
        }

        // Let OpenSeadragon recalculate layout
        setTimeout(function () {
            viewer.viewport.goHome(true);
        }, 100);
    });

    // Allow Escape key to exit fullscreen
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && isFullPage) {
            btn.click();
        }
    });
}
