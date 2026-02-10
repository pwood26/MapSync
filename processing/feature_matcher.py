import cv2
import numpy as np
from PIL import Image

# Allow large USGS aerial frames
Image.MAX_IMAGE_PIXELS = 500_000_000

MAX_DIM = 4000
MIN_INLIERS = 10
GRID_SIZE = 5  # 5x5 grid for GCP spatial distribution


def auto_match(tiff_path, reference_image, reference_geo_transform):
    """Run the automatic feature-matching pipeline.

    Args:
        tiff_path: path to the uploaded TIFF.
        reference_image: numpy RGB array of the stitched satellite image.
        reference_geo_transform: tuple (origin_lon, origin_lat,
            px_size_lon, px_size_lat).

    Returns:
        dict with 'gcps' (list of {pixel_x, pixel_y, lat, lon}),
        'confidence' (0-1), 'match_count', or 'error'.
    """
    # --- Stage 1: Load and normalize the TIFF ---
    aerial_gray, downsample_ratio = _load_tiff(tiff_path)
    if aerial_gray is None:
        return {'error': 'Could not load TIFF image.'}

    ref_gray = cv2.cvtColor(reference_image, cv2.COLOR_RGB2GRAY)

    # --- Stage 2: No-data border mask ---
    mask = _build_border_mask(aerial_gray)

    # --- Stage 3: Preprocessing ---
    aerial_clahe, ref_clahe = _apply_clahe(aerial_gray, ref_gray)
    aerial_edges, ref_edges = _detect_edges(aerial_clahe, ref_clahe)

    # --- Stage 4-6: Feature detection, matching, RANSAC ---
    result = _match_with_orb(aerial_clahe, ref_clahe, mask)
    edge_result = _match_with_orb(aerial_edges, ref_edges, mask)

    # Use whichever produced more inliers
    if edge_result['inlier_count'] > result['inlier_count']:
        result = edge_result

    # SIFT fallback if ORB didn't find enough inliers
    if result['inlier_count'] < MIN_INLIERS:
        sift_result = _match_with_sift(aerial_clahe, ref_clahe, mask)
        if sift_result['inlier_count'] > result['inlier_count']:
            result = sift_result

        sift_edge_result = _match_with_sift(aerial_edges, ref_edges, mask)
        if sift_edge_result['inlier_count'] > result['inlier_count']:
            result = sift_edge_result

    if result['inlier_count'] < MIN_INLIERS:
        return {
            'error': (
                f'Insufficient feature matches (found {result["inlier_count"]}, '
                f'minimum {MIN_INLIERS}). The historical image may be too '
                'different from modern satellite imagery, or the bounding box '
                'may not overlap the actual photo area. '
                'Try adjusting the area or use manual GCP placement.'
            ),
            'match_count': result['inlier_count'],
        }

    # --- Stage 7: GCP extraction with spatial distribution ---
    gcps = _extract_gcps(
        result['src_inlier_pts'],
        result['dst_inlier_pts'],
        result['inlier_distances'],
        aerial_gray.shape,
        downsample_ratio,
        reference_geo_transform,
    )

    if len(gcps) < 5:
        return {
            'error': (
                f'Only {len(gcps)} spatially distributed GCPs found '
                '(minimum 5 required). Try a larger or more accurate '
                'bounding box.'
            ),
            'match_count': result['inlier_count'],
        }

    # --- Stage 8: Confidence scoring ---
    confidence = _compute_confidence(
        result['inlier_count'],
        result['total_matches'],
        result['inlier_distances'],
        gcps,
        aerial_gray.shape,
    )

    return {
        'gcps': gcps,
        'confidence': round(confidence, 2),
        'match_count': result['inlier_count'],
    }


# ============================================================
# Internal helpers
# ============================================================


