// MapSync - Map Viewer (Leaflet)

function initMapViewer(containerId) {
    var map = L.map(containerId, {
        center: [39.8283, -98.5795], // Center of US
        zoom: 5,
    });

    // Esri World Imagery - free satellite tiles, no API key required
    L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        {
            attribution: 'Tiles &copy; Esri',
            maxZoom: 19,
        }
    ).addTo(map);

    // Labels overlay for context
    L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}',
        {
            attribution: 'Labels &copy; Esri',
            maxZoom: 19,
            opacity: 0.8,
        }
    ).addTo(map);

    // GCP placement click handler
    map.on('click', function (e) {
        if (AppState.currentMode !== 'place_map') return;

        var lat = Math.round(e.latlng.lat * 1000000) / 1000000;
        var lon = Math.round(e.latlng.lng * 1000000) / 1000000;

        // Complete the GCP pair
        var gcp = {
            id: AppState.gcps.length + 1,
            pixelX: AppState.pendingGcp.pixelX,
            pixelY: AppState.pendingGcp.pixelY,
            lat: lat,
            lon: lon,
        };

        AppState.gcps.push(gcp);
        AppState.pendingGcp = null;
        AppState.isGeoreferenced = false;

        // Add map marker
        addMapMarker(map, lat, lon, gcp.id);

        // Update UI
        updateGcpTable();
        updateExportButton();
        setMode('navigate');
        updateGcpStatus(
            'GCP ' + gcp.id + ' placed. ' +
            (AppState.gcps.length < 5
                ? 'Need ' + (5 - AppState.gcps.length) + ' more.'
                : 'You can export or add more for accuracy.')
        );
    });

    // Search setup
    setupSearch(map);

    return map;
}

function addMapMarker(map, lat, lon, label) {
    var icon = L.divIcon({
        className: 'gcp-map-marker',
        html: '<span>' + label + '</span>',
        iconSize: [24, 24],
        iconAnchor: [12, 12],
    });

    var marker = L.marker([lat, lon], { icon: icon }).addTo(map);
    AppState.mapMarkers.push(marker);
}

function removeMapMarker(index) {
    if (index >= 0 && index < AppState.mapMarkers.length) {
        AppState.mapInstance.removeLayer(AppState.mapMarkers[index]);
        AppState.mapMarkers.splice(index, 1);
    }
}

function clearMapMarkers() {
    for (var i = 0; i < AppState.mapMarkers.length; i++) {
        AppState.mapInstance.removeLayer(AppState.mapMarkers[i]);
    }
    AppState.mapMarkers = [];
}

function renumberMapMarkers() {
    for (var i = 0; i < AppState.mapMarkers.length; i++) {
        var el = AppState.mapMarkers[i].getElement();
        if (el) {
            var span = el.querySelector('span');
            if (span) span.textContent = i + 1;
        }
    }
}

function setupSearch(map) {
    var form = document.getElementById('searchForm');
    var input = document.getElementById('searchInput');

    form.addEventListener('submit', function (e) {
        e.preventDefault();
        var query = input.value.trim();
        if (!query) return;

        // Check if input looks like lat,lon
        var latLonMatch = query.match(
            /^(-?\d+\.?\d*)\s*[,\s]\s*(-?\d+\.?\d*)$/
        );
        if (latLonMatch) {
            var lat = parseFloat(latLonMatch[1]);
            var lon = parseFloat(latLonMatch[2]);
            if (lat >= -90 && lat <= 90 && lon >= -180 && lon <= 180) {
                map.setView([lat, lon], 16);
                return;
            }
        }

        // Use Nominatim for geocoding
        searchNominatim(query, map);
    });
}

function searchNominatim(query, map) {
    var url =
        'https://nominatim.openstreetmap.org/search?format=json&q=' +
        encodeURIComponent(query) +
        '&limit=1';

    fetch(url, {
        headers: {
            'User-Agent': 'MapSync/1.0',
        },
    })
        .then(function (resp) {
            return resp.json();
        })
        .then(function (results) {
            if (results.length > 0) {
                var lat = parseFloat(results[0].lat);
                var lon = parseFloat(results[0].lon);
                map.setView([lat, lon], 14);
            } else {
                updateGcpStatus('Location not found: "' + query + '"');
            }
        })
        .catch(function (err) {
            updateGcpStatus('Search error: ' + err.message);
        });
}


// ============================================================
// Vector Overlay Functions
// ============================================================

var OVERLAY_COLORS = [
    '#C8922A', '#B91C1C', '#4A7C9B', '#15803D', '#54a0ff',
    '#6B7280', '#01a3a4', '#8B5CF6', '#D97706', '#0891B2',
];

