# MapSync

Georeferencing tool for aligning aerial photos to geographic coordinates using Ground Control Points (GCPs). Users upload TIFF images, place matching points on the aerial photo and a satellite map, then export georeferenced KMZ files for Google Earth.

![MapSync Interface](https://img.shields.io/badge/status-active-success)
![Python](https://img.shields.io/badge/python-3.10+-blue)
![Flask](https://img.shields.io/badge/flask-3.0+-green)

## Features

- 📸 Upload and process large TIFF aerial photos (up to 500MB)
- 🗺️ Interactive dual-view: OpenSeadragon image viewer + Leaflet satellite map
- 📍 Ground Control Point placement with error visualization
- 🌐 GDAL-powered georeferencing using thin-plate spline transformation
- 📦 Export to KMZ format for Google Earth compatibility
- 🎯 Vector overlay support (Shapefile, GeoJSON, KML)
- 🔍 Location search powered by Nominatim

## Tech Stack

- **Backend:** Flask 3.0+, Python 3
- **Image Processing:** Pillow (PIL), GDAL/OGR
- **Frontend:** Vanilla JS, Leaflet 1.9.4, OpenSeadragon 4.1.1
- **Map Tiles:** Esri World Imagery
- **Geocoding:** Nominatim (OpenStreetMap)

## Installation

### Prerequisites

- Python 3.10+
- GDAL installed on your system

**macOS:**
```bash
brew install gdal
```

**Ubuntu/Debian:**
```bash
sudo apt-get install gdal-bin python3-gdal
```

### Setup

```bash
# Clone the repository
git clone https://github.com/pwood26/MapSync.git
cd MapSync

# Install Python dependencies
pip install -r requirements.txt

# Run the application
python app.py
```

The app will be available at `http://localhost:5051`

## Usage

1. **Upload TIFF:** Click "Upload TIFF" and select your aerial photo
2. **Place GCPs:** Click on the aerial photo, then click the corresponding location on the satellite map
3. **Add Points:** Repeat until you have at least 5 Ground Control Points
4. **Georeference:** Click "Georeference Image" to process
5. **Review Errors:** Check residual errors (green < 50m, yellow 50-100m, red > 100m)
6. **Export:** Click "Export KMZ" to download for Google Earth

## Deployment

### Railway

[![Deploy on Railway](https://railway.app/button.svg)](https://railway.app/new)

This project includes Railway configuration files:
- `railway.json` - Railway service configuration
- `nixpacks.toml` - GDAL dependency installation
- `Procfile` - Process commands

### Environment Variables

No environment variables required for basic operation. All processing is done server-side.

## Project Structure

```
MapSync/
├── app.py                    # Flask application and API routes
├── processing/
│   ├── tiff_handler.py       # TIFF validation & preview generation
│   ├── georeferencer.py      # GDAL georeferencing pipeline
│   ├── exporter.py           # KMZ generation
│   └── vector_handler.py     # Vector file conversion
├── static/
│   ├── css/main.css          # Dark theme styling
│   └── js/                   # Frontend modules
├── templates/
│   └── index.html            # Single-page application
└── requirements.txt
```

## API Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/upload` | Upload and validate TIFF |
| POST | `/api/overlay/upload` | Upload vector file |
| POST | `/api/georeference` | Run georeferencing |
| POST | `/api/export` | Generate KMZ |
| GET | `/api/download/<filename>` | Download KMZ |

## License

MIT

## Contributing

Contributions welcome! Please open an issue or submit a pull request.

## Acknowledgments

- Built with [Flask](https://flask.palletsprojects.com/)
- Mapping powered by [Leaflet](https://leafletjs.com/) and [OpenSeadragon](https://openseadragon.github.io/)
- Georeferencing via [GDAL](https://gdal.org/)
