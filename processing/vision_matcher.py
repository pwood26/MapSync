"""MapSync - Claude Vision-based landmark matching for auto-georeferencing.

Replaces ORB/SIFT feature matching with Claude's vision capabilities.
Claude can semantically identify persistent landmarks (river bends, road
intersections, railroad tracks) across decades of landscape change, which
classical feature detectors cannot do.
"""

import base64
import io
import json
import os
import re

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# Allow large USGS aerial frames
Image.MAX_IMAGE_PIXELS = 500_000_000

MAX_DIM = 2000          # Max dimension for images sent to Claude API
GRID_SPACING = 200      # Pixels between grid lines
MIN_GCPS = 5
TARGET_GCPS = 12
CLAUDE_MODEL = 'claude-sonnet-4-20250514'
CLAUDE_MAX_TOKENS = 4096


def auto_match(tiff_path, reference_image, reference_geo_transform):
    """Run Claude Vision-based landmark matching.

    Drop-in replacement for the ORB/SIFT feature_matcher.auto_match().

    Args:
        tiff_path: path to the uploaded TIFF.
        reference_image: numpy RGB array (H x W x 3, uint8) of satellite imagery.
        reference_geo_transform: tuple (origin_lon, origin_lat,
            px_size_lon, px_size_lat).

    Returns:
        dict with 'gcps' (list of {pixel_x, pixel_y, lat, lon}),
        'confidence' (0-1), 'match_count', or 'error'.
    """
    # Check API key
    api_key = os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return {
            'error': (
                'ANTHROPIC_API_KEY environment variable is not set. '
                'Claude Vision API is required for auto-georeferencing. '
                'Set the key in your environment or Railway dashboard.'
            )
        }

    # --- Stage 1: Prepare aerial image ---
    aerial_img, aerial_ratio = _prepare_aerial(tiff_path)
    if aerial_img is None:
        return {'error': 'Could not load TIFF image.'}

    # --- Stage 2: Prepare reference satellite image ---
    ref_img, ref_ratio = _prepare_reference(reference_image)

    # Adjust geo_transform for reference downsampling
    origin_lon, origin_lat, px_size_lon, px_size_lat = reference_geo_transform
    adj_px_size_lon = px_size_lon * ref_ratio
    adj_px_size_lat = px_size_lat * ref_ratio

    # --- Stage 3: Draw grid overlays ---
    aerial_grid = _draw_grid_overlay(aerial_img)
    ref_grid = _draw_grid_overlay(ref_img)

    # --- Stage 4: Encode as base64 JPEG ---
    aerial_b64, aerial_media = _encode_image(aerial_grid)
    ref_b64, ref_media = _encode_image(ref_grid)

    # Compute reference bounds for the prompt
    ref_w, ref_h = ref_img.size
    ref_east = origin_lon + ref_w * ref_ratio * px_size_lon
    ref_south = origin_lat + ref_h * ref_ratio * px_size_lat

    print(f'[vision_matcher] Aerial: {aerial_img.size}, ratio={aerial_ratio:.2f}')
    print(f'[vision_matcher] Reference: {ref_img.size}, ratio={ref_ratio:.2f}')
    print(f'[vision_matcher] Ref bounds: {origin_lon:.6f}W → {ref_east:.6f}E, '
          f'{ref_south:.6f}S → {origin_lat:.6f}N')

    # --- Stage 5: Call Claude Vision API ---
    try:
        response_text = _call_claude_vision(
            aerial_b64, aerial_media,
            ref_b64, ref_media,
            aerial_img.size, ref_img.size,
            {
                'north': origin_lat,
                'south': ref_south,
                'east': ref_east,
                'west': origin_lon,
            },
            api_key,
        )
    except Exception as e:
        return {'error': f'Claude Vision API call failed: {e}'}

    # --- Stage 6: Parse response ---
    parsed = _parse_vision_response(response_text)
    if 'error' in parsed:
        return parsed

    matches = parsed['matches']
    print(f'[vision_matcher] Claude returned {len(matches)} matches, '
          f'overall_confidence={parsed["overall_confidence"]}')
    if parsed.get('notes'):
        print(f'[vision_matcher] Notes: {parsed["notes"]}')

    # --- Stage 7-8: Convert to GCPs ---
    gcps = []
    for m in matches:
        # Filter low-confidence matches
        if m.get('confidence') == 'low':
            continue

        # Validate coordinates are within image bounds
        aw, ah = aerial_img.size
        rw, rh = ref_img.size
        if not (0 <= m['aerial_x'] <= aw and 0 <= m['aerial_y'] <= ah):
            continue
        if not (0 <= m['satellite_x'] <= rw and 0 <= m['satellite_y'] <= rh):
            continue

        # Convert satellite pixel to lat/lon (using adjusted pixel sizes)
        lon = origin_lon + m['satellite_x'] * adj_px_size_lon
        lat = origin_lat + m['satellite_y'] * adj_px_size_lat

        # Scale aerial pixel back to original TIFF coordinates
        orig_px_x = m['aerial_x'] * aerial_ratio
        orig_px_y = m['aerial_y'] * aerial_ratio

        gcps.append({
            'pixel_x': round(float(orig_px_x), 1),
            'pixel_y': round(float(orig_px_y), 1),
            'lat': round(float(lat), 6),
            'lon': round(float(lon), 6),
        })

    if len(gcps) < MIN_GCPS:
        return {
            'error': (
                f'Only {len(gcps)} valid landmark matches found '
                f'(minimum {MIN_GCPS} required). The historical image may '
                'be too different from modern satellite imagery, or the '
                'bounding box may not overlap the actual photo area. '
                'Try adjusting the area or use manual GCP placement.'
            ),
            'match_count': len(gcps),
        }

    # --- Stage 9: Compute confidence ---
    confidence = _compute_confidence(matches, parsed['overall_confidence'])

    return {
        'gcps': gcps,
        'confidence': round(confidence, 2),
        'match_count': len(gcps),
    }