function addVectorOverlay(overlayId, name, geojson) {
    var colorIndex = AppState.vectorOverlays.length % OVERLAY_COLORS.length;
    var color = OVERLAY_COLORS[colorIndex];

    var layer = L.geoJSON(geojson, {
        style: function () {
            return {
                color: color,
                weight: 2.5,
                opacity: 0.9,
                fillColor: color,
                fillOpacity: 0.1,
            };
        },
        pointToLayer: function (feature, latlng) {
            return L.circleMarker(latlng, {
                radius: 6,
                color: color,
                weight: 2,
                opacity: 0.9,
                fillColor: color,
                fillOpacity: 0.3,
            });
        },
        onEachFeature: function (feature, layer) {
            if (feature.properties && Object.keys(feature.properties).length > 0) {
                var html = '<div class="overlay-popup">';
                var props = feature.properties;
                var keys = Object.keys(props);
                for (var i = 0; i < Math.min(keys.length, 8); i++) {
                    var val = props[keys[i]];
                    if (val !== null && val !== '' && val !== undefined) {
                        html += '<b>' + keys[i] + ':</b> ' + val + '<br>';
                    }
                }
                html += '</div>';
                layer.bindPopup(html);
            }
        },
    }).addTo(AppState.mapInstance);

    var entry = {
        id: overlayId,
        name: name,
        layer: layer,
        visible: true,
        color: color,
    };

    AppState.vectorOverlays.push(entry);

    // Zoom to fit the overlay bounds
    var bounds = layer.getBounds();
    if (bounds.isValid()) {
        AppState.mapInstance.fitBounds(bounds, { padding: [30, 30] });
    }

    renderOverlayPanel();
}

function toggleOverlayVisibility(index) {
    var entry = AppState.vectorOverlays[index];
    if (!entry) return;

    if (entry.visible) {
        AppState.mapInstance.removeLayer(entry.layer);
        entry.visible = false;
    } else {
        AppState.mapInstance.addLayer(entry.layer);
        entry.visible = true;
    }

    renderOverlayPanel();
}

function removeOverlay(index) {
    var entry = AppState.vectorOverlays[index];
    if (!entry) return;

    if (entry.visible) {
        AppState.mapInstance.removeLayer(entry.layer);
    }

    AppState.vectorOverlays.splice(index, 1);
    renderOverlayPanel();
}

function zoomToOverlay(index) {
    var entry = AppState.vectorOverlays[index];
    if (!entry) return;

    var bounds = entry.layer.getBounds();
    if (bounds.isValid()) {
        AppState.mapInstance.fitBounds(bounds, { padding: [30, 30] });
    }
}

function renderOverlayPanel() {
    var panel = document.getElementById('overlayPanel');
    var list = document.getElementById('overlayList');

    if (AppState.vectorOverlays.length === 0) {
        panel.style.display = 'none';
        return;
    }

    panel.style.display = 'block';
    list.innerHTML = '';

    for (var i = 0; i < AppState.vectorOverlays.length; i++) {
        var entry = AppState.vectorOverlays[i];
        var item = document.createElement('div');
        item.className = 'overlay-item';
        item.innerHTML =
            '<span class="overlay-color-swatch" style="background:' + entry.color + ';"></span>' +
            '<span class="overlay-name" title="' + entry.name + '">' + entry.name + '</span>' +
            '<button class="overlay-zoom-btn" data-index="' + i + '" title="Zoom to fit">&#x1F50D;</button>' +
            '<button class="overlay-toggle-btn' + (entry.visible ? ' active' : '') + '" data-index="' + i + '" title="Toggle visibility">' +
            (entry.visible ? '&#x1F441;' : '&#x2014;') + '</button>' +
            '<button class="overlay-remove-btn" data-index="' + i + '" title="Remove">&times;</button>';
        list.appendChild(item);
    }

    // Bind event handlers
    var zoomBtns = list.querySelectorAll('.overlay-zoom-btn');
    for (var j = 0; j < zoomBtns.length; j++) {
        zoomBtns[j].addEventListener('click', function () {
            zoomToOverlay(parseInt(this.getAttribute('data-index')));
        });
    }

    var toggleBtns = list.querySelectorAll('.overlay-toggle-btn');
    for (var k = 0; k < toggleBtns.length; k++) {
        toggleBtns[k].addEventListener('click', function () {
            toggleOverlayVisibility(parseInt(this.getAttribute('data-index')));
        });
    }

    var removeBtns = list.querySelectorAll('.overlay-remove-btn');
    for (var m = 0; m < removeBtns.length; m++) {
        removeBtns[m].addEventListener('click', function () {
            removeOverlay(parseInt(this.getAttribute('data-index')));
        });
    }
}
