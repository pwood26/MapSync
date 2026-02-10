# USGS Download Package Guide

This guide explains how to use USGS aerial imagery download packages with MapSync for automatic georeferencing.

---

## 📦 USGS Download Package Format

When you download aerial imagery from USGS EarthExplorer, you receive a ZIP file containing:

```
AR1131860010276.zip/
├── AR1131860010276.tif              # The aerial photograph
├── AR1131860010276.tfw              # World file for georeferencing
├── AR1131860010276_footprint.geojson # Spatial footprint boundary
└── README.txt                        # Usage instructions
```

---

## 🚀 Quick Start

### **Option 1: Upload Entire ZIP Package** (✅ Easiest!)

1. **Download ZIP from USGS** (don't extract it!)
2. **Upload the ZIP file** directly to MapSync
3. **MapSync automatically**:
   - Extracts the TIFF
   - Finds the world file (.tfw)
   - Detects the footprint GeoJSON
4. **See the metadata banner**: "📍 Location metadata detected (World File)"
5. **Click "Auto-Georeference"** → Done!

### **Option 2: Upload Extracted Files**

1. **Extract the ZIP file** on your computer
2. **Upload both files** to MapSync:
   - `AR1131860010276.tif` (the image)
   - `AR1131860010276.tfw` (the world file)
3. **See the metadata banner**: "📍 Location metadata detected (World File)"
4. **Click "Auto-Georeference"** → Automatic AI-guided placement!

### **Option 3: Upload Just the TIFF** (Manual Mode)

1. **Extract and upload**: `AR1131860010276.tif` only
2. **No metadata detected** → Manual bounding box required
3. **Draw bounding box** on the map
4. **AI matching runs** with manual guidance

---

## 📄 What are these files?

### **World File (.tfw)**

A simple text file containing 6 numbers that define the image's geographic transformation:

```
-0.0001         # Pixel width in map units (degrees)
0.0             # Rotation about Y-axis (usually 0)
0.0             # Rotation about X-axis (usually 0)
0.0001          # Pixel height in map units (negative)
-90.5           # X-coordinate of upper-left pixel center
34.7            # Y-coordinate of upper-left pixel center
```

**Why use it?**
- Simple, standardized format
- Recognized by all GIS software
- MapSync calculates corner coordinates automatically

### **GeoJSON Footprint (.geojson)**

A GeoJSON file containing the exact boundary polygon of the aerial photo:

```json
{
  "type": "Feature",
  "geometry": {
    "type": "Polygon",
    "coordinates": [[
      [-90.5, 34.7],  # Northwest corner
      [-90.3, 34.7],  # Northeast corner
      [-90.3, 34.5],  # Southeast corner
      [-90.5, 34.5],  # Southwest corner
      [-90.5, 34.7]   # Close polygon
    ]]
  }
}
```

**Why use it?**
- Shows exact spatial footprint
- Handles rotated/skewed imagery
- Can be viewed directly on a map

---

## 🔄 How MapSync Uses These Files

### **Automatic Detection**

When you upload a TIFF, MapSync automatically searches for companion files:

1. **Checks for world file**: `{filename}.tfw`, `{filename}.tifw`, `{filename}.tiffw`
2. **Checks for footprint**: `{filename}_footprint.geojson`
3. **Extracts corner coordinates** from whichever is found
4. **Displays metadata banner** with location info
5. **Auto-generates bounding box** for AI feature matching

### **AI Feature Matching Integration**

The metadata files provide the **search area**, but MapSync still uses **AI feature matching** for precision:

1. ✅ Metadata determines **where to search** (~5-50km area)
2. ✅ AI downloads satellite imagery for that area
3. ✅ SIFT/ORB feature matching finds exact control points
4. ✅ Result: **Sub-meter accuracy** with zero manual work!

---

## 📋 File Organization Best Practices

### **Keep Files Together**

```
# Correct ✅
uploads/
  AR1131860010276.tif
  AR1131860010276.tfw

# Also Correct ✅
uploads/
  AR1131860010276.tif
  AR1131860010276_footprint.geojson

# Wrong ❌
uploads/
  AR1131860010276.tif
downloads/
  AR1131860010276.tfw  # Different folder!
```

### **Preserve Original Filenames**

```
# Correct ✅
AR1131860010276.tif
AR1131860010276.tfw

# Wrong ❌
my_aerial_photo.tif
AR1131860010276.tfw  # Names don't match!
```

---

## 🎯 Workflow Comparison

### **Upload Entire ZIP** (⚡ Fastest - No Extraction!):

1. Download ZIP from USGS
2. Upload `.zip` file directly to MapSync
3. Green banner appears: "📍 Location metadata detected"
4. Click "Auto-Georeference" (no bounding box needed!)
5. ✅ AI-matched GCPs appear in ~10 seconds

### **Upload Extracted Files** (⚡ Fast):

1. Extract ZIP from USGS
2. Upload `.tif` + `.tfw` to MapSync
3. Green banner appears: "📍 Location metadata detected"
4. Click "Auto-Georeference" (no bounding box needed!)
5. ✅ AI-matched GCPs appear in ~10 seconds

### **Upload TIFF Only** (⏱️ Slower):

1. Upload `.tif` only
2. Click "Auto-Georeference"
3. Draw bounding box on map (~30-60 seconds)
4. Wait for satellite download
5. ✅ AI-matched GCPs appear

**Time saved with ZIP upload: No extraction needed + automatic metadata!**

---

## 🔍 Troubleshooting

### "No location metadata found"

**Cause:** World file or footprint not detected.

**Solutions:**
- Ensure files are in the same directory
- Check that filenames match exactly (case-sensitive!)
- Verify world file has `.tfw` extension (not `.txt`)
- Upload both TIFF and world file together

### "Metadata detected but auto-georeferencing failed"

**Cause:** Metadata provides location, but AI matching failed.

**What to do:**
- System will offer to draw manual bounding box
- Click "Yes" to try with user-defined area
- AI matching still works, just needs manual bounds

### World file values look wrong

**Check:**
- Pixel size should be small (e.g., 0.0001 for aerial imagery)
- Coordinates should be in decimal degrees
- Y-pixel size is usually negative (top-down coordinate system)

---

## 📚 Technical Details

### **Metadata Priority Order**

MapSync checks sources in this order:

1. ✅ **GDAL GeoTransform** (if TIFF already georeferenced)
2. ✅ **World File (.tfw)** - Simple, reliable, standard
3. ✅ **GeoJSON Footprint** - Exact boundary polygon
4. ✅ **EXIF GPS** - Camera GPS (if embedded)
5. ❌ **Manual Bounding Box** - User draws on map

### **World File Specifications**

- **Format:** Plain text, 6 lines
- **Units:** Map units (degrees for lat/lon, meters for projected)
- **Coordinate System:** Usually WGS84 (EPSG:4326)
- **Precision:** Typically 6-10 decimal places

### **GeoJSON Format**

- **Geometry Type:** Polygon or MultiPolygon
- **Coordinate Order:** `[longitude, latitude]` (GeoJSON standard)
- **Bounding Box:** MapSync extracts min/max coordinates

---

## ✅ Best Practices Summary

1. ✅ **Always download world file** with TIFF from EarthExplorer
2. ✅ **Keep files together** in same directory
3. ✅ **Preserve original names** from USGS
4. ✅ **Upload both files** (TIFF + TFW/GeoJSON)
5. ✅ **Verify metadata detected** (check for green banner)
6. ✅ **Trust the AI** - Feature matching refines metadata coordinates

---

## 📧 Support

Questions about USGS download packages?
- **Phil Wood**: pwood@joneswalker.com
- **USGS Customer Service**: custserv@usgs.gov
- **EarthExplorer Help**: https://www.usgs.gov/centers/eros/science/earthexplorer-help-index
