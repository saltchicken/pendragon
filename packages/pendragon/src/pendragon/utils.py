import ezdxf
import ezdxf.path
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
    Supports LINE, LWPOLYLINE, POLYLINE, CIRCLE, ARC, ELLIPSE, and SPLINE.
    """
    doc = ezdxf.readfile(dxf_path)
    msp = doc.modelspace()
    lines = []

    supported_types = {
        'LINE', 'LWPOLYLINE', 'POLYLINE', 'CIRCLE', 'ARC', 'ELLIPSE', 'SPLINE'
    }

    for e in msp:
        if e.dxftype() in supported_types:
            try:
                # Convert the DXF entity into an ezdxf Path object
                path = ezdxf.path.make_path(e)

                # Flatten the path into discrete vertices.
                # 'distance' is the maximum approximation error (sagitta) allowed.
                # 0.05 units ensures very smooth curves without overwhelming Shapely.
                pts = [(v.x, v.y) for v in path.flattening(distance=0.05)]

                if len(pts) >= 2:
                    # Explicitly enforce topological closure if the path is marked closed
                    if path.is_closed and pts[0] != pts[-1]:
                        pts.append(pts[0])

                    lines.append(LineString(pts))
            except Exception:
                # Silently ignore broken or completely unsupported geometry
                pass

    if not lines:
        raise ValueError("No valid line geometries found in DXF modelspace.")

    # polygonize intelligently finds all closed loops formed by the lines
    polygons = list(polygonize(lines))

    if not polygons:
        raise ValueError(
            "Could not form any closed boundaries from the DXF lines.")

    # unary_union merges overlapping polygons and groups disjoint ones into a MultiPolygon
    return unary_union(polygons)


def extract_target_polygons(
        boundary: Polygon | MultiPolygon,
        group_boundaries: bool = False) -> list[Polygon | MultiPolygon]:
    """
    Extracts a list of target geometries from a boundary.
    If group_boundaries is True, returns the unified geometry as a single item.
    Otherwise, unpacks MultiPolygons into their distinct geometric components.
    """
    if group_boundaries:
        return [boundary]
    if isinstance(boundary, MultiPolygon):
        return list(boundary.geoms)
    if isinstance(boundary, Polygon):
        return [boundary]
    return []
