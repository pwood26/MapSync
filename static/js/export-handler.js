// MapSync - Export Handler

document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('exportBtn').addEventListener('click', handleExport);
});

function handleExport() {
    if (AppState.gcps.length < 5) {
        alert('You need at least 5 ground control points to export.');
        return;
    }

    showLoading('Georeferencing image...');

    // Step 1: Run georeferencing
    var gcpData = AppState.gcps.map(function (gcp) {
        return {
            id: gcp.id,
            pixel_x: gcp.pixelX,
            pixel_y: gcp.pixelY,
            lat: gcp.lat,
            lon: gcp.lon,
        };
    });

    fetch('/api/georeference', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            image_id: AppState.imageId,
            gcps: gcpData,
        }),
    })
        .then(function (resp) {
            if (!resp.ok) return resp.json().then(function (d) { throw new Error(d.error); });
            return resp.json();
        })
        .then(function (result) {
            hideLoading();
            AppState.isGeoreferenced = true;

            // Update error column in GCP table
            updateGcpErrors(result.residuals);

            // Show results modal
            showResultsModal(result);
        })
        .catch(function (err) {
            hideLoading();
            alert('Georeferencing failed: ' + err.message);
        });
}

function showResultsModal(result) {
    var rms = result.rms_error || 0;
    var residuals = result.residuals || [];

    var overlay = document.createElement('div');
    overlay.className = 'results-overlay';

    var perPointHtml = '';
    for (var i = 0; i < residuals.length; i++) {
        var r = residuals[i];
        var color = r.error_m > 100 ? '#e94560' : r.error_m > 50 ? '#f0a500' : '#4ecca3';
        perPointHtml +=
            '<span style="color:' + color + '">GCP ' + (i + 1) + ': ' + r.error_m.toFixed(1) + 'm</span>  ';
    }

    overlay.innerHTML =
        '<div class="results-modal">' +
        '  <h3>Georeferencing Complete</h3>' +
        '  <p>RMS Error: <span class="rms">' + rms.toFixed(1) + 'm</span></p>' +
        '  <p style="margin-top:8px;font-size:12px;color:#888;">Per-point errors:</p>' +
        '  <p style="font-size:12px;line-height:1.8;">' + perPointHtml + '</p>' +
        '  <p style="margin-top:12px;font-size:12px;color:#888;">' +
        (rms < 50
            ? 'Good accuracy for Google Earth overlay.'
            : rms < 200
            ? 'Moderate accuracy. Consider adjusting GCPs with high error.'
            : 'High error. Review and adjust your GCPs for better results.') +
        '  </p>' +
        '  <div class="actions">' +
        '    <button class="btn-secondary" id="resultsClose">Close</button>' +
        '    <button class="btn-primary" id="resultsDownload">Download KMZ</button>' +
        '  </div>' +
        '</div>';

    document.body.appendChild(overlay);

    document.getElementById('resultsClose').addEventListener('click', function () {
        document.body.removeChild(overlay);
    });

    document.getElementById('resultsDownload').addEventListener('click', function () {
        document.body.removeChild(overlay);
        downloadKmz();
    });

    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) {
            document.body.removeChild(overlay);
        }
    });
}

function downloadKmz() {
    showLoading('Generating KMZ file...');

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

            updateGcpStatus('KMZ file downloaded! Open it in Google Earth.');
        })
        .catch(function (err) {
            hideLoading();
            alert('Export failed: ' + err.message);
        });
}
