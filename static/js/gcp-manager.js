// MapSync - GCP Manager

document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('addGcpBtn').addEventListener('click', function () {
        if (AppState.currentMode === 'navigate' && AppState.imageId) {
            startGcpPlacement();
        }
    });

    document.getElementById('cancelGcpBtn').addEventListener('click', function () {
        cancelGcpPlacement();
    });
});

function startGcpPlacement() {
    if (!AppState.imageId) return;
    setMode('place_aerial');
}

function cancelGcpPlacement() {
    if (AppState.currentMode === 'navigate') return;

    // If we placed an aerial marker but haven't matched it on the map, remove it
    if (AppState.currentMode === 'place_map' && AppState.pendingGcp) {
        // Remove the last aerial overlay (the pending one)
        var lastIdx = AppState.aerialOverlays.length - 1;
        if (lastIdx >= AppState.gcps.length) {
            removeAerialMarker(lastIdx);
        }
        AppState.pendingGcp = null;
    }

    setMode('navigate');
    updateGcpStatus('Placement cancelled. Click "Add GCP" to try again.');
}

function updateGcpTable() {
    var tbody = document.getElementById('gcpTableBody');
    tbody.innerHTML = '';

    for (var i = 0; i < AppState.gcps.length; i++) {
        var gcp = AppState.gcps[i];
        var tr = document.createElement('tr');
        tr.innerHTML =
            '<td>' + (i + 1) + '</td>' +
            '<td>' + gcp.pixelX.toFixed(1) + '</td>' +
            '<td>' + gcp.pixelY.toFixed(1) + '</td>' +
            '<td>' + gcp.lat.toFixed(6) + '</td>' +
            '<td>' + gcp.lon.toFixed(6) + '</td>' +
            '<td class="error-col">-</td>' +
            '<td><button class="delete-btn" data-index="' + i + '">Delete</button></td>';
        tbody.appendChild(tr);
    }

    // Bind delete buttons
    var deleteBtns = tbody.querySelectorAll('.delete-btn');
    for (var j = 0; j < deleteBtns.length; j++) {
        deleteBtns[j].addEventListener('click', function () {
            var idx = parseInt(this.getAttribute('data-index'));
            deleteGcp(idx);
        });
    }
}

function deleteGcp(index) {
    if (index < 0 || index >= AppState.gcps.length) return;

    AppState.gcps.splice(index, 1);
    AppState.isGeoreferenced = false;

    removeAerialMarker(index);
    removeMapMarker(index);

    // Renumber remaining markers
    renumberAerialMarkers();
    renumberMapMarkers();

    // Renumber GCPs
    for (var i = 0; i < AppState.gcps.length; i++) {
        AppState.gcps[i].id = i + 1;
    }

    updateGcpTable();
    updateExportButton();
    updateGcpStatus(
        AppState.gcps.length === 0
            ? 'All GCPs removed. Click "Add GCP" to start again.'
            : AppState.gcps.length + ' GCP(s) remaining.'
    );
}

function clearAllGcps() {
    AppState.gcps = [];
    AppState.pendingGcp = null;
    clearAerialMarkers();
    clearMapMarkers();
    updateGcpTable();
    updateExportButton();
}

function updateGcpErrors(residuals) {
    var rows = document.querySelectorAll('#gcpTableBody tr');
    for (var i = 0; i < rows.length; i++) {
        var errorCell = rows[i].querySelector('.error-col');
        if (residuals && residuals[i]) {
            var error = residuals[i].error_m;
            errorCell.textContent = error.toFixed(1) + 'm';
            if (error > 100) {
                errorCell.style.color = '#B91C1C';
            } else if (error > 50) {
                errorCell.style.color = '#C8922A';
            } else {
                errorCell.style.color = '#15803D';
            }
        }
    }
}
