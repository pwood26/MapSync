// MapSync - Auto-Georeference from Metadata
// Uses USGS metadata (world file, footprint, GDAL geotransform) to place
// initial GCPs at corner and center positions. User can then fine-tune.

document.addEventListener('DOMContentLoaded', function () {
    var btn = document.getElementById('autoGeorefBtn');
    if (btn) {
        btn.addEventListener('click', onAutoGeorefClick);
    }
});

function onAutoGeorefClick() {
    if (!AppState.imageId) return;

    var metadata = AppState.metadata;
    if (!metadata || (!metadata.has_georeference && !metadata.has_gps)) {
        alert(
            'No location metadata found.\n\n' +
            'Upload a USGS ZIP package (with .tfw world file or footprint GeoJSON) ' +
            'or place GCPs manually.'
        );
        return;
    }

    // Hide the metadata bar — its hint is no longer needed
    var metaInfo = document.getElementById('metadataInfo');
    if (metaInfo) metaInfo.style.display = 'none';

    showMapLoading('Generating control points from metadata...');

    fetch('/api/auto-georeference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ image_id: AppState.imageId }),
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

            var source = data.metadata_source || 'metadata';
            updateGcpStatus(
                'Placed ' + data.gcps.length + ' control points from ' + source + '. ' +
                'Review and adjust positions, then click Export GeoTIFF.'
            );
        })
        .catch(function (err) {
            hideMapLoading();
            updateGcpStatus('Auto-georeferencing failed: ' + err.message);
            alert('Auto-georeferencing failed:\n\n' + err.message);
        });
}

// Helper function to populate GCPs from auto-georeferencing result
function populateGcpsFromAutoResult(data) {
    // Clear any existing GCPs first
    clearAllGcps();

    // Populate GCPs from the result
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
