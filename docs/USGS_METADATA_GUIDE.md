# USGS Aerial Imagery Metadata Guide

This guide explains how MapSync automatically extracts coordinate metadata from USGS aerial imagery to enable one-click georeferencing.

---

## 🎯 Overview

MapSync can automatically detect and use location metadata from USGS aerial photos through **three methods**:

1. **Metadata Sidecar Files** (Recommended - No API needed)
2. **USGS M2M API** (Requires free account)
3. **Embedded EXIF/GeoTIFF tags** (If already georeferenced)

---

## 📁 Method 1: Metadata Sidecar Files (Easiest)

### What are sidecar files?

When you download aerial imagery from USGS EarthExplorer, you can optionally download metadata files that contain corner coordinates. These are XML or text files with the same name as your TIFF.

### How to download metadata files from EarthExplorer:

1. Go to [USGS EarthExplorer](https://earthexplorer.usgs.gov/)
2. Search for and select your aerial imagery
3. Click "Download Options" for your image
4. **Check the box for "Metadata"** in addition to the TIFF
5. Download both files to the same folder

### Supported metadata formats:

- **FGDC XML** (`.xml`) - Standard USGS metadata format
- **Metadata text** (`_meta.txt`) - EarthExplorer export format
- **MET files** (`.met`) - Alternative metadata format

### File organization:

```
uploads/
  AR1131860010276.tiff          ← Your aerial image
  AR1131860010276.xml           ← Metadata sidecar (same name!)
```

### What MapSync does:

1. When you upload `AR1131860010276.tiff`
2. MapSync automatically looks for `AR1131860010276.xml`
3. Extracts corner coordinates from XML
4. Shows metadata banner: "📍 Location metadata detected (FGDC XML Metadata)"
5. One-click auto-georeferencing with AI precision!

---

## 🔌 Method 2: USGS M2M API (Automatic Download)

### What is the M2M API?

The Machine-to-Machine API allows programmatic access to USGS metadata without manually downloading files. MapSync can fetch metadata automatically using the aerial photo's Entity ID.

### Setup steps:

1. **Register for USGS account** (free):
   - Go to: https://ers.cr.usgs.gov/register
   - Complete registration and verify email

2. **Request M2M API access**:
   - Visit: https://m2m.cr.usgs.gov/
   - Login with your USGS credentials
   - Request access (usually approved within 24 hours)

3. **Configure MapSync**:
   ```bash
   # Copy the example config
   cp .env.example .env

   # Edit .env and add your credentials
   USGS_USERNAME=your_username
   USGS_PASSWORD=your_password
   ```

4. **Restart MapSync** - metadata will now fetch automatically!

### How it works:

- MapSync detects Entity ID pattern in filename (e.g., `AR1131860010276.tiff`)
- Connects to USGS M2M API
- Fetches corner coordinates automatically
- No need to download separate metadata files!

### Entity ID patterns:

USGS aerial imagery follows this naming format:
- **State Code** (2 letters): AR, CA, TX, LA, etc.
- **13-digit ID**: Unique identifier
- Example: `AR1131860010276`, `CA4567890123456`

---

## 🗺️ Method 3: Embedded GeoTIFF Tags

If your TIFF is already georeferenced (contains GDAL geotransform data), MapSync automatically reads the embedded coordinates.

### Check if your TIFF is georeferenced:

```bash
gdalinfo your_image.tiff
```

Look for:
```
Corner Coordinates:
Upper Left  ( -90.1234,  34.5678)
Lower Right ( -90.0987,  34.5432)
```

---

## 📊 Metadata Priority Order

MapSync checks these sources in order:

1. ✅ **GDAL GeoTransform** (embedded in TIFF)
2. ✅ **Metadata Sidecar Files** (.xml, .txt, .met)
3. ✅ **USGS M2M API** (if credentials configured)
4. ✅ **EXIF GPS Tags** (from camera)
5. ❌ No metadata → User draws bounding box manually

---

## 🚀 Workflow Comparison

### With Metadata (Automatic):

1. Upload `AR1131860010276.tiff` + `AR1131860010276.xml`
2. See green banner: "📍 Location metadata detected"
3. Click "Auto-Georeference"
4. ✅ Done! AI-matched control points appear instantly

### Without Metadata (Manual):

1. Upload `image.tiff`
2. Click "Auto-Georeference"
3. Draw bounding box on map
4. Wait for satellite download
5. ✅ AI-matched control points appear

**Time saved with metadata: 30-60 seconds per image!**

---

## 🔍 Troubleshooting

### "No location metadata found"

**Cause:** No sidecar file detected and no USGS API credentials configured.

**Solutions:**
- Download metadata XML from EarthExplorer alongside your TIFF
- Configure USGS M2M API credentials (see Method 2)
- Manually draw bounding box (still uses AI matching!)

### "Entity ID not recognized"

**Cause:** Filename doesn't match USGS pattern (2 letters + 13 digits).

**Solution:**
- Rename file to match USGS Entity ID format
- Example: `AR1131860010276.tiff`

### Metadata file not detected

**Cause:** Files not in same directory or different names.

**Solution:**
```bash
# Correct ✅
uploads/AR1131860010276.tiff
uploads/AR1131860010276.xml

# Wrong ❌
uploads/AR1131860010276.tiff
downloads/metadata.xml
```

---

## 📚 Additional Resources

- [USGS Aerial Photo Single Frames Data Dictionary](https://www.usgs.gov/centers/eros/science/aerial-photo-single-frames-data-dictionary)
- [USGS M2M API Documentation](https://m2m.cr.usgs.gov/)
- [EarthExplorer Help](https://www.usgs.gov/centers/eros/science/earthexplorer-help-index)
- [Aerial Photography Single Frame Records](https://www.usgs.gov/centers/eros/science/usgs-eros-archive-aerial-photography-aerial-photo-single-frames)

---

## ✅ Best Practices

1. **Always download metadata files** when downloading aerials from EarthExplorer
2. **Keep files together** - TIFF and XML in same folder with same name
3. **Use original filenames** - Preserve USGS Entity ID for API lookups
4. **Configure API credentials** once for automatic metadata retrieval
5. **Test with one image first** to verify workflow

---

## 📧 Support

Questions about USGS metadata? Contact:
- **Phil Wood**: pwood@joneswalker.com
- **USGS Customer Services**: custserv@usgs.gov