# ============================================================
# Image preparation
# ============================================================


def _prepare_aerial(tiff_path):
    """Load aerial TIFF, convert to RGB, downsample if needed.

    Returns:
        (pil_image, downsample_ratio) where downsample_ratio maps
        downsampled pixels back to original pixels.
    """
    try:
        img = Image.open(tiff_path)
    except Exception:
        return None, 1.0

    # Handle various TIFF modes
    if img.mode == 'I;16':
        # 16-bit grayscale — normalize to 8-bit
        arr = np.array(img, dtype=np.float32)
        arr = (arr - arr.min()) / max(arr.max() - arr.min(), 1) * 255
        img = Image.fromarray(arr.astype(np.uint8))

    if img.mode in ('I', 'F'):
        arr = np.array(img, dtype=np.float32)
        arr = (arr - arr.min()) / max(arr.max() - arr.min(), 1) * 255
        img = Image.fromarray(arr.astype(np.uint8))

    if img.mode == 'RGBA':
        # Composite onto white background
        bg = Image.new('RGB', img.size, (255, 255, 255))
        bg.paste(img, mask=img.split()[3])
        img = bg
    elif img.mode != 'RGB':
        img = img.convert('RGB')

    w, h = img.size
    if max(w, h) > MAX_DIM:
        scale = MAX_DIM / max(w, h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        return img, 1.0 / scale

    return img, 1.0


def _prepare_reference(reference_image):
    """Downsample satellite reference if needed.

    Args:
        reference_image: numpy RGB array (H x W x 3, uint8)

    Returns:
        (pil_image, downsample_ratio)
    """
    img = Image.fromarray(reference_image)
    w, h = img.size

    if max(w, h) > MAX_DIM:
        scale = MAX_DIM / max(w, h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        return img, 1.0 / scale

    return img, 1.0


# ============================================================
# Grid overlay
# ============================================================


def _draw_grid_overlay(pil_image, spacing=GRID_SPACING):
    """Draw a labeled pixel coordinate grid over the image.

    Red grid lines every `spacing` pixels with coordinate labels
    along the top and left edges. This gives Claude a concrete
    reference frame for reporting pixel positions.

    Returns a new PIL Image with the grid overlay.
    """
    img = pil_image.copy().convert('RGBA')
    overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    w, h = img.size

    try:
        font = ImageFont.load_default(size=14)
    except TypeError:
        # Older Pillow versions don't accept size parameter
        font = ImageFont.load_default()

    line_color = (255, 50, 50, 160)
    bg_color = (255, 255, 255, 200)
    text_color = (200, 0, 0, 255)

    # Vertical lines with X labels at top
    for x in range(0, w, spacing):
        draw.line([(x, 0), (x, h)], fill=line_color, width=1)
        label = str(x)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.rectangle([x + 2, 1, x + 4 + tw, 3 + th], fill=bg_color)
        draw.text((x + 3, 2), label, fill=text_color, font=font)

    # Horizontal lines with Y labels on left
    for y in range(0, h, spacing):
        draw.line([(0, y), (w, y)], fill=line_color, width=1)
        label = str(y)
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.rectangle([1, y + 2, 3 + tw, y + 4 + th], fill=bg_color)
        draw.text((2, y + 3), label, fill=text_color, font=font)

    # Composite overlay onto image
    result = Image.alpha_composite(img, overlay)
    return result.convert('RGB')


# ============================================================
# Image encoding
# ============================================================


def _encode_image(pil_image, quality=85):
    """Encode a PIL Image as base64 JPEG string.

    Returns (base64_str, media_type) tuple.
    """
    buf = io.BytesIO()
    pil_image.save(buf, format='JPEG', quality=quality)
    b64 = base64.standard_b64encode(buf.getvalue()).decode('utf-8')
    return b64, 'image/jpeg'


# ============================================================
# Claude Vision API
# ============================================================


def _call_claude_vision(aerial_b64, aerial_media, ref_b64, ref_media,
                        aerial_dims, ref_dims, ref_bounds, api_key):
    """Call Claude Vision API with both images and matching prompt.

    Returns the raw response text from Claude.
    """
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)

    aerial_w, aerial_h = aerial_dims
    ref_w, ref_h = ref_dims

    prompt_parts = [
        {
            'type': 'text',
            'text': (
                'You are a geospatial analyst matching landmarks between a '
                'historical aerial photograph and modern satellite imagery '
                'of the same area.\n\n'
                'Both images have a red pixel coordinate grid overlay. '
                'The grid lines are labeled with pixel coordinates along the '
                'top (X axis) and left (Y axis) edges. Use these grid labels '
                'to report precise pixel positions.'
            ),
        },
        {
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': aerial_media,
                'data': aerial_b64,
            },
        },
        {
            'type': 'text',
            'text': (
                f'IMAGE 1 (above): Historical aerial photograph.\n'
                f'- Dimensions: {aerial_w} x {aerial_h} pixels\n'
                f'- Grid spacing: {GRID_SPACING} pixels\n'
                f'- This may be black-and-white or grayscale. It may have '
                f'black borders (no-data areas) — ignore those regions.'
            ),
        },
        {
            'type': 'image',
            'source': {
                'type': 'base64',
                'media_type': ref_media,
                'data': ref_b64,
            },
        },
        {
            'type': 'text',
            'text': (
                f'IMAGE 2 (above): Modern satellite imagery (Esri World Imagery).\n'
                f'- Dimensions: {ref_w} x {ref_h} pixels\n'
                f'- Grid spacing: {GRID_SPACING} pixels\n'
                f'- Geographic coverage: '
                f'{ref_bounds["west"]:.6f} to {ref_bounds["east"]:.6f} longitude, '
                f'{ref_bounds["south"]:.6f} to {ref_bounds["north"]:.6f} latitude'
            ),
        },
        {
            'type': 'text',
            'text': (
                f'TASK: Identify {TARGET_GCPS} landmark points that are clearly '
                f'visible in BOTH images. These will be used as Ground Control '
                f'Points (GCPs) for georeferencing the historical photo.\n\n'

                'GOOD LANDMARKS (prioritize these):\n'
                '- Road intersections or sharp road curves\n'
                '- River bends, canal junctions, or shoreline features\n'
                '- Bridge endpoints\n'
                '- Railroad crossings or rail line curves\n'
                '- Building corners or distinctive structures\n'
                '- Levee or embankment turns\n'
                '- Field corners or property boundaries\n'
                '- Pond or lake edges with distinctive shapes\n\n'

                'BAD LANDMARKS (avoid these):\n'
                '- Points in featureless areas (open water, uniform forest, bare ground)\n'
                '- Points in the black border/no-data area of the aerial photo\n'
                '- Points that have clearly changed between time periods\n'
                '- Points near the very edge of either image\n\n'

                'SPATIAL DISTRIBUTION: Spread points across the entire '
                'overlapping area. Do NOT cluster points in one region. '
                'Aim for at least one point in each quadrant.\n\n'

                'COORDINATE PRECISION: Use the red grid overlay to determine '
                'pixel coordinates. Read the nearest grid labels and estimate '
                'the position between grid lines. For example, if a point is '
                'roughly 60%% of the way between grid line X=400 and X=600, '
                'report X as approximately 520.\n\n'

                'RESPONSE FORMAT: Return ONLY valid JSON (no markdown fences, '
                'no explanation outside the JSON). Use this exact structure:\n\n'
                '{\n'
                '  "matches": [\n'
                '    {\n'
                '      "landmark": "brief description",\n'
                '      "aerial_x": 520,\n'
                '      "aerial_y": 780,\n'
                '      "satellite_x": 1240,\n'
                '      "satellite_y": 860,\n'
                '      "confidence": "high"\n'
                '    }\n'
                '  ],\n'
                '  "overall_confidence": 0.7,\n'
                '  "notes": "brief note about matching difficulty"\n'
                '}\n\n'

                'Rules:\n'
                '- aerial_x/aerial_y: pixel coordinates in IMAGE 1\n'
                '- satellite_x/satellite_y: pixel coordinates in IMAGE 2\n'
                '- confidence per point: "high", "medium", or "low"\n'
                '- overall_confidence: 0.0 to 1.0\n'
                f'- Include at least {MIN_GCPS} matches, ideally {TARGET_GCPS}\n'
                f'- If you cannot find {MIN_GCPS} confident matches, set '
                f'overall_confidence below 0.3 and explain in notes'
            ),
        },
    ]

    response = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=CLAUDE_MAX_TOKENS,
        messages=[{
            'role': 'user',
            'content': prompt_parts,
        }],
    )

    return response.content[0].text


