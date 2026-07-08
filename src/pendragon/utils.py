import ezdxf
from PIL import Image
from shapely.geometry import LineString
from shapely.geometry import MultiPolygon
from shapely.geometry import Polygon
from shapely.ops import polygonize
from shapely.ops import unary_union


class ImageSampler:

    def __init__(self, image_path: str, bounds: tuple):
        self.img = Image.open(image_path).convert("L")
        self.minx, self.miny, self.maxx, self.maxy = bounds
        self.width = self.maxx - self.minx
        self.height = self.maxy - self.miny

    def get_darkness(self, x: float, y: float) -> float:
        if self.width == 0 or self.height == 0:
            return 0.0
        px = max(
            0,
            min(int(((x - self.minx) / self.width) * (self.img.width - 1)),
                self.img.width - 1))
        py = max(
            0,
            min(
                int((1.0 - ((y - self.miny) / self.height)) *
                    (self.img.height - 1)), self.img.height - 1))
        return (255 - self.img.getpixel((px, py))) / 255.0


def load_dxf_boundary(dxf_path: str) -> Polygon | MultiPolygon:
    """
    Parses a DXF file and constructs a Shapely Polygon or MultiPolygon.
    Handles multiple disjoint, overlapping, or holed polygons.
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    lines = []

    for e in msp:
        if e.dxftype() == 'LWPOLYLINE':
            pts = [vertex[:2] for vertex in e.vertices()]
            if len(pts) >= 2:
                # If the polyline is flagged as closed, ensure the coordinate loop is closed
                if e.closed and pts[0] != pts[-1]:
                    pts.append(pts[0])
                lines.append(LineString(pts))
        elif e.dxftype() == 'LINE':
            lines.append(LineString([e.dxf.start[:2], e.dxf.end[:2]]))
        # Note: You can add handling for SPLINE or ARC here later if needed

    if not lines:
        raise ValueError("No valid line geometries found in DXF modelspace.")

    # polygonize intelligently finds all closed loops formed by the lines
    polygons = list(polygonize(lines))

    if not polygons:
        raise ValueError(
            "Could not form any closed boundaries from the DXF lines.")

    # unary_union merges overlapping polygons and groups disjoint ones into a MultiPolygon
    return unary_union(polygons)
