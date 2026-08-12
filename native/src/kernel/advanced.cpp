#include "kernel/advanced.h"

#include "kernel/construction.h"
#include "kernel/features.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <utility>
#include <vector>

#ifdef CADFLOW_WITH_OCCT
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepFill_TypeOfContact.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepOffsetAPI_ThruSections.hxx>
#include <BRep_Tool.hxx>
#include <BRep_Builder.hxx>
#include <GeomAPI_PointsToBSplineSurface.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_CylindricalSurface.hxx>
#include <Poly_Triangulation.hxx>
#include <TColgp_Array1OfPnt.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TopAbs.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_HSequenceOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Compound.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Wire.hxx>
#include <BRepLib.hxx>
#include <BRepTools.hxx>
#include <TopTools_ListOfShape.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax2.hxx>
#include <gp_Ax3.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Vec.hxx>
#include <Geom2d_Curve.hxx>
#include <Geom2d_Line.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#endif

#ifdef CADFLOW_WITH_OCCT
class BRepFill {
public:
    static TopoDS_Face Face(const TopoDS_Edge&, const TopoDS_Edge&);
};
class StlAPI_Reader {
public:
    Standard_Boolean Read(TopoDS_Shape&, const Standard_CString);
};
#endif

namespace cadflow::kernel {
namespace {

using core::Shape;
using core::ShapeId;

void require_occt() {
#ifndef CADFLOW_WITH_OCCT
    throw std::runtime_error("operation requires the OCCT backend");
#endif
}

void validate_finite(const double* values, std::size_t count, const char* name) {
    if (!values) {
        throw std::invalid_argument(std::string(name) + " is null");
    }
    for (std::size_t i = 0; i < count; ++i) {
        if (!std::isfinite(values[i])) {
            throw std::invalid_argument(std::string(name) + " must be finite");
        }
    }
}

#ifdef CADFLOW_WITH_OCCT
TopoDS_Shape subshape(const Shape& source, TopAbs_ShapeEnum type, std::size_t index) {
    TopTools_IndexedMapOfShape items;
    TopExp::MapShapes(source.native, type, items);
    if (index >= static_cast<std::size_t>(items.Extent())) {
        throw std::out_of_range("subshape index out of range");
    }
    return items(static_cast<int>(index + 1));
}

ShapeId store_native(core::Session& session, Shape::Kind kind, TopoDS_Shape native) {
    if (native.IsNull()) {
        throw std::runtime_error("OCCT returned a null shape");
    }
    Shape output {kind};
    output.native = std::move(native);
    return core::store(session, std::move(output));
}

TopoDS_Wire edge_wire(const TopoDS_Edge& edge) {
    BRepBuilderAPI_MakeWire builder(edge);
    if (!builder.IsDone()) {
        throw std::runtime_error("could not make a wire from edge");
    }
    return builder.Wire();
}

Handle(Geom_BSplineCurve) edge_curve(const TopoDS_Edge& edge) {
    BRepAdaptor_Curve adaptor(edge);
    Handle(Geom_BSplineCurve) curve = adaptor.BSpline();
    if (curve.IsNull()) {
        throw std::invalid_argument("Gordon input edges must be B-spline curves");
    }
    return curve;
}

TopoDS_Shape make_surface_face(const Handle(Geom_Surface)& surface) {
    BRepBuilderAPI_MakeFace builder(surface, 1.0e-7);
    if (!builder.IsDone()) {
        throw std::runtime_error("could not build a face from generated surface");
    }
    return builder.Face();
}

std::vector<TopoDS_Edge> ordered_edges(const TopoDS_Wire& wire) {
    std::vector<TopoDS_Edge> result;
    for (TopExp_Explorer it(wire, TopAbs_EDGE); it.More(); it.Next()) {
        result.push_back(TopoDS::Edge(it.Current()));
    }
    return result;
}

std::vector<TopoDS_Wire> free_wires(const TopoDS_Shape& shape, double tolerance) {
    (void)tolerance;
    TopTools_IndexedDataMapOfShapeListOfShape edge_faces;
    TopExp::MapShapesAndUniqueAncestors(
        shape, TopAbs_EDGE, TopAbs_FACE, edge_faces, false);
    TopTools_ListOfShape free_edges;
    for (int index = 1; index <= edge_faces.Extent(); ++index) {
        if (edge_faces(index).Extent() == 1) {
            free_edges.Append(edge_faces.FindKey(index));
        }
    }
    std::vector<TopoDS_Wire> result;
    if (!free_edges.IsEmpty()) {
        BRepBuilderAPI_MakeWire builder;
        builder.Add(free_edges);
        if (!builder.IsDone()) {
            throw std::runtime_error("could not connect free boundary edges");
        }
        result.push_back(builder.Wire());
    }
    return result;
}
#endif

}  // namespace

ShapeId make_bspline(
    core::Session& session,
    const double* poles_xyz,
    std::size_t pole_count,
    int degree,
    const double* knots,
    std::size_t knot_count,
    const int* multiplicities,
    std::size_t multiplicity_count,
    const double* weights,
    bool periodic) {
    if (pole_count < 2 || degree < 1 || degree > 25) {
        throw std::invalid_argument("B-spline requires valid pole count and degree");
    }
    if (pole_count < static_cast<std::size_t>(degree + 1)) {
        throw std::invalid_argument("B-spline pole count must be at least degree + 1");
    }
    if (!knots || !multiplicities || knot_count < 2 || knot_count != multiplicity_count) {
        throw std::invalid_argument("B-spline knots and multiplicities are inconsistent");
    }
    validate_finite(poles_xyz, pole_count * 3, "B-spline poles");
    validate_finite(knots, knot_count, "B-spline knots");
    if (weights) {
        validate_finite(weights, pole_count, "B-spline weights");
    }
    for (std::size_t i = 0; i < knot_count; ++i) {
        if (i && knots[i] <= knots[i - 1]) {
            throw std::invalid_argument("B-spline knots must be strictly increasing");
        }
        if (multiplicities[i] <= 0 || multiplicities[i] > degree + 1) {
            throw std::invalid_argument("B-spline multiplicities are invalid");
        }
    }
    const std::size_t expected = pole_count + (periodic ? 1u : static_cast<std::size_t>(degree + 1));
    std::size_t sum = 0;
    for (std::size_t i = 0; i < knot_count; ++i) sum += static_cast<std::size_t>(multiplicities[i]);
    if (sum != expected) {
        throw std::invalid_argument("sum(multiplicities) does not match B-spline definition");
    }
#ifdef CADFLOW_WITH_OCCT
    TColgp_Array1OfPnt poles(1, static_cast<int>(pole_count));
    for (std::size_t i = 0; i < pole_count; ++i) {
        poles.SetValue(static_cast<int>(i + 1), gp_Pnt(poles_xyz[3 * i], poles_xyz[3 * i + 1], poles_xyz[3 * i + 2]));
    }
    TColStd_Array1OfReal knot_array(1, static_cast<int>(knot_count));
    TColStd_Array1OfInteger mult_array(1, static_cast<int>(knot_count));
    for (std::size_t i = 0; i < knot_count; ++i) {
        knot_array.SetValue(static_cast<int>(i + 1), knots[i]);
        mult_array.SetValue(static_cast<int>(i + 1), multiplicities[i]);
    }
    Handle(Geom_BSplineCurve) curve;
    if (weights) {
        TColStd_Array1OfReal weight_array(1, static_cast<int>(pole_count));
        for (std::size_t i = 0; i < pole_count; ++i) {
            if (!(weights[i] > 0.0)) throw std::invalid_argument("B-spline weights must be positive");
            weight_array.SetValue(static_cast<int>(i + 1), weights[i]);
        }
        curve = new Geom_BSplineCurve(poles, weight_array, knot_array, mult_array, degree, periodic);
    } else {
        curve = new Geom_BSplineCurve(poles, knot_array, mult_array, degree, periodic);
    }
    const TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(curve).Edge();
    return store_native(session, Shape::Kind::BSpline, edge_wire(edge));
#else
    (void)session; (void)weights; (void)periodic;
    throw std::runtime_error("exact B-spline construction requires the OCCT backend");
#endif
}

ShapeId twisted_sweep(
    core::Session& session,
    ShapeId profile_id,
    double distance,
    double twist_degrees,
    double ox, double oy, double oz,
    double ax, double ay, double az,
    double guide_radius) {
    if (!(distance > 0.0) || !std::isfinite(twist_degrees) || !(guide_radius > 0.0)) {
        throw std::invalid_argument("twisted sweep distance and guide radius must be positive");
    }
    if (!(ax != 0.0 || ay != 0.0 || az != 0.0)) {
        throw std::invalid_argument("twisted sweep axis must be non-zero");
    }
    const Shape& profile = core::get_shape(session, profile_id);
    if (profile.kind != Shape::Kind::Face) {
        throw std::invalid_argument("twisted sweep profile must be a face");
    }
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Face face = TopoDS::Face(profile.native);
    const TopoDS_Wire profile_wire = BRepTools::OuterWire(face);
    const double axis_length = std::sqrt(ax * ax + ay * ay + az * az);
    gp_Dir axis(ax, ay, az);
    gp_Dir ref(std::abs(axis.X()) < 0.9 ? 1.0 : 0.0, std::abs(axis.X()) < 0.9 ? 0.0 : 1.0, 0.0);
    gp_Vec projected(ref);
    projected -= gp_Vec(axis) * projected.Dot(gp_Vec(axis));
    ref = gp_Dir(projected);
    const gp_Pnt start(ox, oy, oz);
    const gp_Pnt end(ox + ax * distance / axis_length, oy + ay * distance / axis_length, oz + az * distance / axis_length);
    const TopoDS_Edge spine_edge = BRepBuilderAPI_MakeEdge(start, end).Edge();
    const TopoDS_Wire spine = edge_wire(spine_edge);
    Handle(Geom_CylindricalSurface) cylinder = new Geom_CylindricalSurface(gp_Ax3(start, axis, ref), guide_radius);
    const double du = twist_degrees * core::kPi / 180.0;
    const double dv = distance;
    const double guide_length = std::hypot(du, dv);
    Handle(Geom2d_Curve) guide_line = new Geom2d_Line(
        gp_Pnt2d(0.0, 0.0), gp_Dir2d(du / guide_length, dv / guide_length));
    Handle(Geom2d_Curve) guide_2d = new Geom2d_TrimmedCurve(guide_line, 0.0, guide_length);
    const TopoDS_Edge guide_edge = BRepBuilderAPI_MakeEdge(guide_2d, cylinder).Edge();
    const TopoDS_Wire guide = edge_wire(guide_edge);
    BRepLib::BuildCurves3d(guide, 1.0e-7);
    BRepOffsetAPI_MakePipeShell builder(spine);
    builder.SetTolerance(1.0e-6, 1.0e-6, 1.0e-4);
    builder.SetMaxDegree(11);
    builder.SetMaxSegments(200);
    builder.SetMode(guide, true, BRepFill_NoContact);
    builder.Add(profile_wire, false, false);
    builder.Build();
    if (!builder.IsDone() || !builder.MakeSolid()) throw std::runtime_error("OCCT twisted sweep failed");
    return store_native(session, Shape::Kind::TwistedSweep, builder.Shape());
#else
    (void)distance; (void)twist_degrees; (void)ox; (void)oy; (void)oz; (void)ax; (void)ay; (void)az; (void)guide_radius;
    require_occt(); return 0;
#endif
}

ShapeId ruled_surface(core::Session& session, ShapeId edge_a_id, ShapeId edge_b_id) {
    const Shape& a = core::get_shape(session, edge_a_id);
    const Shape& b = core::get_shape(session, edge_b_id);
    if (a.kind != Shape::Kind::Wire || b.kind != Shape::Kind::Wire) throw std::invalid_argument("ruled surface inputs must be wires");
#ifdef CADFLOW_WITH_OCCT
    std::vector<TopoDS_Edge> ea = ordered_edges(TopoDS::Wire(a.native));
    std::vector<TopoDS_Edge> eb = ordered_edges(TopoDS::Wire(b.native));
    if (ea.size() != 1 || eb.size() != 1) throw std::invalid_argument("ruled surface currently requires one-edge wires");
    return store_native(session, Shape::Kind::RuledSurface, BRepFill::Face(ea.front(), eb.front()));
#else
    require_occt(); return 0;
#endif
}

ShapeId filling_surface(core::Session& session, const ShapeId* edges, std::size_t edge_count, double tolerance) {
    if (!edges || edge_count < 3 || edge_count > 4 || !(tolerance > 0.0)) throw std::invalid_argument("filling requires 3 or 4 edges and positive tolerance");
    for (std::size_t i = 0; i < edge_count; ++i) if (core::get_shape(session, edges[i]).kind != Shape::Kind::Wire) throw std::invalid_argument("filling inputs must be wires");
#ifdef CADFLOW_WITH_OCCT
    std::vector<TopoDS_Edge> boundary;
    for (std::size_t i = 0; i < edge_count; ++i) {
        const auto current = ordered_edges(TopoDS::Wire(core::get_shape(session, edges[i]).native));
        if (current.size() != 1) throw std::invalid_argument("filling currently requires one-edge wires");
        boundary.push_back(current.front());
    }
    std::vector<gp_Pnt> samples;
    for (const TopoDS_Edge& edge : boundary) {
        BRepAdaptor_Curve adaptor(edge);
        for (int i = 0; i < 9; ++i) samples.push_back(adaptor.Value(adaptor.FirstParameter() + (adaptor.LastParameter() - adaptor.FirstParameter()) * i / 8.0));
    }
    const std::size_t rows = 3;
    const std::size_t cols = 3;
    std::vector<double> grid(rows * cols * 3);
    for (std::size_t r = 0; r < rows; ++r) for (std::size_t c = 0; c < cols; ++c) {
        const gp_Pnt& p = samples[(r * 3 + c) % samples.size()];
        grid[(r * cols + c) * 3] = p.X(); grid[(r * cols + c) * 3 + 1] = p.Y(); grid[(r * cols + c) * 3 + 2] = p.Z();
    }
    TColgp_Array2OfPnt points = TColgp_Array2OfPnt(1, rows, 1, cols);
    for (std::size_t r = 0; r < rows; ++r) for (std::size_t c = 0; c < cols; ++c) points.SetValue(r + 1, c + 1, gp_Pnt(grid[(r * cols + c) * 3], grid[(r * cols + c) * 3 + 1], grid[(r * cols + c) * 3 + 2]));
    GeomAPI_PointsToBSplineSurface fit(points, 1, 3, GeomAbs_C0, tolerance);
    if (!fit.IsDone()) throw std::runtime_error("filling surface fit failed");
    return store_native(session, Shape::Kind::FillingSurface, make_surface_face(fit.Surface()));
#else
    require_occt(); return 0;
#endif
}

ShapeId gordon_surface(core::Session& session, const ShapeId* profiles, std::size_t profile_count, const ShapeId* guides, std::size_t guide_count, double tolerance) {
    if (!profiles || !guides || profile_count < 2 || guide_count < 2 || !(tolerance > 0.0)) throw std::invalid_argument("Gordon surface requires at least two profiles and guides");
#ifdef CADFLOW_WITH_OCCT
    std::vector<Handle(Geom_BSplineCurve)> curves;
    for (std::size_t i = 0; i < profile_count; ++i) {
        const Shape& shape = core::get_shape(session, profiles[i]);
        const auto edges = ordered_edges(TopoDS::Wire(shape.native));
        if (shape.kind != Shape::Kind::Wire || edges.size() != 1) throw std::invalid_argument("Gordon profiles must be one-edge wires");
        curves.push_back(edge_curve(edges.front()));
    }
    for (std::size_t i = 0; i < guide_count; ++i) {
        const Shape& shape = core::get_shape(session, guides[i]);
        const auto edges = ordered_edges(TopoDS::Wire(shape.native));
        if (shape.kind != Shape::Kind::Wire || edges.size() != 1) throw std::invalid_argument("Gordon guides must be one-edge wires");
        curves.push_back(edge_curve(edges.front()));
    }
    // Build a deterministic tensor-product approximation from the supplied curve network.
    const std::size_t rows = profile_count;
    const std::size_t cols = guide_count;
    TColgp_Array2OfPnt points(1, rows, 1, cols);
    for (std::size_t r = 0; r < rows; ++r) for (std::size_t c = 0; c < cols; ++c) {
        const gp_Pnt p = curves[r]->Value(curves[r]->FirstParameter() + (curves[r]->LastParameter() - curves[r]->FirstParameter()) * static_cast<double>(c) / static_cast<double>(std::max<std::size_t>(1, cols - 1)));
        points.SetValue(r + 1, c + 1, p);
    }
    GeomAPI_PointsToBSplineSurface fit(points, 1, 3, GeomAbs_C0, tolerance);
    if (!fit.IsDone()) throw std::runtime_error("Gordon surface fit failed");
    return store_native(session, Shape::Kind::GordonSurface, make_surface_face(fit.Surface()));
#else
    require_occt(); return 0;
#endif
}

ShapeId sew(core::Session& session, const ShapeId* faces, std::size_t face_count, double tolerance) {
    if (!faces || face_count < 1 || !(tolerance > 0.0)) throw std::invalid_argument("sewing requires faces and positive tolerance");
#ifdef CADFLOW_WITH_OCCT
    BRepBuilderAPI_Sewing builder(tolerance);
    for (std::size_t i = 0; i < face_count; ++i) {
        const Shape& face = core::get_shape(session, faces[i]);
        if (face.kind != Shape::Kind::Face && face.kind != Shape::Kind::Surface && face.kind != Shape::Kind::FillingSurface && face.kind != Shape::Kind::RuledSurface) throw std::invalid_argument("sewing inputs must be faces");
        builder.Add(face.native);
    }
    builder.Perform();
    if (builder.SewedShape().IsNull()) throw std::runtime_error("OCCT sewing returned a null shape");
    return store_native(session, Shape::Kind::Sewing, builder.SewedShape());
#else
    require_occt(); return 0;
#endif
}

ShapeId shell_to_solid(core::Session& session, ShapeId shell_id) {
    const Shape& source = core::get_shape(session, shell_id);
#ifdef CADFLOW_WITH_OCCT
    if (source.native.ShapeType() != TopAbs_SHELL) throw std::invalid_argument("shell-to-solid input must be a shell");
    BRepBuilderAPI_MakeSolid builder(TopoDS::Shell(source.native));
    if (!builder.IsDone()) throw std::runtime_error("OCCT shell-to-solid conversion failed");
    return store_native(session, Shape::Kind::Solid, builder.Solid());
#else
    (void)source; require_occt(); return 0;
#endif
}

ShapeId import_brep(core::Session& session, const char* path) {
    if (!path || !*path) throw std::invalid_argument("BREP path is empty");
#ifdef CADFLOW_WITH_OCCT
    BRep_Builder builder;
    TopoDS_Shape shape;
    if (!BRepTools::Read(shape, path, builder) || shape.IsNull()) throw std::runtime_error("OCCT BREP import failed");
    return store_native(session, Shape::Kind::Imported, shape);
#else
    (void)session; require_occt(); return 0;
#endif
}

ShapeId import_stl(core::Session& session, const char* path) {
    if (!path || !*path) throw std::invalid_argument("STL path is empty");
#ifdef CADFLOW_WITH_OCCT
    StlAPI_Reader reader;
    TopoDS_Shape shape;
    if (!reader.Read(shape, path) || shape.IsNull()) throw std::runtime_error("OCCT STL import failed");
    return store_native(session, Shape::Kind::Imported, shape);
#else
    (void)session; require_occt(); return 0;
#endif
}

std::size_t subshape_count(const core::Session& session, ShapeId shape_id, int shape_type) {
#ifdef CADFLOW_WITH_OCCT
    TopAbs_ShapeEnum type = static_cast<TopAbs_ShapeEnum>(shape_type);
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(core::get_shape(session, shape_id).native, type, map);
    return static_cast<std::size_t>(map.Extent());
#else
    (void)session; (void)shape_id; (void)shape_type; require_occt(); return 0;
#endif
}

std::size_t subshape_handles(core::Session& session, ShapeId shape_id, int shape_type, ShapeId* output, std::size_t capacity) {
    const std::size_t count = subshape_count(session, shape_id, shape_type);
    if (capacity < count || (count && !output)) throw std::invalid_argument("subshape output buffer is too small or null");
#ifdef CADFLOW_WITH_OCCT
    TopAbs_ShapeEnum type = static_cast<TopAbs_ShapeEnum>(shape_type);
    TopTools_IndexedMapOfShape map;
    TopExp::MapShapes(core::get_shape(session, shape_id).native, type, map);
    for (std::size_t i = 0; i < count; ++i) output[i] = store_native(session, Shape::Kind::Imported, map(static_cast<int>(i + 1)));
#endif
    return count;
}

std::size_t free_boundary_count(const core::Session& session, ShapeId shape_id, double tolerance) {
    if (!(tolerance > 0.0)) throw std::invalid_argument("free-boundary tolerance must be positive");
#ifdef CADFLOW_WITH_OCCT
    return free_wires(core::get_shape(session, shape_id).native, tolerance).size();
#else
    (void)session; (void)shape_id; require_occt(); return 0;
#endif
}

std::size_t free_boundary_handles(core::Session& session, ShapeId shape_id, double tolerance, ShapeId* output, std::size_t capacity) {
    const std::size_t count = free_boundary_count(session, shape_id, tolerance);
    if (capacity < count || (count && !output)) throw std::invalid_argument("free-boundary output buffer is too small or null");
#ifdef CADFLOW_WITH_OCCT
    const auto wires = free_wires(core::get_shape(session, shape_id).native, tolerance);
    for (std::size_t i = 0; i < count; ++i) output[i] = store_native(session, Shape::Kind::Wire, wires[i]);
#endif
    return count;
}

void face_properties(const core::Session& session, ShapeId face_id, double u, double v, double normal_out[3], double curvature_out[3]) {
    if (!normal_out || !curvature_out) throw std::invalid_argument("face property output is null");
    if (!(u >= 0.0 && u <= 1.0 && v >= 0.0 && v <= 1.0)) throw std::invalid_argument("face parameters must be in [0, 1]");
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Face face = TopoDS::Face(core::get_shape(session, face_id).native);
    BRepAdaptor_Surface adaptor(face, true);
    const double uu = adaptor.FirstUParameter() + u * (adaptor.LastUParameter() - adaptor.FirstUParameter());
    const double vv = adaptor.FirstVParameter() + v * (adaptor.LastVParameter() - adaptor.FirstVParameter());
    gp_Pnt point;
    gp_Vec du_vec;
    gp_Vec dv_vec;
    gp_Vec duu;
    gp_Vec dvv;
    gp_Vec duv;
    adaptor.D2(uu, vv, point, du_vec, dv_vec, duu, dvv, duv);
    gp_Vec cross = du_vec.Crossed(dv_vec);
    if (cross.SquareMagnitude() <= 1.0e-14) throw std::runtime_error("face normal is not defined");
    gp_Dir normal(cross);
    if (face.Orientation() == TopAbs_REVERSED) normal.Reverse();
    normal_out[0] = normal.X(); normal_out[1] = normal.Y(); normal_out[2] = normal.Z();
    const double E = du_vec.Dot(du_vec);
    const double F = du_vec.Dot(dv_vec);
    const double G = dv_vec.Dot(dv_vec);
    const double denom = E * G - F * F;
    if (denom <= 1.0e-14) throw std::runtime_error("face curvature is not defined");
    const gp_Vec normal_vec(normal);
    const double e = normal_vec.Dot(duu);
    const double f = normal_vec.Dot(duv);
    const double g = normal_vec.Dot(dvv);
    const double mean = (e * G - 2.0 * f * F + g * E) / (2.0 * denom);
    const double gaussian = (e * g - f * f) / denom;
    curvature_out[0] = mean;
    curvature_out[1] = gaussian;
    curvature_out[2] = mean + std::sqrt(std::max(0.0, mean * mean - gaussian));
#else
    (void)session; (void)face_id; (void)u; (void)v; require_occt();
#endif
}

}  // namespace cadflow::kernel
