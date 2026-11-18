"""Bounded image/diagram crops for visual retrieval experiments and indexing."""
from dataclasses import dataclass

REGION_VERSION = 'raster-vector-crops-v2'


@dataclass(frozen=True)
class Region:
    page: int
    bbox: tuple[float, float, float, float]
    kind: str


def page_regions(page, max_regions=4):
    import pymupdf
    if max_regions < 1:
        raise ValueError('max_regions must be positive')
    bounds, candidates, seen = page.rect, [], set()
    area = max(1., bounds.get_area())
    for info in sorted(page.get_image_info(hashes=True), key=lambda i: -(pymupdf.Rect(i['bbox']) & bounds).get_area()):
        rect = pymupdf.Rect(info['bbox']) & bounds
        fraction = rect.get_area() / area
        if not .025 <= fraction <= .85 or min(rect.width, rect.height) < 30:
            continue
        banner = rect.width > .85*bounds.width and ((rect.y0 < .03*bounds.height and rect.height < .25*bounds.height) or
                   (rect.y1 > .97*bounds.height and rect.height < .4*bounds.height))
        if banner:
            continue
        if info.get('digest') and info.get('digest') in seen:
            continue
        seen.add(info.get('digest'))
        candidates.append((rect, 'image'))
    for rect in page.cluster_drawings(x_tolerance=8, y_tolerance=8):
        rect = rect & bounds
        fraction = rect.get_area() / area
        if .025 <= fraction <= .6 and min(rect.width, rect.height) >= 35:
            candidates.append((rect, 'diagram'))
    # Avoid indexing nearly identical boxes twice (e.g. an image's decorative frame).
    selected = []
    for rect, kind in candidates:
        if any((rect & old).get_area()/max(1., min(rect.get_area(), old.get_area())) > .85 for old, _ in selected):
            continue
        selected.append((rect, kind))
        if len(selected) == max_regions:
            break
    if not selected and any((pymupdf.Rect(info['bbox']) & bounds).get_area()/area >= .85 for info in page.get_image_info()):
        # Scan-only pages get two overlapping zoomed views instead of just one tiny page.
        if bounds.height >= bounds.width:
            selected = [(pymupdf.Rect(0,0,bounds.width,.6*bounds.height),'tile'),
                        (pymupdf.Rect(0,.4*bounds.height,bounds.width,bounds.height),'tile')]
        else:
            selected = [(pymupdf.Rect(0,0,.6*bounds.width,bounds.height),'tile'),
                        (pymupdf.Rect(.4*bounds.width,0,bounds.width,bounds.height),'tile')]
    return [Region(page.number+1, tuple(rect),kind) for rect,kind in selected[:max_regions]]


def iter_regions(path, content, max_regions=4):
    import pymupdf
    from PIL import Image, ImageStat
    with pymupdf.open(stream=content, filetype='pdf') as document:
        if document.needs_pass:
            raise ValueError('Encrypted PDF')
        for page in document:
            for region in page_regions(page,max_regions):
                rect = pymupdf.Rect(region.bbox)
                scale = min(3., 1024/max(rect.width,rect.height))
                pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale,scale),clip=rect,alpha=False)
                image = Image.frombytes('RGB',(pixmap.width,pixmap.height),pixmap.samples)
                try:
                    with image.convert('L') as gray:
                        if ImageStat.Stat(gray).stddev[0] < 5:
                            continue
                    yield region,image
                finally:
                    image.close()