def _load_tiff(tiff_path):
    """Load TIFF as grayscale, downsample if needed.

    Returns (gray_image, downsample_ratio).
    """
    try:
        img = cv2.imread(tiff_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            # Fallback to Pillow for unusual TIFF encodings
            pil_img = Image.open(tiff_path).convert('L')
            img = np.array(pil_img)
    except Exception:
        try:
            pil_img = Image.open(tiff_path).convert('L')
            img = np.array(pil_img)
        except Exception:
            return None, 1.0

    h, w = img.shape[:2]
    if max(h, w) > MAX_DIM:
        scale = MAX_DIM / max(h, w)
        img = cv2.resize(img, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_AREA)
        return img, 1.0 / scale
    return img, 1.0


def _build_border_mask(gray):
    """Create a binary mask excluding black no-data borders."""
    _, mask = cv2.threshold(gray, 15, 255, cv2.THRESH_BINARY)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(
        mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    if contours:
        largest = max(contours, key=cv2.contourArea)
        mask = np.zeros_like(mask)
        cv2.drawContours(mask, [largest], -1, 255, -1)

    return mask


def _apply_clahe(aerial, ref):
    """Apply CLAHE to both images."""
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    return clahe.apply(aerial), clahe.apply(ref)


def _detect_edges(aerial, ref):
    """Canny edge detection on both images, dilated for descriptor area."""
    aerial_edges = cv2.Canny(aerial, 30, 100)
    ref_edges = cv2.Canny(ref, 30, 100)

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    aerial_edges = cv2.dilate(aerial_edges, kernel, iterations=1)
    ref_edges = cv2.dilate(ref_edges, kernel, iterations=1)

    return aerial_edges, ref_edges


def _match_with_orb(aerial, ref, mask):
    """Detect ORB features, match with BFMatcher, filter with RANSAC."""
    orb = cv2.ORB_create(
        nfeatures=10000, scaleFactor=1.2, nlevels=8,
        edgeThreshold=15, patchSize=31,
    )

    kp_a, des_a = orb.detectAndCompute(aerial, mask)
    kp_r, des_r = orb.detectAndCompute(ref, None)

    if des_a is None or des_r is None or len(des_a) < 2 or len(des_r) < 2:
        return _empty_result()

    bf = cv2.BFMatcher(cv2.NORM_HAMMING)
    raw_matches = bf.knnMatch(des_a, des_r, k=2)

    # Lowe's ratio test
    good = []
    for pair in raw_matches:
        if len(pair) == 2:
            m, n = pair
            if m.distance < 0.75 * n.distance:
                good.append(m)

    if len(good) < 4:
        return _empty_result(total=len(good))

    return _ransac_filter(kp_a, kp_r, good)


def _match_with_sift(aerial, ref, mask):
    """Detect SIFT features, match with FLANN, filter with RANSAC."""
    sift = cv2.SIFT_create(
        nfeatures=5000, contrastThreshold=0.03, edgeThreshold=15,
    )

    kp_a, des_a = sift.detectAndCompute(aerial, mask)
    kp_r, des_r = sift.detectAndCompute(ref, None)

    if des_a is None or des_r is None or len(des_a) < 2 or len(des_r) < 2:
        return _empty_result()

    index_params = dict(algorithm=1, trees=5)  # FLANN_INDEX_KDTREE
    search_params = dict(checks=100)
    flann = cv2.FlannBasedMatcher(index_params, search_params)

    raw_matches = flann.knnMatch(des_a, des_r, k=2)

    good = []
    for pair in raw_matches:
        if len(pair) == 2:
            m, n = pair
            if m.distance < 0.7 * n.distance:
                good.append(m)

    if len(good) < 4:
        return _empty_result(total=len(good))

    return _ransac_filter(kp_a, kp_r, good)


def _ransac_filter(kp_src, kp_dst, good_matches):
    """Apply RANSAC homography to filter outliers."""
    src_pts = np.float32(
        [kp_src[m.queryIdx].pt for m in good_matches]
    ).reshape(-1, 1, 2)
    dst_pts = np.float32(
        [kp_dst[m.trainIdx].pt for m in good_matches]
    ).reshape(-1, 1, 2)

    H, inlier_mask = cv2.findHomography(
        src_pts, dst_pts, cv2.RANSAC,
        ransacReprojThreshold=5.0, maxIters=2000, confidence=0.995,
    )

    if inlier_mask is None:
        return _empty_result(total=len(good_matches))

    inlier_mask = inlier_mask.ravel().astype(bool)
    src_inliers = src_pts[inlier_mask].reshape(-1, 2)
    dst_inliers = dst_pts[inlier_mask].reshape(-1, 2)

    # Compute reprojection distances for inliers
    distances = []
    for m_idx in range(len(good_matches)):
        if inlier_mask[m_idx]:
            distances.append(good_matches[m_idx].distance)

    return {
        'inlier_count': int(inlier_mask.sum()),
        'total_matches': len(good_matches),
        'src_inlier_pts': src_inliers,
        'dst_inlier_pts': dst_inliers,
        'inlier_distances': distances,
    }


def _empty_result(total=0):
    """Return an empty match result."""
    return {
        'inlier_count': 0,
        'total_matches': total,
        'src_inlier_pts': np.array([]),
        'dst_inlier_pts': np.array([]),
        'inlier_distances': [],
    }


def _extract_gcps(src_pts, dst_pts, distances, img_shape,
                  downsample_ratio, geo_transform):
    """Select spatially distributed GCPs from inlier matches.

    Divides the aerial image into a grid and picks the best match
    (lowest descriptor distance) per cell.
    """
    origin_lon, origin_lat, px_size_lon, px_size_lat = geo_transform
    h, w = img_shape[:2]
    cell_h = h / GRID_SIZE
    cell_w = w / GRID_SIZE

    # Best match per grid cell: (row, col) -> (index, distance)
    grid = {}

    for i in range(len(src_pts)):
        pt = src_pts[i]
        row = min(int(pt[1] / cell_h), GRID_SIZE - 1)
        col = min(int(pt[0] / cell_w), GRID_SIZE - 1)
        dist = distances[i] if i < len(distances) else float('inf')

        if (row, col) not in grid or dist < grid[(row, col)][1]:
            grid[(row, col)] = (i, dist)

    gcps = []
    for (row, col), (idx, _) in grid.items():
        aerial_pt = src_pts[idx]
        ref_pt = dst_pts[idx]

        # Scale back to original TIFF coordinates
        orig_px_x = aerial_pt[0] * downsample_ratio
        orig_px_y = aerial_pt[1] * downsample_ratio

        # Convert reference pixel to geographic coordinates
        lon = origin_lon + ref_pt[0] * px_size_lon
        lat = origin_lat + ref_pt[1] * px_size_lat

        gcps.append({
            'pixel_x': round(float(orig_px_x), 1),
            'pixel_y': round(float(orig_px_y), 1),
            'lat': round(float(lat), 6),
            'lon': round(float(lon), 6),
        })

    return gcps


def _compute_confidence(inlier_count, total_matches, distances,
                        gcps, img_shape):
    """Compute an overall confidence score (0.0 to 1.0)."""
    # Factor 1: Inlier count (more is better, saturates at 100)
    count_score = min(inlier_count / 100.0, 1.0)

    # Factor 2: Inlier ratio
    ratio_score = (inlier_count / total_matches) if total_matches > 0 else 0

    # Factor 3: Spatial distribution - fraction of grid cells with GCPs
    distribution_score = len(gcps) / (GRID_SIZE * GRID_SIZE)

    # Factor 4: Average descriptor distance (lower is better)
    if distances:
        avg_dist = sum(distances) / len(distances)
        # Normalize: ORB distances typically 0-256, SIFT 0-300
        dist_score = max(0, 1.0 - avg_dist / 200.0)
    else:
        dist_score = 0

    # Weighted average
    confidence = (
        0.3 * count_score
        + 0.2 * ratio_score
        + 0.3 * distribution_score
        + 0.2 * dist_score
    )

    return max(0.0, min(1.0, confidence))
