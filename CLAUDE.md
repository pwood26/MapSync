# MapSync

Georeferencing tool for aligning aerial photos to geographic coordinates using Ground Control Points (GCPs). Users upload TIFF images, place matching points on the aerial photo and a satellite map, then export georeferenced KMZ files for Google Earth.

## Tech Stack

- **Backend:** Flask 3.0+, Python 3
- **Image Processing:** Pillow (PIL), GDAL/OGR (via subprocess)
- **Frontend:** Vanilla JS, Leaflet 1.9.4 (maps), OpenSeadragon 4.1.1 (image viewer)
- **Map Tiles:** Esri World Imagery (no API key needed)
- **Geocoding:** Nominatim (OpenStreetMap)

## Project Structure

```
app.py                    # Flask app with API routes
processing/
  tiff_handler.py         # TIFF validation & PNG preview generation
  georeferencer.py        # GDAL georeferencing pipeline (gdal_translate + gdalwarp TPS)
  exporter.py             # KMZ generation (KML + JPEG in ZIP)
  vector_handler.py       # Vector file conversion to GeoJSON (ogr2ogr)
templates/
  index.html              # Single-page app template
static/
  css/main.css            # Dark theme styling
  js/
    app.js                # App state, file upload, mode switching
    aerial-viewer.js      # OpenSeadragon wrapper, rotation, GCP marker placement
    map-viewer.js         # Leaflet map, GCP clicks, vector overlays, search
    gcp-manager.js        # GCP table management, error display
    export-handler.js     # Georeferencing trigger, results modal, KMZ download
  uploads/                # Temp TIFF storage (gitignored)
  previews/               # PNG previews (gitignored)
  exports/                # Georeferenced TIFFs & KMZ (gitignored)
  overlays/               # Temp vector files (gitignored)
```

## Key Commands

```bash
# Install dependencies
pip3 install -r requirements.txt

# Run the app (port 5051)
python3 app.py

# GDAL must be installed separately (e.g., brew install gdal)
```

## Architecture Notes

- **Preview/Original pattern:** Original TIFF stays server-side; browser works with a scaled PNG preview. Pixel coordinates are scaled back to original dimensions using `scale_factor`.
- **Two-phase GCP placement:** User clicks aerial photo first (captures pixel X/Y), then clicks satellite map (captures lat/lon). Minimum 5 GCPs required for export.
- **GDAL subprocess calls:** No Python GDAL bindings — uses `gdal_translate` (embed GCPs), `gdalwarp` (thin-plate spline transform), `gdalinfo` (read bounds), `ogr2ogr`/`ogrinfo` (vector conversion).
- **Stateless API:** All app state lives client-side in the `AppState` object. Each API call is independent.
- **Max upload:** 500 MB.

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/upload` | Upload and validate TIFF, create preview |
| POST | `/api/overlay/upload` | Upload vector file, convert to GeoJSON |
| POST | `/api/georeference` | Run GDAL georeferencing, return residuals |
| POST | `/api/export` | Generate KMZ from georeferenced TIFF |
| GET | `/api/download/<filename>` | Download generated KMZ |

## Style Conventions

- Dark theme UI with accent colors: `#4ecca3` (green/success), `#e94560` (red/alert), `#48dbfb` (cyan/info)
- Error color coding: green (<50m), yellow (50-100m), red (>100m)
- No frontend build tools or frameworks — plain JS modules loaded via script tags
- Backend uses Flask's built-in error handling; processing functions return dicts with `success` boolean
