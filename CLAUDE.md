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
  tiff_handler.py         # TIFF validation, PNG preview, metadata extraction
  georeferencer.py        # GDAL georeferencing pipeline (gdal_translate + gdalwarp TPS)
  metadata_georeferencer.py  # Generate GCPs from metadata (center+GSD, corners)
  auto_georeferencer.py   # AI feature matching pipeline (tile download + matching)
  worldfile_parser.py     # Parse ESRI World Files (.tfw)
  footprint_parser.py     # Parse GeoJSON footprint files
  zip_handler.py          # Extract USGS ZIP packages
  exporter.py             # KMZ generation (KML + JPEG in ZIP)
  vector_handler.py       # Vector file conversion to GeoJSON (ogr2ogr)
templates/
  index.html              # Single-page app template
static/
  css/main.css            # Dark theme styling
  js/
    app.js                # App state, file upload, metadata display
    aerial-viewer.js      # OpenSeadragon wrapper, rotation, GCP marker placement
    map-viewer.js         # Leaflet map, GCP clicks, vector overlays, search
    gcp-manager.js        # GCP table management, error display
    export-handler.js     # Georeferencing trigger, results modal, KMZ download
    auto-georef.js        # Auto-georef with metadata guidance
  uploads/                # Temp TIFF storage (gitignored)
  previews/               # PNG previews (gitignored)
  exports/                # Georeferenced TIFFs & KMZ (gitignored)
  overlays/               # Temp vector files (gitignored)
  temp_extract/           # Temp ZIP extraction (gitignored)
docs/
  USGS_DOWNLOAD_GUIDE.md  # USGS download package guide (world files & footprints)
```

## Key Commands

```bash
# Install dependencies
pip3 install -r requirements.txt

# Run the app (port 5051)
python3 app.py

# GDAL must be installed separately (e.g., brew install gdal)
```

## Deployment

### Railway
- **GitHub Repository:** https://github.com/pwood26/MapSync
- **Configuration:**
  - `Aptfile` - Installs GDAL system packages (gdal-bin, libgdal-dev)
  - `Procfile` - Defines web process: `gunicorn --bind 0.0.0.0:$PORT app:app`
  - `requirements.txt` - Python dependencies including gunicorn
  - `railway.json` - Build and deploy configuration
- **Environment Variables:** None required (uses free public APIs)
- **Port Binding:** App reads `PORT` from environment, defaults to 5051 locally

## Architecture Notes

- **Preview/Original pattern:** Original TIFF stays server-side; browser works with a scaled PNG preview. Pixel coordinates are scaled back to original dimensions using `scale_factor`.
- **Metadata-guided AI georeferencing:**
  - Extracts location metadata from GDAL geotransform, USGS world files (.tfw), GeoJSON footprints, or EXIF GPS
  - Uses metadata to auto-generate bounding box for AI feature matching
  - AI feature matching (SIFT/ORB) provides sub-meter precision
  - Fallback to manual bounding box if no metadata available
  - Compatible with USGS download packages (TIFF + TFW + footprint GeoJSON)
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

- **LPA Brand Identity** — Professional oil & gas engineering aesthetic, flat and utilitarian
- **Colors:** Primary Navy `#1B2A4A`, Accent Gold `#C8922A` (use sparingly), Error Red `#B91C1C`, Success Green `#15803D`, Mid Gray `#6B7280`, Body Text `#3A3F47`
- **Typography:** Inter (headings/body), JetBrains Mono (data fields/coordinates)
- **UI:** Square corners on buttons/cards (0px border-radius), 4px on input fields only. No gradients, no drop shadows. Gold rule dividers (`1px solid #C8922A`)
- Error color coding: green `#15803D` (<50m), gold `#C8922A` (50-100m), red `#B91C1C` (>100m)
- **Password protection:** Client-side login screen gates access (password: `mapsync2024`, sessionStorage-based)
- No frontend build tools or frameworks — plain JS modules loaded via script tags
- Backend uses Flask's built-in error handling; processing functions return dicts with `success` boolean
