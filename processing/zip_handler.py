"""Handle ZIP file uploads containing USGS download packages.

USGS download packages typically contain:
- {entityId}.tif - The aerial photograph
- {entityId}.tfw - World file
- {entityId}_footprint.geojson - Spatial footprint
- README.txt - Instructions
"""

import os
import zipfile
import tempfile
from typing import Optional, Dict, List


def is_zipfile(filepath: str) -> bool:
    """Check if file is a valid ZIP archive."""
    try:
        return zipfile.is_zipfile(filepath)
    except Exception:
        return False


def extract_usgs_package(zip_path: str, extract_dir: str) -> Optional[Dict]:
    """Extract USGS download package from ZIP file.

    Args:
        zip_path: Path to ZIP file
        extract_dir: Directory to extract files to

    Returns:
        Dict with paths to extracted files:
        {
            'tiff': path to TIFF file,
            'worldfile': path to .tfw file (optional),
            'footprint': path to _footprint.geojson (optional),
            'readme': path to README.txt (optional)
        }
    """
    try:
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            # Get list of files in archive
            file_list = zip_ref.namelist()

            # Find the TIFF file
            tiff_files = [f for f in file_list if f.lower().endswith(('.tif', '.tiff')) and not f.startswith('__MACOSX')]

            if not tiff_files:
                return None

            # Use the first TIFF found
            tiff_filename = tiff_files[0]
            base_name = os.path.splitext(os.path.basename(tiff_filename))[0]

            # Look for companion files
            worldfile = None
            footprint = None
            readme = None

            for filename in file_list:
                if filename.startswith('__MACOSX'):
                    continue

                basename = os.path.basename(filename)
                lower_name = basename.lower()

                # World file (.tfw, .tifw, .tiffw)
                if lower_name.endswith(('.tfw', '.tifw', '.tiffw')):
                    worldfile = filename

                # Footprint GeoJSON
                elif '_footprint.geojson' in lower_name or 'footprint.geojson' in lower_name:
                    footprint = filename

                # README
                elif lower_name == 'readme.txt':
                    readme = filename

            # Extract files
            zip_ref.extractall(extract_dir)

            result = {
                'tiff': os.path.join(extract_dir, tiff_filename),
            }

            if worldfile:
                result['worldfile'] = os.path.join(extract_dir, worldfile)

            if footprint:
                result['footprint'] = os.path.join(extract_dir, footprint)

            if readme:
                result['readme'] = os.path.join(extract_dir, readme)

            return result

    except (zipfile.BadZipFile, Exception) as e:
        return None


def get_package_info(extracted_files: Dict) -> str:
    """Get human-readable info about extracted package.

    Args:
        extracted_files: Dict from extract_usgs_package()

    Returns:
        String describing what was found
    """
    parts = []

    if extracted_files.get('tiff'):
        parts.append("TIFF image")

    if extracted_files.get('worldfile'):
        parts.append("world file (.tfw)")

    if extracted_files.get('footprint'):
        parts.append("footprint GeoJSON")

    if extracted_files.get('readme'):
        parts.append("README")

    if not parts:
        return "Unknown package"

    return f"USGS package with {', '.join(parts)}"


def cleanup_extracted_files(extracted_files: Dict):
    """Clean up extracted temporary files.

    Args:
        extracted_files: Dict from extract_usgs_package()
    """
    if not extracted_files:
        return

    # Get the extraction directory from any file path
    for file_path in extracted_files.values():
        if file_path and os.path.exists(file_path):
            extract_dir = os.path.dirname(file_path)

            # Remove all files in the extraction directory
            try:
                for filename in os.listdir(extract_dir):
                    filepath = os.path.join(extract_dir, filename)
                    if os.path.isfile(filepath):
                        os.remove(filepath)

                # Remove the directory itself
                os.rmdir(extract_dir)
            except Exception:
                pass

            break
