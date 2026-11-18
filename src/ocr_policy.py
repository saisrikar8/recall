"""Conservative per-page OCR decisions based on native text and image geometry."""
from dataclasses import dataclass
import math
import re


@dataclass(frozen=True)
class OCRDecision:
    mode: str  # none, page, or regions
    reason: str
    regions: tuple[tuple[float, float, float, float], ...] = ()


def broken_text(text):
    visible = [char for char in text if not char.isspace()]
    if not visible:
        return False
    invalid = sum(char in {'\ufffd', '\x00'} or (ord(char) < 32) for char in visible)
    return invalid / len(visible) > .02 or len(re.findall(r'\(cid:\d+\)', text)) >= 2


def classify_page(page):
    import pymupdf
    bounds = page.rect
    area = max(1., bounds.get_area())
    words = []
    for value in page.get_text('words'):
        rectangle = pymupdf.Rect(value[:4])
        if not all(math.isfinite(x) for x in rectangle) or rectangle.is_empty:
            continue
        clipped = rectangle & bounds
        if clipped.get_area() >= rectangle.get_area() * .8:
            words.append((clipped, value[4]))
    native = page.get_text()
    if broken_text(native):
        return OCRDecision('page', 'broken_native_text')
    # Incidental page labels must not disguise an otherwise scanned document.
    body = [(rect, value) for rect, value in words
            if rect.y0 >= bounds.y0 + .07 * bounds.height and rect.y1 <= bounds.y1 - .07 * bounds.height]
    body_text = ' '.join(value for _, value in body)
    images = page.get_image_info(hashes=True)
    candidates, seen_images = [], set()
    # Repeated raster tiles need at most one representative crop, not repeated OCR.
    for info in sorted(images, key=lambda item: (pymupdf.Rect(item['bbox']) & bounds).get_area(), reverse=True):
        rect = pymupdf.Rect(info['bbox']) & bounds
        fraction = rect.get_area() / area
        if rect.is_empty or fraction < .08:
            continue
        # A shallow edge banner whose title already exists as text is not a scanned body.
        banner = rect.width >= .85 * bounds.width and rect.height <= .25 * bounds.height and rect.y0 <= bounds.y0 + .01 * bounds.height
        covered_title = sum(len(value) for word, value in words if (word & rect).get_area() >= word.get_area() * .5)
        if banner and covered_title >= 12:
            continue
        digest = info.get('digest')
        if digest and digest in seen_images:
            continue
        if digest:
            seen_images.add(digest)
        candidates.append(rect)
    if not any(char.isalnum() for char in body_text):
        if images or page.get_drawings():
            return OCRDecision('page', 'no_usable_body_text')
        return OCRDecision('none', 'blank_or_incidental_text_only')
    if len(body_text.strip()) < 50 and candidates:
        return OCRDecision('page', 'sparse_text_with_substantial_images')
    uncovered = []
    for region in candidates:
        intersecting = [(rect & region, value) for rect, value in words
                        if (rect & region).get_area() >= rect.get_area() * .5]
        characters = sum(len(value) for _, value in intersecting)
        coverage = sum(rect.get_area() for rect, _ in intersecting) / max(1., region.get_area())
        # A well-spread OCR/text layer over a scan is already usable. A title alone is not.
        spread = ((max(rect.y1 for rect, _ in intersecting) - min(rect.y0 for rect, _ in intersecting))
                  / max(1., region.height)) if intersecting else 0.
        represented = characters >= 50 and coverage >= .025 and spread >= .25
        if not represented:
            uncovered.append(region)
    if uncovered:
        # Merge overlapping crops to avoid OCRing the same image multiple times.
        merged = []
        for rect in uncovered:
            changed = True
            while changed:
                changed = False
                for index, previous in enumerate(merged):
                    if rect.intersects(previous):
                        rect = rect | merged.pop(index)
                        changed = True
                        break
            merged.append(rect)
        if sum(rect.get_area() for rect in merged) / area >= .75:
            return OCRDecision('page', 'image_content_not_covered_by_text')
        return OCRDecision('regions', 'images_without_usable_text', tuple(tuple(rect) for rect in merged))
    return OCRDecision('none', 'usable_native_text')