# ============================================================
# Response parsing
# ============================================================


def _parse_vision_response(response_text):
    """Parse Claude's JSON response into match data.

    Handles common formatting issues: markdown fences, trailing
    commas, approximate values (~ prefix).

    Returns:
        dict with 'matches' list, 'overall_confidence', 'notes',
        or 'error'.
    """
    text = response_text.strip()

    # Strip markdown code fences
    if text.startswith('```'):
        # Remove opening fence (possibly ```json)
        first_newline = text.find('\n')
        if first_newline != -1:
            text = text[first_newline + 1:]
        else:
            text = text[3:]
    if text.rstrip().endswith('```'):
        text = text.rstrip()[:-3]
    text = text.strip()

    # Remove trailing commas before ] or }
    text = re.sub(r',\s*([}\]])', r'\1', text)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        print(f'[vision_matcher] JSON parse error: {e}')
        print(f'[vision_matcher] Raw response:\n{response_text[:500]}')
        return {'error': f'Failed to parse Claude response as JSON: {e}'}

    matches = data.get('matches', [])
    valid_matches = []

    for m in matches:
        try:
            valid_matches.append({
                'landmark': str(m.get('landmark', 'unknown')),
                'aerial_x': _parse_number(m['aerial_x']),
                'aerial_y': _parse_number(m['aerial_y']),
                'satellite_x': _parse_number(m['satellite_x']),
                'satellite_y': _parse_number(m['satellite_y']),
                'confidence': m.get('confidence', 'medium'),
            })
        except (KeyError, ValueError, TypeError) as e:
            print(f'[vision_matcher] Skipping malformed match: {e}')
            continue

    if not valid_matches:
        return {
            'error': (
                'Claude did not return any valid landmark matches. '
                'The images may not overlap or may be too different '
                'for reliable matching.'
            )
        }

    return {
        'matches': valid_matches,
        'overall_confidence': float(data.get('overall_confidence', 0.5)),
        'notes': str(data.get('notes', '')),
    }


