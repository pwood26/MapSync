"""Shared configuration for MapSync image processing."""

from PIL import Image

# Allow very large images (USGS aerials can be 100+ megapixels)
MAX_IMAGE_PIXELS = 500_000_000
Image.MAX_IMAGE_PIXELS = MAX_IMAGE_PIXELS