def _parse_number(value):
    """Parse a number that might have ~ or 'approximately' prefix."""
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    # Remove common prefixes
    s = s.lstrip('~').lstrip('≈').strip()
    s = s.replace('approximately', '').strip()
    return float(s)


# ============================================================
# Confidence scoring
# ============================================================


def _compute_confidence(matches, claude_confidence):
    """Compute overall confidence score (0.0 to 1.0).

    Blends Claude's self-assessment with objective metrics.
    """
    if not matches:
        return 0.0

    # Factor 1: Number of matches (saturates at TARGET_GCPS)
    count_score = min(len(matches) / TARGET_GCPS, 1.0)

    # Factor 2: High-confidence match ratio
    high = sum(1 for m in matches if m.get('confidence') == 'high')
    med = sum(1 for m in matches if m.get('confidence') == 'medium')
    conf_score = (high * 1.0 + med * 0.5) / len(matches)

    # Factor 3: Spatial distribution (check quadrant coverage)
    if len(matches) >= 2:
        xs = [m['aerial_x'] for m in matches]
        ys = [m['aerial_y'] for m in matches]
        cx = (min(xs) + max(xs)) / 2
        cy = (min(ys) + max(ys)) / 2
        quadrants = set()
        for m in matches:
            qx = 0 if m['aerial_x'] < cx else 1
            qy = 0 if m['aerial_y'] < cy else 1
            quadrants.add((qx, qy))
        dist_score = len(quadrants) / 4.0
    else:
        dist_score = 0.25

    # Factor 4: Claude's self-assessed confidence
    claude_score = max(0.0, min(1.0, claude_confidence))

    confidence = (
        0.25 * count_score
        + 0.20 * conf_score
        + 0.25 * dist_score
        + 0.30 * claude_score
    )

    return max(0.0, min(1.0, confidence))
