#include "kernel/smooth_fillet.h"

#include "kernel/blend.h"
#include "kernel/differential.h"

#include <algorithm>
#include <atomic>
#include <exception>
#include <memory>
#include <mutex>
#include <thread>
#include <cmath>
#include <numeric>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#ifdef CADFLOW_WITH_OCCT
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Curve2d.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakeSolid.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepBuilderAPI_Sewing.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepGProp.hxx>
#include <BRepLib.hxx>
#include <BRepTools.hxx>
#include <BRepTools_ReShape.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BSplCLib.hxx>
#include <BRep_Builder.hxx>
#include <BRep_Tool.hxx>
#include <GProp_GProps.hxx>
#include <Geom2dAPI_Interpolate.hxx>
#include <Geom2dAPI_ProjectPointOnCurve.hxx>
#include <Geom2d_BSplineCurve.hxx>
#include <Geom2d_Curve.hxx>
#include <Geom2d_Line.hxx>
#include <Geom2d_TrimmedCurve.hxx>
#include <GeomAPI_ProjectPointOnSurf.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_Curve.hxx>
#include <Geom_Surface.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColStd_HArray1OfReal.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColgp_HArray1OfPnt2d.hxx>
#include <TopAbs.hxx>
#include <math_Matrix.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shell.hxx>
#include <TopoDS_Solid.hxx>
#include <TopoDS_Vertex.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Dir2d.hxx>
#include <gp_Pln.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Vec.hxx>
#endif

namespace cadflow::kernel {
namespace {

#ifdef CADFLOW_WITH_OCCT

/* Spring (trim) edges are tangent to the round; end edges meet it at an angle. */
constexpr double kTangentCosine = 0.99984769515639127;  // cos(1 degree)
/* Parameter agreement for OCCT's iso-parametric fillet pcurves. */
constexpr double kParameterTolerance = 1.0e-6;
constexpr double kPi = 3.14159265358979323846;

gp_Vec normal_along_edge(const TopoDS_Face& face, const TopoDS_Edge& edge, double fraction) {
    const BRepAdaptor_Curve2d pcurve(edge, face);
    const double t = pcurve.FirstParameter()
        + (pcurve.LastParameter() - pcurve.FirstParameter()) * fraction;
    const gp_Pnt2d uv = pcurve.Value(t);
    const BRepAdaptor_Surface surface(face, false);
    const differential::LocalGeometry local = differential::evaluate(
        surface, face.Orientation() == TopAbs_REVERSED, uv.X(), uv.Y());
    if (!local.regular) {
        throw std::runtime_error("smooth fillet met an undefined face normal");
    }
    return local.normal;
}

bool tangent_along(const TopoDS_Face& a, const TopoDS_Face& b, const TopoDS_Edge& edge) {
    for (double fraction : {0.25, 0.5, 0.75}) {
        if (normal_along_edge(a, edge, fraction).Dot(normal_along_edge(b, edge, fraction))
            < kTangentCosine) {
            return false;
        }
    }
    return true;
}

TopoDS_Face other_face(
    const TopTools_IndexedDataMapOfShapeListOfShape& ancestors,
    const TopoDS_Edge& edge, const TopoDS_Face& face) {
    TopoDS_Face result;
    int count = 0;
    for (TopTools_ListOfShape::Iterator it(ancestors.FindFromKey(edge)); it.More(); it.Next()) {
        if (!it.Value().IsSame(face)) {
            if (count == 0 || !it.Value().IsSame(result)) {
                result = TopoDS::Face(it.Value());
                ++count;
            }
        }
    }
    if (count != 1) {
        throw std::runtime_error("smooth fillet requires manifold edges around each round");
    }
    return result;
}

/* The face as it is oriented inside `shape`. */
TopoDS_Face oriented_face(const TopoDS_Shape& shape, const TopoDS_Shape& face) {
    for (TopExp_Explorer explorer(shape, TopAbs_FACE); explorer.More(); explorer.Next()) {
        if (explorer.Current().IsSame(face)) {
            return TopoDS::Face(explorer.Current());
        }
    }
    throw std::runtime_error("round face is missing from the filleted solid");
}

/* Edge on the blend's iso-v end section, oriented like `old_edge` and bound
   by its vertices so the end face keeps its topology. */
TopoDS_Edge section_edge(const Handle(Geom_Curve)& section, const TopoDS_Edge& old_edge) {
    TopoDS_Vertex first;
    TopoDS_Vertex last;
    TopExp::Vertices(old_edge, first, last);  // forward orientation
    Handle(Geom_Curve) curve = section;
    const gp_Pnt start = curve->Value(curve->FirstParameter());
    if (start.Distance(BRep_Tool::Pnt(first)) > start.Distance(BRep_Tool::Pnt(last))) {
        curve = curve->Reversed();
    }
    BRepBuilderAPI_MakeEdge builder(
        curve, first, last, curve->FirstParameter(), curve->LastParameter());
    if (!builder.IsDone()) {
        throw std::runtime_error("smooth fillet could not rebuild an end-face edge");
    }
    TopoDS_Edge edge = builder.Edge();
    BRepLib::SameParameter(edge, 1.0e-7);
    return edge;
}

/* Re-bound a planar end face with the blend section that now ends the round. */
void replace_cap_edge(
    BRepTools_ReShape& reshape, const TopoDS_Face& cap, const TopoDS_Edge& edge,
    const Handle(Geom_Curve)& section, double tolerance) {
    const BRepAdaptor_Surface cap_surface(cap, false);
    if (cap_surface.GetType() != GeomAbs_Plane) {
        throw std::runtime_error("smooth fillet currently requires planar end faces");
    }
    const gp_Pln plane = cap_surface.Plane();
    for (int sample = 0; sample <= 8; ++sample) {
        const gp_Pnt point = section->Value(
            section->FirstParameter()
            + (section->LastParameter() - section->FirstParameter()) * sample / 8.0);
        if (plane.Distance(point) > 10.0 * tolerance) {
            throw std::runtime_error(
                "smooth fillet end section leaves its planar end face; the filleted "
                "edge must meet its end faces perpendicularly");
        }
    }
    /* section_edge follows the old edge's forward direction, so the
       replacement must be recorded against the forward orientation. */
    reshape.Replace(edge.Oriented(TopAbs_FORWARD), section_edge(section, edge));
}

/* Run body(0) .. body(count - 1) on the hardware threads; rethrows the
   first exception. */
template <typename Body>
void parallel_for(std::size_t count, const Body& body) {
    const std::size_t threads = std::min<std::size_t>(
        count, std::max(1u, std::thread::hardware_concurrency()));
    if (threads <= 1) {
        for (std::size_t k = 0; k < count; ++k) body(k);
        return;
    }
    std::atomic<std::size_t> next {0};
    std::exception_ptr failure;
    std::mutex failure_mutex;
    std::vector<std::thread> workers;
    for (std::size_t t = 0; t < threads; ++t) {
        workers.emplace_back([&]() {
            for (std::size_t k = next++; k < count; k = next++) {
                try {
                    body(k);
                } catch (...) {
                    const std::lock_guard<std::mutex> lock(failure_mutex);
                    if (!failure) failure = std::current_exception();
                    next = count;
                }
            }
        });
    }
    for (std::thread& worker : workers) worker.join();
    if (failure) std::rethrow_exception(failure);
}

/* ---------------------------------------------------------------------------
   Rounds. OCCT's fillet surface is swept by rolling-ball sections: its two
   trim lines (springs) are iso-parametric at cross values c_A and c_B, and the
   other parameter t runs along the spine. The replacement blend B(u, v) keeps
   v = t, so section t of the blend joins the same two contact points as
   OCCT's section t, and u = 0 / 1 are the springs.
   ------------------------------------------------------------------------- */

enum class EndKind { Cap, Junction, Miter, Corner };

struct RoundEnd {
    EndKind kind {EndKind::Cap};
    TopoDS_Edge edge;
    TopoDS_Face neighbour;
    /* Round index for Junction / Miter, corner index for Corner. */
    int other {-1};
};

struct Spring {
    TopoDS_Edge edge;
    TopoDS_Face support;
    double cross {0.0};
    double first {0.0};
    double last {0.0};
    Handle(Geom2d_Curve) on_round;
    double on_round_first {0.0};
    double on_round_last {0.0};
    Handle(Geom2d_Curve) on_support;
    Handle(BRepAdaptor_Curve) curve;
    Handle(BRepAdaptor_Surface) surface;
    Handle(Geom_Surface) geometry;
    bool reversed {false};
};

struct Round {
    TopoDS_Face face;
    Handle(Geom_Surface) surface;
    bool cross_u {true};
    Spring spring[2];
    double first {0.0};
    double last {0.0};
    RoundEnd ends[2];
    bool fixed[2] {false, false};
    BlendFrames end_frames[2];
    /* Spine extension beyond a miter end, where the blends are intersected. */
    double margin[2] {0.0, 0.0};
    int chain {-1};
    BlendGeometry blend;
    /* u-v polyline of a miter end, ordered so the face loop runs
       (0, bottom) -> (1, bottom) -> (1, top) -> (0, top). */
    std::vector<gp_Pnt2d> miter[2];
};

double spine_of(const Round& round, const gp_Pnt2d& uv) {
    return round.cross_u ? uv.Y() : uv.X();
}

double cross_of(const Round& round, const gp_Pnt2d& uv) {
    return round.cross_u ? uv.X() : uv.Y();
}

void round_d1(
    const Round& round, double cross, double spine, gp_Pnt& point,
    gp_Vec& d_cross, gp_Vec& d_spine) {
    gp_Vec du;
    gp_Vec dv;
    if (round.cross_u) {
        round.surface->D1(cross, spine, point, du, dv);
        d_cross = du;
        d_spine = dv;
    } else {
        round.surface->D1(spine, cross, point, du, dv);
        d_cross = dv;
        d_spine = du;
    }
}

/* Support frame where section `spine` of the round touches spring `side`. */
BlendFrame contact_frame(const Round& round, int side, double spine) {
    const Spring& spring = round.spring[side];
    gp_Pnt contact;
    gp_Vec d_cross;
    gp_Vec d_spine;
    round_d1(round, spring.cross, spine, contact, d_cross, d_spine);
    if (round.spring[1 - side].cross < spring.cross) {
        d_cross.Reverse();  // towards the other spring
    }
    double su = 0.0;
    double sv = 0.0;
    gp_Pnt point;
    if (spine >= spring.first - kParameterTolerance && spine <= spring.last + kParameterTolerance) {
        /* On the trim line: use the shared edge's own point and pcurve. */
        const gp_Pnt2d uv = round.cross_u ? gp_Pnt2d(spring.cross, spine)
                                          : gp_Pnt2d(spine, spring.cross);
        Geom2dAPI_ProjectPointOnCurve projection(
            uv, spring.on_round, spring.on_round_first, spring.on_round_last);
        double parameter = 0.0;
        if (projection.NbPoints() > 0) {
            parameter = projection.LowerDistanceParameter();
        } else {
            const gp_Pnt2d start = spring.on_round->Value(spring.on_round_first);
            parameter = uv.Distance(start) < kParameterTolerance
                ? spring.on_round_first : spring.on_round_last;
        }
        point = spring.curve->Value(parameter);
        const gp_Pnt2d support_uv = spring.on_support->Value(parameter);
        su = support_uv.X();
        sv = support_uv.Y();
    } else {
        /* Past the trim line (a miter end): the round's own contact curve on
           the support's extension. */
        GeomAPI_ProjectPointOnSurf projection(contact, spring.geometry);
        if (projection.NbPoints() == 0) {
            throw std::runtime_error("smooth fillet could not extend a trim line");
        }
        projection.LowerDistanceParameters(su, sv);
        point = projection.NearestPoint();
    }
    const differential::LocalGeometry local =
        differential::evaluate(*spring.surface, spring.reversed, su, sv);
    if (!local.regular) {
        throw std::runtime_error("smooth fillet met an undefined support normal");
    }
    const gp_Vec normal = local.normal;
    gp_Vec tangent = d_spine - normal * d_spine.Dot(normal);
    gp_Vec out = d_cross - normal * d_cross.Dot(normal);
    if (tangent.Magnitude() <= 1.0e-12 * d_spine.Magnitude() + 1.0e-300) {
        throw std::runtime_error("smooth fillet met a degenerate trim line");
    }
    tangent.Normalize();
    out -= tangent * out.Dot(tangent);
    if (out.Magnitude() <= 1.0e-300) {
        throw std::runtime_error("smooth fillet met a degenerate round section");
    }
    out.Normalize();
    BlendFrame frame;
    frame.point = point;
    frame.normal = normal;
    frame.out = out;
    frame.curvature = differential::normal_curvature(local, out);
    if (!std::isfinite(frame.curvature)) {
        throw std::runtime_error("smooth fillet support curvature is undefined");
    }
    return frame;
}

BlendFrames round_frames(const Round& round, double spine) {
    if (spine == round.first && round.fixed[0]) return round.end_frames[0];
    if (spine == round.last && round.fixed[1]) return round.end_frames[1];
    return {contact_frame(round, 0, spine), contact_frame(round, 1, spine)};
}

BlendFrame average(const BlendFrame& a, const BlendFrame& b) {
    BlendFrame output;
    output.point = gp_Pnt((a.point.XYZ() + b.point.XYZ()) * 0.5);
    output.normal = (a.normal + b.normal).Normalized();
    output.out = (a.out + b.out);
    output.out -= output.normal * output.out.Dot(output.normal);
    output.out.Normalize();
    output.curvature = 0.5 * (a.curvature + b.curvature);
    return output;
}

/* (u, v) of a pcurve's ends on the round face. */
void pcurve_ends(
    const Round& round, const TopoDS_Edge& edge, gp_Pnt2d& start, gp_Pnt2d& end) {
    double first = 0.0;
    double last = 0.0;
    const Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(edge, round.face, first, last);
    if (pcurve.IsNull()) {
        throw std::runtime_error("round edge has no pcurve on the round face");
    }
    start = pcurve->Value(first);
    end = pcurve->Value(last);
}

Spring make_spring(const TopoDS_Face& face, const TopoDS_Edge& edge, const TopoDS_Face& support) {
    Spring spring;
    spring.edge = edge;
    spring.support = support;
    spring.on_round = BRep_Tool::CurveOnSurface(edge, face, spring.on_round_first, spring.on_round_last);
    double first = 0.0;
    double last = 0.0;
    spring.on_support = BRep_Tool::CurveOnSurface(edge, support, first, last);
    if (spring.on_round.IsNull() || spring.on_support.IsNull()) {
        throw std::runtime_error("trim line is missing a pcurve");
    }
    spring.curve = new BRepAdaptor_Curve(edge);
    spring.surface = new BRepAdaptor_Surface(support, false);
    spring.geometry = BRep_Tool::Surface(support);
    spring.reversed = support.Orientation() == TopAbs_REVERSED;
    return spring;
}

/* Fill in springs, cross direction, and spine range; ends are classified later. */
Round make_round(
    const TopoDS_Face& face,
    const std::vector<std::pair<TopoDS_Edge, TopoDS_Face>>& springs) {
    Round round;
    round.face = face;
    round.surface = BRep_Tool::Surface(face);
    bool iso_u = true;
    bool iso_v = true;
    for (const auto& [edge, support] : springs) {
        double first = 0.0;
        double last = 0.0;
        const Handle(Geom2d_Curve) pcurve = BRep_Tool::CurveOnSurface(edge, face, first, last);
        const gp_Pnt2d a = pcurve->Value(first);
        const gp_Pnt2d b = pcurve->Value(last);
        const gp_Pnt2d m = pcurve->Value(0.5 * (first + last));
        iso_u = iso_u && std::abs(a.X() - b.X()) < kParameterTolerance
            && std::abs(a.X() - m.X()) < kParameterTolerance;
        iso_v = iso_v && std::abs(a.Y() - b.Y()) < kParameterTolerance
            && std::abs(a.Y() - m.Y()) < kParameterTolerance;
    }
    if (iso_u == iso_v) {
        throw std::runtime_error(
            "smooth fillet needs round faces whose trim lines are iso-parameter lines");
    }
    round.cross_u = iso_u;
    for (int side = 0; side < 2; ++side) {
        round.spring[side] = make_spring(face, springs[side].first, springs[side].second);
        Spring& spring = round.spring[side];
        const gp_Pnt2d a = spring.on_round->Value(spring.on_round_first);
        const gp_Pnt2d b = spring.on_round->Value(spring.on_round_last);
        spring.cross = cross_of(round, a);
        spring.first = std::min(spine_of(round, a), spine_of(round, b));
        spring.last = std::max(spine_of(round, a), spine_of(round, b));
    }
    if (std::abs(round.spring[0].cross - round.spring[1].cross) < kParameterTolerance) {
        throw std::runtime_error("round trim lines coincide");
    }
    double u_min = 0.0;
    double u_max = 0.0;
    double v_min = 0.0;
    double v_max = 0.0;
    BRepTools::UVBounds(face, u_min, u_max, v_min, v_max);
    round.first = round.cross_u ? v_min : u_min;
    round.last = round.cross_u ? v_max : u_max;
    return round;
}

/* Which end (0 = spine start, 1 = spine end) a non-spring edge closes, or -1. */
int end_of(const Round& round, const TopoDS_Edge& edge) {
    gp_Pnt2d a;
    gp_Pnt2d b;
    pcurve_ends(round, edge, a, b);
    for (int end = 0; end < 2; ++end) {
        const gp_Pnt2d corner_a = round.cross_u
            ? gp_Pnt2d(round.spring[0].cross, end ? round.spring[0].last : round.spring[0].first)
            : gp_Pnt2d(end ? round.spring[0].last : round.spring[0].first, round.spring[0].cross);
        const gp_Pnt2d corner_b = round.cross_u
            ? gp_Pnt2d(round.spring[1].cross, end ? round.spring[1].last : round.spring[1].first)
            : gp_Pnt2d(end ? round.spring[1].last : round.spring[1].first, round.spring[1].cross);
        const bool forward = a.Distance(corner_a) < kParameterTolerance
            && b.Distance(corner_b) < kParameterTolerance;
        const bool backward = a.Distance(corner_b) < kParameterTolerance
            && b.Distance(corner_a) < kParameterTolerance;
        if (forward || backward) return end;
    }
    return -1;
}

bool iso_end(const Round& round, int end) {
    const double a = end ? round.spring[0].last : round.spring[0].first;
    const double b = end ? round.spring[1].last : round.spring[1].first;
    const double t = end ? round.last : round.first;
    return std::abs(a - b) < kParameterTolerance && std::abs(a - t) < kParameterTolerance;
}

double end_spine(const Round& round, int end) { return end ? round.last : round.first; }

/* Blend surface B(u, v) and its parameter at (blend u, OCCT cross value). */
double blend_u(const Round& round, double cross) {
    return (cross - round.spring[0].cross) / (round.spring[1].cross - round.spring[0].cross);
}

/* Solve B_r(u_r, v_r) = B_q(u_q, v_q) with u_r fixed (Newton). */
bool intersect_blends(
    const Handle(Geom_BSplineSurface)& r, const Handle(Geom_BSplineSurface)& q,
    double u_r, double& v_r, double& u_q, double& v_q) {
    for (int iteration = 0; iteration < 50; ++iteration) {
        gp_Pnt pr;
        gp_Pnt pq;
        gp_Vec ru;
        gp_Vec rv;
        gp_Vec qu;
        gp_Vec qv;
        r->D1(u_r, v_r, pr, ru, rv);
        q->D1(u_q, v_q, pq, qu, qv);
        const gp_Vec f(pq, pr);  // B_r - B_q
        if (f.Magnitude() < 1.0e-12) return true;
        /* J [dv_r, du_q, dv_q] = -f with J = [rv, -qu, -qv]. */
        const gp_Vec c1 = rv;
        const gp_Vec c2 = -qu;
        const gp_Vec c3 = -qv;
        const double det = c1.Dot(c2.Crossed(c3));
        if (std::abs(det) < 1.0e-300) return false;
        const gp_Vec rhs = -f;
        const double d1 = rhs.Dot(c2.Crossed(c3)) / det;
        const double d2 = c1.Dot(rhs.Crossed(c3)) / det;
        const double d3 = c1.Dot(c2.Crossed(rhs)) / det;
        v_r += d1;
        u_q += d2;
        v_q += d3;
        if (!std::isfinite(v_r) || !std::isfinite(u_q) || !std::isfinite(v_q)) return false;
    }
    return false;
}

/* Miter between two rounds that meet at an angle: the intersection of the two
   blends, seeded by OCCT's miter between the circular rounds. */
void compute_miter(std::vector<Round>& rounds, int r_index, int r_end) {
    Round& r = rounds[static_cast<std::size_t>(r_index)];
    const int q_index = r.ends[r_end].other;
    Round& q = rounds[static_cast<std::size_t>(q_index)];
    const TopoDS_Edge& edge = r.ends[r_end].edge;
    const int q_end = q.ends[0].kind == EndKind::Miter && q.ends[0].edge.IsSame(edge) ? 0 : 1;
    double first = 0.0;
    double last = 0.0;
    const Handle(Geom2d_Curve) on_r = BRep_Tool::CurveOnSurface(edge, r.face, first, last);
    double q_first = 0.0;
    double q_last = 0.0;
    const Handle(Geom2d_Curve) on_q = BRep_Tool::CurveOnSurface(edge, q.face, q_first, q_last);
    if (std::abs(first - q_first) > 1.0e-9 || std::abs(last - q_last) > 1.0e-9) {
        throw std::runtime_error("miter pcurves use different parameter ranges");
    }
    constexpr int samples = 64;
    std::vector<gp_Pnt2d> uv_r;
    std::vector<gp_Pnt2d> uv_q;
    double v_r = 0.0;
    double u_q = 0.0;
    double v_q = 0.0;
    for (int k = 0; k <= samples; ++k) {
        const double e = first + (last - first) * k / samples;
        const gp_Pnt2d guess_r = on_r->Value(e);
        const gp_Pnt2d guess_q = on_q->Value(e);
        double u_r = blend_u(r, cross_of(r, guess_r));
        if (k == 0 || k == samples) u_r = std::round(u_r);  // ends lie on the springs
        if (k == 0 || k == samples) {
            /* The miter ends where two springs meet. Both blends interpolate
               their springs exactly, so OCCT's vertex is the exact end; the
               blends may be tangent there, which stalls Newton. */
            v_r = spine_of(r, guess_r);
            u_q = std::round(blend_u(q, cross_of(q, guess_q)));
            v_q = spine_of(q, guess_q);
            uv_r.emplace_back(u_r, v_r);
            uv_q.emplace_back(u_q, v_q);
            continue;
        }
        if (!intersect_blends(r.blend.surface, q.blend.surface, u_r, v_r, u_q, v_q)) {
            /* Restart from OCCT's point if continuation lost the curve. */
            v_r = spine_of(r, guess_r);
            u_q = blend_u(q, cross_of(q, guess_q));
            v_q = spine_of(q, guess_q);
            if (!intersect_blends(r.blend.surface, q.blend.surface, u_r, v_r, u_q, v_q)) {
                throw std::runtime_error("smooth fillet could not intersect two mitred blends");
            }
        }
        if (u_q < -1.0e-7 || u_q > 1.0 + 1.0e-7) {
            throw std::runtime_error("smooth fillet miter leaves the neighbouring blend");
        }
        uv_r.emplace_back(u_r, v_r);
        uv_q.emplace_back(std::clamp(u_q, 0.0, 1.0), v_q);
    }
    auto store = [](Round& round, int end, std::vector<gp_Pnt2d> points) {
        /* Bottom runs u 0 -> 1, top runs u 1 -> 0. */
        const bool increasing = points.back().X() > points.front().X();
        if (increasing != (end == 0)) std::reverse(points.begin(), points.end());
        round.miter[end] = std::move(points);
    };
    store(r, r_end, uv_r);
    store(q, q_end, uv_q);
}

/* Solve the dense symmetric system A x = b for three right-hand sides. */
std::vector<gp_XYZ> solve(std::vector<double> a, std::vector<gp_XYZ> b) {
    const std::size_t n = b.size();
    for (std::size_t column = 0; column < n; ++column) {
        std::size_t pivot = column;
        for (std::size_t row = column + 1; row < n; ++row) {
            if (std::abs(a[row * n + column]) > std::abs(a[pivot * n + column])) pivot = row;
        }
        if (std::abs(a[pivot * n + column]) < 1.0e-300) {
            throw std::runtime_error("smooth fillet corner fit is singular");
        }
        if (pivot != column) {
            for (std::size_t k = 0; k < n; ++k) std::swap(a[pivot * n + k], a[column * n + k]);
            std::swap(b[pivot], b[column]);
        }
        for (std::size_t row = column + 1; row < n; ++row) {
            const double factor = a[row * n + column] / a[column * n + column];
            if (factor == 0.0) continue;
            for (std::size_t k = column; k < n; ++k) a[row * n + k] -= factor * a[column * n + k];
            b[row] -= b[column] * factor;
        }
    }
    std::vector<gp_XYZ> x(n);
    for (std::size_t i = n; i-- > 0;) {
        gp_XYZ sum = b[i];
        for (std::size_t k = i + 1; k < n; ++k) sum -= x[k] * a[i * n + k];
        x[i] = sum / a[i * n + i];
    }
    return x;
}

/* ---------------------------------------------------------------------------
   Corner patches. Where rounds meet at a vertex OCCT places a corner face
   bounded by round sections. It is replaced by an n-sided transfinite patch
   (Kato's scheme) over a regular n-gon: each side carries the second-order
   Taylor ribbon of its blend across the section, and weights prod_{j!=i}
   d_j^3 make the patch agree with every ribbon to second order, i.e. G2.
   A bubble-function correction fairs the interior without touching that
   boundary jet. The n-gon is split into n quads at the side midpoints and
   the centre; each becomes a degree-5 B-spline whose boundary pole rows are
   solved for the G1/G2 conditions and whose interior poles are fitted.
   ------------------------------------------------------------------------- */

struct CornerSide {
    int round {-1};
    int end {0};
    bool reversed {false};  // s runs from u = 1 to u = 0
};

class CornerPatch {
public:
    CornerPatch(const std::vector<Round>& rounds, std::vector<CornerSide> sides)
        : rounds_(rounds), sides_(std::move(sides)) {
        const int n = static_cast<int>(sides_.size());
        const double radius = 0.5 / std::sin(kPi / n);  // unit sides
        for (int k = 0; k < n; ++k) {
            const double angle = 2.0 * kPi * k / n;
            vertices_.emplace_back(radius * std::cos(angle), radius * std::sin(angle));
        }
        sin_angle_ = std::sin(kPi - 2.0 * kPi / n);
        /* Ribbon i leaves side i along a parameter direction (du, dv) of its
           round, interpolated between the two directions that reproduce the
           neighbouring sides at the patch corners: moving along side i+1 at
           unit domain speed raises d_i at rate sin(alpha) with s fixed at 1,
           so ribbon i must predict P_{i+1}'(0) there (and -P_{i-1}'(1) at
           s = 0). Any transversal direction in the round's tangent plane is
           G1, and the round's own second-order Taylor term along it makes the
           cross curvature the round's, i.e. G2. */
        for (int i = 0; i < n; ++i) {
            const int previous = (i + n - 1) % n;
            const int next = (i + 1) % n;
            const gp_XY start = direction(i, 0.0, -side_tangent(previous, 1.0) / sin_angle_);
            const gp_XY end = direction(i, 1.0, side_tangent(next, 0.0) / sin_angle_);
            const double inward = sides_[static_cast<std::size_t>(i)].end ? 1.0 : -1.0;
            if (!(start.Y() * inward > 0.0 && end.Y() * inward > 0.0)) {
                throw std::runtime_error(
                    "smooth fillet corner: a meeting round's section does not lead into the "
                    "corner patch; the corner is too irregular");
            }
            direction_start_.push_back(start);
            direction_end_.push_back(end);
        }
        twist_start_.assign(static_cast<std::size_t>(n), gp_XY(0.0, 0.0));
        twist_end_.assign(static_cast<std::size_t>(n), gp_XY(0.0, 0.0));
        second_start_.assign(static_cast<std::size_t>(n), gp_XYZ(0.0, 0.0, 0.0));
        second_end_.assign(static_cast<std::size_t>(n), gp_XYZ(0.0, 0.0, 0.0));
        /* The two ribbons meeting at a vertex agree to first order and in the
           normal part of their second derivatives (both rounds are G2 to the
           face the vertex lies on), but not in the tangential parts. Kato's
           blend then has a curvature spike at the vertex that no spline fit
           resolves. Each ribbon has tangential freedom that keeps its own
           side G2: the tangential part of its second-order term and the twist
           of its direction field. Spend it so the second derivatives of both
           ribbons coincide at every vertex; the terms decouple, so a few
           linear passes converge. */
    for (int pass = 0; pass < 3; ++pass) {
            for (int i = 0; i < n; ++i) {
                match_vertex(i);
            }
        }
    }

    int sides() const { return static_cast<int>(sides_.size()); }

    gp_Pnt2d vertex(int i) const { return vertices_[static_cast<std::size_t>(i % sides())]; }

    /* Ribbon i at domain point p; p may lie slightly outside the n-gon, so
       cross derivatives at side i can be taken by central differences. */
    gp_Pnt ribbon_at(int i, const gp_Pnt2d& p) const {
        const int n = sides();
        const double before = signed_distance((i + n - 1) % n, p);
        const double after = signed_distance((i + 1) % n, p);
        return ribbon(i, before / (before + after), signed_distance(i, p));
    }

    /* Patch point: Kato's interpolant plus the fairing correction. */
    gp_Pnt value(const gp_Pnt2d& p) const {
        gp_XYZ point = kato(p).XYZ();
        if (!coefficients_.empty()) {
            const std::vector<double> basis = bubbles(p);
            for (std::size_t k = 0; k < basis.size(); ++k) point += coefficients_[k] * basis[k];
        }
        return gp_Pnt(point);
    }

    /* Kato's scheme interpolates the ribbons to second order but, where they
       disagree inside the patch, leaves a band of uneven curvature near each
       side. Add sum c_k b(p) x^i y^j with b = prod_i d_i^3: every term
       vanishes to third order on every side, so the G2 boundary is untouched,
       and the c_k minimize the third-order (minimum variation) energy
       integral |F_xxx|^2 + 3|F_xxy|^2 + 3|F_xyy|^2 + |F_yyy|^2 over the
       domain, sampled on a grid. */
    void fair(int degree, int grid) {
        coefficients_.clear();
        degree_ = degree;
        double extent = 0.0;
        for (const gp_Pnt2d& vertex : vertices_) extent = std::max(extent, vertex.XY().Modulus());
        bubble_scale_ = 1.0;
        bubble_scale_ = 1.0 / std::max(1.0e-300, bubble(gp_Pnt2d(0.0, 0.0)));
        const double step = 2.0 * extent / grid;
        /* Stencil offsets and weights for the four third derivatives. */
        struct Term { int dx; int dy; double weight; };
        const std::vector<std::vector<Term>> operators {
            {{2, 0, 0.5}, {1, 0, -1.0}, {-1, 0, 1.0}, {-2, 0, -0.5}},
            {{1, 1, 0.5}, {-1, 1, 0.5}, {0, 1, -1.0}, {1, -1, -0.5}, {-1, -1, -0.5}, {0, -1, 1.0}},
            {{1, 1, 0.5}, {1, -1, 0.5}, {1, 0, -1.0}, {-1, 1, -0.5}, {-1, -1, -0.5}, {-1, 0, 1.0}},
            {{0, 2, 0.5}, {0, 1, -1.0}, {0, -1, 1.0}, {0, -2, -0.5}},
        };
        const double operator_weight[4] {1.0, 3.0, 3.0, 1.0};
        const std::size_t count = static_cast<std::size_t>((degree + 1) * (degree + 2) / 2);
        std::vector<double> normal(count * count, 0.0);
        std::vector<gp_XYZ> rhs(count, gp_XYZ(0.0, 0.0, 0.0));
        auto inside = [&](const gp_Pnt2d& p) {
            for (int i = 0; i < sides(); ++i) {
                if (signed_distance(i, p) <= 0.0) return false;
            }
            return true;
        };
        /* Every stencil point lies on the half-step lattice: evaluate the
           interpolant and the bubble basis once per lattice node. */
        const int reach = grid + 2;
        const int width = 2 * reach + 1;
        auto node = [&](int ix, int iy) {
            return static_cast<std::size_t>((ix + reach) * width + (iy + reach));
        };
        std::vector<char> usable_node(static_cast<std::size_t>(width * width), 0);
        std::vector<gp_XYZ> kato_node(static_cast<std::size_t>(width * width));
        std::vector<std::vector<double>> bubble_node(static_cast<std::size_t>(width * width));
        for (int ix = -reach; ix <= reach; ++ix) {
            for (int iy = -reach; iy <= reach; ++iy) {
                const gp_Pnt2d p(ix * step * 0.5, iy * step * 0.5);
                if (!inside(p)) continue;
                const std::size_t k = node(ix, iy);
                usable_node[k] = 1;
                kato_node[k] = kato(p).XYZ();
                bubble_node[k] = bubbles(p);
            }
        }
        for (int ix = -grid; ix <= grid; ++ix) {
            for (int iy = -grid; iy <= grid; ++iy) {
                bool usable = true;
                for (int dx = -2; dx <= 2 && usable; ++dx) {
                    for (int dy = -2; dy <= 2 && usable; ++dy) {
                        if (std::abs(dx) + std::abs(dy) > 2) continue;
                        usable = usable_node[node(ix + dx, iy + dy)] != 0;
                    }
                }
                if (!usable) continue;
                for (int o = 0; o < 4; ++o) {
                    gp_XYZ kato_term(0.0, 0.0, 0.0);
                    std::vector<double> row(count, 0.0);
                    for (const Term& term : operators[static_cast<std::size_t>(o)]) {
                        const std::size_t k = node(ix + term.dx, iy + term.dy);
                        kato_term += kato_node[k] * term.weight;
                        const std::vector<double>& basis = bubble_node[k];
                        for (std::size_t c = 0; c < count; ++c) row[c] += basis[c] * term.weight;
                    }
                    const double w = operator_weight[o];
                    for (std::size_t r = 0; r < count; ++r) {
                        rhs[r] -= kato_term * (w * row[r]);
                        for (std::size_t c = 0; c < count; ++c) normal[r * count + c] += w * row[r] * row[c];
                    }
                }
            }
        }
        double trace = 0.0;
        for (std::size_t k = 0; k < count; ++k) trace += normal[k * count + k];
        for (std::size_t k = 0; k < count; ++k) normal[k * count + k] += 1.0e-12 * trace / count;
        coefficients_ = solve(std::move(normal), std::move(rhs));
    }

    gp_Pnt kato(const gp_Pnt2d& p) const {
        const int n = sides();
        std::vector<double> d(static_cast<std::size_t>(n));
        int nearest = 0;
        for (int i = 0; i < n; ++i) {
            d[static_cast<std::size_t>(i)] = distance(i, p);
            if (d[static_cast<std::size_t>(i)] < d[static_cast<std::size_t>(nearest)]) nearest = i;
        }
        if (d[static_cast<std::size_t>(nearest)] < 1.0e-13) {
            return ribbon(nearest, parameter(nearest, d), 0.0);
        }
        gp_XYZ sum(0.0, 0.0, 0.0);
        double weights = 0.0;
        for (int i = 0; i < n; ++i) {
            const double di = d[static_cast<std::size_t>(i)];
            const double weight = 1.0 / (di * di * di);
            sum += ribbon(i, parameter(i, d), di).XYZ() * weight;
            weights += weight;
        }
        return gp_Pnt(sum / weights);
    }

private:
    /* Inward distance to side i's line (side i runs vertex i -> vertex i+1). */
    double signed_distance(int i, const gp_Pnt2d& p) const {
        const gp_Pnt2d a = vertex(i);
        const gp_Pnt2d b = vertex(i + 1);
        const double dx = b.X() - a.X();
        const double dy = b.Y() - a.Y();
        return ((p.X() - a.X()) * -dy + (p.Y() - a.Y()) * dx) / std::hypot(dx, dy);
    }

    double distance(int i, const gp_Pnt2d& p) const {
        return std::max(0.0, signed_distance(i, p));
    }

    double bubble(const gp_Pnt2d& p) const {
        double value = bubble_scale_;
        for (int i = 0; i < sides(); ++i) {
            const double d = distance(i, p);
            value *= d * d * d;
        }
        return value;
    }

    /* b(p) x^i y^j for i + j <= degree. */
    std::vector<double> bubbles(const gp_Pnt2d& p) const {
        const double base = bubble(p);
        std::vector<double> output;
        for (int total = 0; total <= degree_; ++total) {
            for (int i = 0; i <= total; ++i) {
                output.push_back(base * std::pow(p.X(), i) * std::pow(p.Y(), total - i));
            }
        }
        return output;
    }

    double parameter(int i, const std::vector<double>& d) const {
        const int n = sides();
        const double before = d[static_cast<std::size_t>((i + n - 1) % n)];
        const double after = d[static_cast<std::size_t>((i + 1) % n)];
        return before + after > 0.0 ? before / (before + after) : 0.5;
    }

    double blend_u(int i, double s) const {
        return sides_[static_cast<std::size_t>(i)].reversed ? 1.0 - s : s;
    }

    const Round& round(int i) const {
        return rounds_[static_cast<std::size_t>(sides_[static_cast<std::size_t>(i)].round)];
    }

    double spine(int i) const {
        return end_spine(round(i), sides_[static_cast<std::size_t>(i)].end);
    }

    /* Parameter-space components (du, dv) of the round's tangent vector w
       at side i, parameter s. */
    gp_XY direction(int i, double s, const gp_Vec& w, bool check = true) const {
        gp_Pnt point;
        gp_Vec du;
        gp_Vec dv;
        round(i).blend.surface->D1(blend_u(i, s), spine(i), point, du, dv);
        const double e = du.Dot(du);
        const double f = du.Dot(dv);
        const double g = dv.Dot(dv);
        const double determinant = e * g - f * f;
        if (!(determinant > 0.0)) {
            throw std::runtime_error("smooth fillet corner met a degenerate round");
        }
        const double a = (g * du.Dot(w) - f * dv.Dot(w)) / determinant;
        const double b = (e * dv.Dot(w) - f * du.Dot(w)) / determinant;
        const gp_Vec residual = w - du * a - dv * b;
        if (check && residual.Magnitude() > 1.0e-3 * w.Magnitude()) {
            throw std::runtime_error(
                "smooth fillet corner: meeting rounds do not share a tangent plane at a corner");
        }
        return gp_XY(a, b);
    }

    /* dP_i/ds along the side. */
    gp_Vec side_tangent(int i, double s) const {
        gp_Pnt point;
        gp_Vec du;
        gp_Vec dv;
        round(i).blend.surface->D1(blend_u(i, s), spine(i), point, du, dv);
        return sides_[static_cast<std::size_t>(i)].reversed ? -du : du;
    }

    /* Parameter direction of ribbon i: linear between the corner-matching
       ends plus Hermite twist terms that vanish at both ends. */
    gp_XY ribbon_direction(int i, double s) const {
        const std::size_t k = static_cast<std::size_t>(i);
        return direction_start_[k] * (1.0 - s) + direction_end_[k] * s
            + twist_start_[k] * (s * (1.0 - s) * (1.0 - s))
            - twist_end_[k] * (s * s * (1.0 - s));
    }

    gp_Pnt ribbon(int i, double s, double d) const {
        gp_Pnt point;
        gp_Vec du;
        gp_Vec dv;
        gp_Vec duu;
        gp_Vec dvv;
        gp_Vec duv;
        round(i).blend.surface->D2(blend_u(i, s), spine(i), point, du, dv, duu, dvv, duv);
        if (d == 0.0) return point;
        const gp_XY step = ribbon_direction(i, s) * d;
        /* Tangential second-order correction, projected so the cross
           curvature stays the round's. */
        const std::size_t k = static_cast<std::size_t>(i);
        gp_Vec extra(second_start_[k] * (1.0 - s) + second_end_[k] * s);
        gp_Vec normal = du.Crossed(dv);
        if (normal.Magnitude() > 1.0e-300) {
            normal.Normalize();
            extra -= normal * extra.Dot(normal);
        }
        return point.Translated(du * step.X() + dv * step.Y()
            + (duu * (step.X() * step.X()) + duv * (2.0 * step.X() * step.Y())
               + dvv * (step.Y() * step.Y()) + extra * (d * d)) * 0.5);
    }

    /* Second derivatives (xx, xy, yy) of ribbon j at vertex i in oblique
       coordinates p = v_i + x e + y f, e along side i and f along side i-1. */
    void vertex_hessian(int j, int i, gp_Vec output[3]) const {
        const gp_XY origin = vertex(i).XY();
        const gp_XY e = (vertex(i + 1).XY() - origin).Normalized();
        const gp_XY f = (vertex(i + sides() - 1).XY() - origin).Normalized();
        constexpr double h = 1.0e-3;
        auto at = [&](double x, double y) {
            return ribbon_at(j, gp_Pnt2d(origin + e * x + f * y)).XYZ();
        };
        const gp_XYZ centre = at(0.0, 0.0);
        output[0] = gp_Vec((at(h, 0.0) - centre * 2.0 + at(-h, 0.0)) / (h * h));
        output[1] = gp_Vec((at(h, h) - at(h, -h) - at(-h, h) + at(-h, -h)) / (4.0 * h * h));
        output[2] = gp_Vec((at(0.0, h) - centre * 2.0 + at(0.0, -h)) / (h * h));
    }

    void match_vertex(int i) {
        const int n = sides();
        const int previous = (i + n - 1) % n;
        gp_Vec mine[3];
        gp_Vec theirs[3];
        vertex_hessian(i, i, mine);
        vertex_hessian(previous, i, theirs);
        gp_Pnt point;
        gp_Vec du;
        gp_Vec dv;
        round(i).blend.surface->D1(blend_u(i, 0.0), spine(i), point, du, dv);
        const gp_Vec normal = du.Crossed(dv).Normalized();
        auto tangential = [&](const gp_Vec& v) { return v - normal * v.Dot(normal); };
        const double sin2 = sin_angle_ * sin_angle_;
        /* xx runs along side i: fixed for ribbon i, free (second-order term)
           for ribbon i-1. yy is the mirror image. */
        second_end_[static_cast<std::size_t>(previous)] +=
            tangential(mine[0] - theirs[0]).XYZ() / sin2;
        second_start_[static_cast<std::size_t>(i)] +=
            tangential(theirs[2] - mine[2]).XYZ() / sin2;
        /* Split the twist difference between both ribbons. Ribbon i's twist
           enters as +sin(alpha) W', ribbon i-1's as -sin(alpha) W'. The
           correction shrinks to rounding noise as the passes converge, so
           it skips the tangent-plane check. */
        const gp_Vec half = tangential(theirs[1] - mine[1]) * (0.5 / sin_angle_);
        twist_start_[static_cast<std::size_t>(i)] += direction(i, 0.0, half, false);
        twist_end_[static_cast<std::size_t>(previous)] += direction(previous, 1.0, half, false);
    }

    const std::vector<Round>& rounds_;
    std::vector<CornerSide> sides_;
    std::vector<gp_Pnt2d> vertices_;
    std::vector<gp_XY> direction_start_;
    std::vector<gp_XY> direction_end_;
    std::vector<gp_XY> twist_start_;
    std::vector<gp_XY> twist_end_;
    std::vector<gp_XYZ> second_start_;
    std::vector<gp_XYZ> second_end_;
    double sin_angle_ {1.0};
    int degree_ {0};
    double bubble_scale_ {1.0};
    std::vector<gp_XYZ> coefficients_;
};

/* Clamped B-spline space of degree 5 on [0, 1]. */
class Basis {
public:
    explicit Basis(int spans) : flat_(1, spans + 1 + 2 * kDegree) {
        for (int k = 0; k <= spans; ++k) {
            breaks_.push_back(static_cast<double>(k) / spans);
        }
        int index = 1;
        for (int k = 0; k <= spans; ++k) {
            const int multiplicity = (k == 0 || k == spans) ? kDegree + 1 : 1;
            for (int m = 0; m < multiplicity; ++m) {
                flat_.SetValue(index++, breaks_[static_cast<std::size_t>(k)]);
            }
        }
    }

    static constexpr int kDegree = 5;

    int spans() const { return static_cast<int>(breaks_.size()) - 1; }
    int count() const { return spans() + kDegree; }

    /* `per_span` evenly spaced samples inside every knot span, plus t = 1. */
    std::vector<double> samples(int per_span) const {
        std::vector<double> output;
        for (int k = 0; k < spans(); ++k) {
            for (int m = 0; m < per_span; ++m) {
                output.push_back(breaks_[static_cast<std::size_t>(k)]
                    + (breaks_[static_cast<std::size_t>(k) + 1] - breaks_[static_cast<std::size_t>(k)])
                        * m / per_span);
            }
        }
        output.push_back(1.0);
        return output;
    }

    /* Values (order 0) or derivatives of every basis function at t. */
    std::vector<double> eval(double t, int order) const {
        math_Matrix matrix(1, order + 1, 1, kDegree + 1);
        int first = 0;
        BSplCLib::EvalBsplineBasis(order, kDegree + 1, flat_, t, first, matrix);
        std::vector<double> output(static_cast<std::size_t>(count()), 0.0);
        for (int k = 1; k <= kDegree + 1; ++k) {
            const int index = first + k - 2;
            if (index >= 0 && index < count()) {
                output[static_cast<std::size_t>(index)] = matrix(order + 1, k);
            }
        }
        return output;
    }

    void knots(TColStd_Array1OfReal& values, TColStd_Array1OfInteger& multiplicities) const {
        for (int k = 0; k <= spans(); ++k) {
            values.SetValue(k + 1, breaks_[static_cast<std::size_t>(k)]);
            multiplicities.SetValue(k + 1, (k == 0 || k == spans()) ? kDegree + 1 : 1);
        }
    }

private:
    std::vector<double> breaks_;
    TColStd_Array1OfReal flat_;
};

/* Solve the dense symmetric positive definite system A x = b (Cholesky). */
std::vector<double> solve_scalar(std::vector<double> a, std::vector<double> b) {
    const std::size_t n = b.size();
    for (std::size_t j = 0; j < n; ++j) {
        double diagonal = a[j * n + j];
        for (std::size_t k = 0; k < j; ++k) diagonal -= a[j * n + k] * a[j * n + k];
        if (!(diagonal > 0.0)) {
            throw std::runtime_error("smooth fillet corner fit is singular");
        }
        diagonal = std::sqrt(diagonal);
        a[j * n + j] = diagonal;
        for (std::size_t i = j + 1; i < n; ++i) {
            double value = a[i * n + j];
            const double* ri = &a[i * n];
            const double* rj = &a[j * n];
            for (std::size_t k = 0; k < j; ++k) value -= ri[k] * rj[k];
            a[i * n + j] = value / diagonal;
        }
    }
    for (std::size_t i = 0; i < n; ++i) {
        double value = b[i];
        for (std::size_t k = 0; k < i; ++k) value -= a[i * n + k] * b[k];
        b[i] = value / a[i * n + i];
    }
    for (std::size_t i = n; i-- > 0;) {
        double value = b[i];
        for (std::size_t k = i + 1; k < n; ++k) value -= a[k * n + i] * b[k];
        b[i] = value / a[i * n + i];
    }
    return b;
}

/* Least-squares control points of a curve in `basis` through f(t). */
template <typename Function>
std::vector<gp_XYZ> fit_curve(const Basis& basis, const Function& f) {
    const std::size_t n = static_cast<std::size_t>(basis.count());
    std::vector<double> normal(n * n, 0.0);
    std::vector<gp_XYZ> rhs(n, gp_XYZ(0.0, 0.0, 0.0));
    for (double t : basis.samples(8)) {
        const std::vector<double> row = basis.eval(t, 0);
        const gp_XYZ value = f(t);
        for (std::size_t i = 0; i < n; ++i) {
            if (row[i] == 0.0) continue;
            rhs[i] += value * row[i];
            for (std::size_t j = 0; j < n; ++j) normal[i * n + j] += row[i] * row[j];
        }
    }
    return solve(std::move(normal), std::move(rhs));
}

/* Quad i of the patch (vertex i, midpoint of side i, centre, midpoint of
   side i-1) as a degree-5 B-spline. On each of its four sides the first
   three control rows reproduce the position and first two cross derivatives
   of the boundary data: the round's ribbon on the outer sides (G2 to the
   round by construction) and the smooth patch function on the inner sides
   (G2 to the neighbouring quads). The remaining poles fit the patch. */
Handle(Geom_BSplineSurface) corner_quad(const CornerPatch& patch, int i) {
    const int n = patch.sides();
    const gp_XY corner = patch.vertex(i).XY();
    const gp_XY mid_next = (corner + patch.vertex(i + 1).XY()) * 0.5;
    const gp_XY mid_previous = (corner + patch.vertex(i + n - 1).XY()) * 0.5;
    const gp_XY centre(0.0, 0.0);
    auto domain = [&](double a, double b) {
        return gp_Pnt2d(corner * ((1 - a) * (1 - b)) + mid_next * (a * (1 - b))
            + centre * (a * b) + mid_previous * ((1 - a) * b));
    };
    /* One function supplies every side's data, so the corner blocks of
       control points, constrained from two sides, see consistent jets. */
    auto inner = [&patch, &domain](double a, double b) {
        return patch.value(domain(a, b)).XYZ();
    };

    const Basis basis(12);
    const int count = basis.count();
    std::vector<gp_XYZ> sum(static_cast<std::size_t>(count * count), gp_XYZ(0.0, 0.0, 0.0));
    std::vector<int> hits(static_cast<std::size_t>(count * count), 0);
    auto pole = [&](int a, int b) -> std::size_t { return static_cast<std::size_t>(a * count + b); };
    constexpr double h = 2.0e-4;

    /* Boundary rows: the first three pole rows along each side carry the
       side's position and first two cross derivatives. Corner blocks are
       shared by two sides whose data agree only up to second order at a
       polygon vertex (the interpolant is C2, not C3, there), and row-2 poles
       act on curvature with a factor of about (5 spans)^2, so averaging the
       two sides' poles breaks G2 near the vertex. All boundary rows are
       solved jointly instead: positions in full; on the outer sides the
       cross derivatives only through what decides G1 and G2,
         n . F_c = 0   and   n . F_cc = II(F_c, F_c),
       the latter linearized around the current F_c. Their tangential parts
       only change the parametrization; a light proximal pull towards the
       previous pass keeps the system regular while they move as needed. */
    std::vector<int> unknown(static_cast<std::size_t>(count * count), -1);
    int unknowns = 0;
    for (int ka = 0; ka < count; ++ka) {
        for (int kb = 0; kb < count; ++kb) {
            if (ka < 3 || kb < 3 || ka >= count - 3 || kb >= count - 3) {
                unknown[pole(ka, kb)] = unknowns++;
            }
        }
    }
    const std::size_t size = static_cast<std::size_t>(3 * unknowns);
    const std::vector<double> end_derivatives[2][3] {
        {basis.eval(0.0, 0), basis.eval(0.0, 1), basis.eval(0.0, 2)},
        {basis.eval(1.0, 0), basis.eval(1.0, 1), basis.eval(1.0, 2)},
    };
    struct Sample {
        bool outer {false};
        double t {0.0};
        gp_XYZ data[3];
        gp_Vec frame[3];
        /* Second fundamental form in the basis (T, D1). */
        double ii_tt {0.0};
        double ii_td {0.0};
        double ii_dd {0.0};
        gp_Vec alpha_row;  // alpha(X) = alpha_row . X for X = alpha T + beta D1
        gp_Vec beta_row;
        /* (variable, coefficient) of F, F_c, F_cc. */
        std::vector<std::pair<int, double>> terms[3];
    };
    std::vector<Sample> samples;
    /* side: 0 -> b = 0, 1 -> b = 1, 2 -> a = 0, 3 -> a = 1. */
    for (int side = 0; side < 4; ++side) {
        const bool along_a = side < 2;
        const int end = (side == 1 || side == 3) ? 1 : 0;
        const double fixed = end;
        auto at = [&](double t, double c) { return along_a ? inner(t, c) : inner(c, t); };
        for (double t : basis.samples(8)) {
            Sample sample;
            sample.outer = side == 0 || side == 2;
            sample.t = t;
            const gp_XYZ f0 = at(t, fixed);
            sample.data[0] = f0;
            if (sample.outer) {
                /* One-sided differences into the domain. */
                auto cross_data = [&](double u, gp_XYZ& first, gp_XYZ& second) {
                    const gp_XYZ p0 = at(u, 0.0);
                    const gp_XYZ p1 = at(u, h);
                    const gp_XYZ p2 = at(u, 2.0 * h);
                    const gp_XYZ p3 = at(u, 3.0 * h);
                    first = (p0 * -3.0 + p1 * 4.0 - p2) / (2.0 * h);
                    second = (p0 * 2.0 - p1 * 5.0 + p2 * 4.0 - p3) / (h * h);
                };
                cross_data(t, sample.data[1], sample.data[2]);
                const double dt = t < 0.5 ? 1.0e-4 : -1.0e-4;
                const gp_XYZ ahead = at(t + dt, 0.0);
                const gp_XYZ behind = at(t - dt, 0.0);
                const bool central = t - dt >= 0.0 && t - dt <= 1.0;
                gp_Vec along;
                double ii_tt_value = 0.0;
                gp_XYZ cross_ahead;
                gp_XYZ unused;
                cross_data(t + dt, cross_ahead, unused);
                const gp_Vec cross(sample.data[1]);
                if (central) {
                    along = gp_Vec((ahead - behind) / (2.0 * dt));
                } else {
                    along = gp_Vec((ahead - f0) / dt);
                }
                const gp_Vec normal = along.Crossed(cross).Normalized();
                if (central) {
                    ii_tt_value = normal.Dot(gp_Vec((ahead - f0 * 2.0 + behind) / (dt * dt)));
                } else {
                    const gp_XYZ ahead2 = at(t + 2.0 * dt, 0.0);
                    ii_tt_value = normal.Dot(gp_Vec((f0 - ahead * 2.0 + ahead2) / (dt * dt)));
                }
                sample.frame[0] = normal;
                sample.frame[1] = along.Normalized();
                sample.frame[2] = normal.Crossed(sample.frame[1]);
                sample.ii_tt = ii_tt_value;
                sample.ii_td = normal.Dot((gp_Vec(cross_ahead) - cross) / dt);
                sample.ii_dd = normal.Dot(gp_Vec(sample.data[2]));
                const double e = along.Dot(along);
                const double f = along.Dot(cross);
                const double g = cross.Dot(cross);
                const double determinant = e * g - f * f;
                sample.alpha_row = (along * g - cross * f) / determinant;
                sample.beta_row = (cross * e - along * f) / determinant;
            } else {
                const double sign = end ? -1.0 : 1.0;
                const gp_XYZ fh = at(t, fixed + sign * h);
                const gp_XYZ fm = at(t, fixed - sign * h);
                sample.data[1] = (fh - fm) / (2.0 * h) * sign;
                sample.data[2] = (fh - f0 * 2.0 + fm) / (h * h);
                sample.frame[0] = gp_Vec(1, 0, 0);
                sample.frame[1] = gp_Vec(0, 1, 0);
                sample.frame[2] = gp_Vec(0, 0, 1);
            }
            const std::vector<double> along_values = basis.eval(t, 0);
            for (int order = 0; order < 3; ++order) {
                const std::vector<double>& across = end_derivatives[end][order];
                for (int k = 0; k < count; ++k) {
                    if (along_values[static_cast<std::size_t>(k)] == 0.0) continue;
                    for (int r = 0; r < count; ++r) {
                        const double coefficient =
                            along_values[static_cast<std::size_t>(k)] * across[static_cast<std::size_t>(r)];
                        if (coefficient == 0.0) continue;
                        const int variable = unknown[along_a ? pole(k, r) : pole(r, k)];
                        if (variable < 0) {
                            throw std::runtime_error("corner fit boundary pole outside the boundary rows");
                        }
                        sample.terms[order].emplace_back(variable, coefficient);
                    }
                }
            }
            samples.push_back(std::move(sample));
        }
    }

    const double scale1 = 1.0 / count;
    const double scale2 = scale1 * scale1;
    constexpr double proximal = 3.0e-5;
    constexpr double firm = 1.0e-3;
    constexpr double vertex_zone = 0.25;
    std::vector<double> boundary;
    auto current = [&](const Sample& sample, int order) {
        if (boundary.empty()) return sample.data[order];
        gp_XYZ value(0.0, 0.0, 0.0);
        for (const auto& [variable, coefficient] : sample.terms[order]) {
            const std::size_t v = static_cast<std::size_t>(3 * variable);
            value += gp_XYZ(boundary[v], boundary[v + 1], boundary[v + 2]) * coefficient;
        }
        return value;
    };
    for (int pass = 0; pass < 3; ++pass) {
        std::vector<double> normal_matrix(size * size, 0.0);
        std::vector<double> boundary_rhs(size, 0.0);
        std::vector<std::pair<std::size_t, double>> row;
        auto add_row = [&](double value) {
            for (const auto& [r, wr] : row) {
                boundary_rhs[r] += wr * value;
                double* line = &normal_matrix[r * size];
                for (const auto& [c, wc] : row) line[c] += wr * wc;
            }
        };
        /* Row  weight * (sum_terms e . P  [- g . F_c]) = weight * target. */
        auto emit = [&](const Sample& sample, int order, const gp_Vec& direction,
                        const gp_Vec* curvature, double weight, double target) {
            row.clear();
            for (const auto& [variable, coefficient] : sample.terms[order]) {
                for (int c = 0; c < 3; ++c) {
                    const double value = direction.Coord(c + 1) * coefficient;
                    if (value != 0.0) {
                        row.emplace_back(static_cast<std::size_t>(3 * variable + c), weight * value);
                    }
                }
            }
            if (curvature) {
                for (const auto& [variable, coefficient] : sample.terms[1]) {
                    for (int c = 0; c < 3; ++c) {
                        const double value = -curvature->Coord(c + 1) * coefficient;
                        if (value != 0.0) {
                            row.emplace_back(static_cast<std::size_t>(3 * variable + c), weight * value);
                        }
                    }
                }
            }
            add_row(weight * target);
        };
        for (const Sample& sample : samples) {
            for (int axis = 0; axis < 3; ++axis) {
                emit(sample, 0, sample.frame[axis], nullptr, 1.0,
                     gp_Vec(sample.data[0]).Dot(sample.frame[axis]));
            }
            if (!sample.outer) {
                for (int order = 1; order < 3; ++order) {
                    const double weight = order == 1 ? scale1 : scale2;
                    for (int axis = 0; axis < 3; ++axis) {
                        emit(sample, order, sample.frame[axis], nullptr, weight,
                             gp_Vec(sample.data[order]).Dot(sample.frame[axis]));
                    }
                }
                continue;
            }
            const gp_Vec& normal = sample.frame[0];
            /* G1. */
            emit(sample, 1, normal, nullptr, scale1, 0.0);
            /* G2 around X0 = current F_c: II(X0, Y) = curvature . Y. */
            const gp_Vec x0(current(sample, 1));
            const double a0 = sample.alpha_row.Dot(x0);
            const double b0 = sample.beta_row.Dot(x0);
            const double ii_x_t = a0 * sample.ii_tt + b0 * sample.ii_td;
            const double ii_x_d = a0 * sample.ii_td + b0 * sample.ii_dd;
            const gp_Vec curvature = (sample.alpha_row * ii_x_t + sample.beta_row * ii_x_d) * 2.0;
            const double ii_x_x = a0 * ii_x_t + b0 * ii_x_d;
            emit(sample, 2, normal, &curvature, scale2, -ii_x_x);
            /* Proximal pull on the tangential parts: weak at the polygon
               vertex (t = 0), where the conflict is, firm away from it so
               the rows cannot wander along the side. */
            const double ramp = std::min(1.0, sample.t / vertex_zone);
            const double pull = proximal + (firm - proximal) * ramp * ramp;
            for (int order = 1; order < 3; ++order) {
                const double weight = pull * (order == 1 ? scale1 : scale2);
                const gp_XYZ previous = current(sample, order);
                for (int axis = 1; axis < 3; ++axis) {
                    emit(sample, order, sample.frame[axis], nullptr, weight,
                         gp_Vec(previous).Dot(sample.frame[axis]));
                }
            }
        }
        boundary = solve_scalar(std::move(normal_matrix), std::move(boundary_rhs));
    }
    for (std::size_t index = 0; index < unknown.size(); ++index) {
        if (unknown[index] >= 0) {
            const std::size_t v = static_cast<std::size_t>(3 * unknown[index]);
            sum[index] = gp_XYZ(boundary[v], boundary[v + 1], boundary[v + 2]);
            hits[index] = 1;
        }
    }

    /* Least squares for the free poles against the patch function. */
    std::vector<int> free_index(static_cast<std::size_t>(count * count), -1);
    int free_count = 0;
    for (std::size_t k = 0; k < hits.size(); ++k) {
        if (hits[k] == 0) {
            free_index[k] = free_count++;
        } else {
            sum[k] /= hits[k];
        }
    }
    const std::size_t m = static_cast<std::size_t>(free_count);
    std::vector<double> normal(m * m, 0.0);
    std::vector<gp_XYZ> rhs(m, gp_XYZ(0.0, 0.0, 0.0));
    const std::vector<double> grid = basis.samples(4);
    for (double a : grid) {
        const std::vector<double> na = basis.eval(a, 0);
        for (double b : grid) {
            const std::vector<double> nb = basis.eval(b, 0);
            gp_XYZ residual = inner(a, b);
            std::vector<std::pair<int, double>> row;
            for (int ka = 0; ka < count; ++ka) {
                if (na[static_cast<std::size_t>(ka)] == 0.0) continue;
                for (int kb = 0; kb < count; ++kb) {
                    const double weight = na[static_cast<std::size_t>(ka)] * nb[static_cast<std::size_t>(kb)];
                    if (weight == 0.0) continue;
                    const std::size_t index = pole(ka, kb);
                    if (free_index[index] < 0) {
                        residual -= sum[index] * weight;
                    } else {
                        row.emplace_back(free_index[index], weight);
                    }
                }
            }
            for (const auto& [r, wr] : row) {
                rhs[static_cast<std::size_t>(r)] += residual * wr;
                for (const auto& [c, wc] : row) {
                    normal[static_cast<std::size_t>(r) * m + static_cast<std::size_t>(c)] += wr * wc;
                }
            }
        }
    }
    /* Control-net fairness: the boundary rows carry a parametrization the
       G2 solve chose freely, so matching the patch function at fixed
       parameters alone would ripple the interior. Penalize second
       differences of the net (both directions and the twist). */
    const double fairness_weight = static_cast<double>(grid.size() * grid.size()) / static_cast<double>(count * count);
    auto add_stencil = [&](const std::vector<std::pair<std::size_t, double>>& stencil) {
        gp_XYZ residual(0.0, 0.0, 0.0);
        std::vector<std::pair<int, double>> row;
        for (const auto& [index, coefficient] : stencil) {
            if (free_index[index] < 0) {
                residual -= sum[index] * coefficient;
            } else {
                row.emplace_back(free_index[index], coefficient);
            }
        }
        for (const auto& [r, wr] : row) {
            rhs[static_cast<std::size_t>(r)] += residual * (wr * fairness_weight);
            for (const auto& [c, wc] : row) {
                normal[static_cast<std::size_t>(r) * m + static_cast<std::size_t>(c)] += wr * wc * fairness_weight;
            }
        }
    };
    for (int ka = 0; ka < count; ++ka) {
        for (int kb = 0; kb < count; ++kb) {
            if (ka + 2 < count) add_stencil({{pole(ka, kb), 1.0}, {pole(ka + 1, kb), -2.0}, {pole(ka + 2, kb), 1.0}});
            if (kb + 2 < count) add_stencil({{pole(ka, kb), 1.0}, {pole(ka, kb + 1), -2.0}, {pole(ka, kb + 2), 1.0}});
            if (ka + 1 < count && kb + 1 < count) {
                add_stencil({{pole(ka, kb), 1.0}, {pole(ka + 1, kb), -1.0}, {pole(ka, kb + 1), -1.0},
                             {pole(ka + 1, kb + 1), 1.0}});
            }
        }
    }
    const std::vector<gp_XYZ> solution = solve(std::move(normal), std::move(rhs));
    TColgp_Array2OfPnt poles(1, count, 1, count);
    for (int ka = 0; ka < count; ++ka) {
        for (int kb = 0; kb < count; ++kb) {
            const std::size_t index = pole(ka, kb);
            const gp_XYZ value = free_index[index] < 0
                ? sum[index] : solution[static_cast<std::size_t>(free_index[index])];
            poles.SetValue(ka + 1, kb + 1, gp_Pnt(value));
        }
    }
    TColStd_Array1OfReal knots(1, basis.spans() + 1);
    TColStd_Array1OfInteger multiplicities(1, basis.spans() + 1);
    basis.knots(knots, multiplicities);
    return new Geom_BSplineSurface(
        poles, knots, knots, multiplicities, multiplicities, Basis::kDegree, Basis::kDegree);
}

/* ---------------------------------------------------------------------------
   Face of a rebuilt round: the blend trimmed by its springs and end curves,
   all given as pcurves in the blend's (u, v).
   ------------------------------------------------------------------------- */

TopoDS_Edge uv_edge(
    const Handle(Geom2d_Curve)& curve, const Handle(Geom_Surface)& surface,
    const TopoDS_Vertex& start, const TopoDS_Vertex& end, double first, double last) {
    BRepBuilderAPI_MakeEdge builder(curve, surface, start, end, first, last);
    if (!builder.IsDone()) {
        throw std::runtime_error("smooth fillet could not build a blend boundary edge");
    }
    TopoDS_Edge edge = builder.Edge();
    BRepLib::BuildCurves3d(edge, 1.0e-8);
    return edge;
}

TopoDS_Edge uv_segment(
    const Handle(Geom_Surface)& surface, const gp_Pnt2d& a, const gp_Pnt2d& b,
    const TopoDS_Vertex& start, const TopoDS_Vertex& end) {
    const double length = a.Distance(b);
    Handle(Geom2d_Line) line = new Geom2d_Line(a, gp_Dir2d(b.X() - a.X(), b.Y() - a.Y()));
    return uv_edge(line, surface, start, end, 0.0, length);
}

TopoDS_Edge uv_polyline_edge(
    const Handle(Geom_Surface)& surface, const std::vector<gp_Pnt2d>& points,
    const TopoDS_Vertex& start, const TopoDS_Vertex& end) {
    Handle(TColgp_HArray1OfPnt2d) array =
        new TColgp_HArray1OfPnt2d(1, static_cast<int>(points.size()));
    Handle(TColStd_HArray1OfReal) parameters =
        new TColStd_HArray1OfReal(1, static_cast<int>(points.size()));
    for (std::size_t k = 0; k < points.size(); ++k) {
        array->SetValue(static_cast<int>(k) + 1, points[k]);
        parameters->SetValue(
            static_cast<int>(k) + 1, static_cast<double>(k) / static_cast<double>(points.size() - 1));
    }
    Geom2dAPI_Interpolate interpolate(array, parameters, false, 1.0e-12);
    interpolate.Perform();
    if (!interpolate.IsDone()) {
        throw std::runtime_error("smooth fillet could not interpolate a miter");
    }
    return uv_edge(interpolate.Curve(), surface, start, end, 0.0, 1.0);
}

TopoDS_Vertex make_vertex(const gp_Pnt& point) {
    TopoDS_Vertex vertex;
    BRep_Builder().MakeVertex(vertex, point, 1.0e-7);
    return vertex;
}

/* Loop (0, bottom) -> (1, bottom) -> (1, top) -> (0, top), counter-clockwise in
   (u, v). Ends shared with corner patches are split at u = 0.5 to match the
   patch's quads. */
TopoDS_Face round_face(const Round& round) {
    const Handle(Geom_Surface) surface(round.blend.surface.get());
    gp_Pnt2d corners[4];
    for (int end = 0; end < 2; ++end) {
        gp_Pnt2d at_a;
        gp_Pnt2d at_b;
        if (round.ends[end].kind == EndKind::Miter) {
            const auto& miter = round.miter[end];
            at_a = end == 0 ? miter.front() : miter.back();
            at_b = end == 0 ? miter.back() : miter.front();
        } else {
            at_a = gp_Pnt2d(0.0, end_spine(round, end));
            at_b = gp_Pnt2d(1.0, end_spine(round, end));
        }
        corners[end == 0 ? 0 : 3] = at_a;
        corners[end == 0 ? 1 : 2] = at_b;
    }
    TopoDS_Vertex vertices[4];
    for (int k = 0; k < 4; ++k) {
        vertices[k] = make_vertex(surface->Value(corners[k].X(), corners[k].Y()));
    }
    BRepBuilderAPI_MakeWire wire;
    auto add_end = [&](int end, int from, int to) {
        const RoundEnd& info = round.ends[end];
        if (info.kind == EndKind::Miter) {
            wire.Add(uv_polyline_edge(surface, round.miter[end], vertices[from], vertices[to]));
        } else if (info.kind == EndKind::Corner) {
            const gp_Pnt2d middle(0.5, end_spine(round, end));
            const TopoDS_Vertex split = make_vertex(surface->Value(middle.X(), middle.Y()));
            wire.Add(uv_segment(surface, corners[from], middle, vertices[from], split));
            wire.Add(uv_segment(surface, middle, corners[to], split, vertices[to]));
        } else {
            wire.Add(uv_segment(surface, corners[from], corners[to], vertices[from], vertices[to]));
        }
    };
    add_end(0, 0, 1);
    wire.Add(uv_segment(surface, corners[1], corners[2], vertices[1], vertices[2]));
    add_end(1, 2, 3);
    wire.Add(uv_segment(surface, corners[3], corners[0], vertices[3], vertices[0]));
    if (!wire.IsDone()) {
        throw std::runtime_error("smooth fillet could not close a blend boundary");
    }
    BRepBuilderAPI_MakeFace face(surface, wire.Wire(), true);
    if (!face.IsDone()) {
        throw std::runtime_error("OCCT could not make the smooth fillet face");
    }
    return face.Face();
}

/* Rounds whose spine is closed (a seam edge, e.g. a cylinder rim) keep the
   arc-length coupled blend between their two closed trim lines. */
TopoDS_Face closed_round_face(
    const std::vector<std::pair<TopoDS_Edge, TopoDS_Face>>& springs,
    int continuity, double tension, double tolerance) {
    const BlendOptions options {tolerance, 0, -1};
    const BlendGeometry blend = blend_geometry(
        springs[0].second, springs[0].first, continuity, tension,
        springs[1].second, springs[1].first, continuity, tension, options);
    BRepBuilderAPI_MakeFace blend_face(blend.surface, std::max(tolerance, 1.0e-7));
    if (!blend_face.IsDone()) {
        throw std::runtime_error("OCCT could not make the smooth fillet face");
    }
    return blend_face.Face();
}

int find_root(std::vector<int>& parent, int i) {
    while (parent[static_cast<std::size_t>(i)] != i) {
        parent[static_cast<std::size_t>(i)] =
            parent[static_cast<std::size_t>(parent[static_cast<std::size_t>(i)])];
        i = parent[static_cast<std::size_t>(i)];
    }
    return i;
}

#endif

}  // namespace

core::ShapeId smooth_fillet(
    core::Session& session,
    core::ShapeId id,
    double setback,
    const std::size_t* edge_indices,
    std::size_t edge_count,
    int continuity,
    double tension,
    double tolerance) {
    if (!(std::isfinite(setback) && setback > 0.0)) {
        throw std::invalid_argument("smooth fillet setback must be finite and positive");
    }
    if (continuity != 1 && continuity != 2) {
        throw std::invalid_argument("smooth fillet continuity must be 1 (G1) or 2 (G2)");
    }
    if (!(std::isfinite(tension) && tension >= 0.0)) {
        throw std::invalid_argument("smooth fillet tension must be positive, or 0 for automatic");
    }
    if (!(std::isfinite(tolerance) && tolerance > 0.0)) {
        throw std::invalid_argument("smooth fillet tolerance must be positive");
    }
    if (!edge_indices && edge_count != 0) {
        throw std::invalid_argument("smooth fillet edge index array is null");
    }
#ifdef CADFLOW_WITH_OCCT
    const core::Shape& source = core::get_shape(session, id);
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(source.native, TopAbs_EDGE, edges);
    std::vector<std::size_t> selected(edge_indices, edge_indices + edge_count);
    if (selected.empty()) {
        for (int index = 0; index < edges.Extent(); ++index) {
            selected.push_back(static_cast<std::size_t>(index));
        }
    }
    std::vector<bool> seen(static_cast<std::size_t>(edges.Extent()), false);
    for (std::size_t index : selected) {
        if (index >= seen.size()) throw std::out_of_range("subshape index is out of range");
        if (seen[index]) throw std::invalid_argument("subshape indices must be unique");
        seen[index] = true;
    }

    /* 1. Circular fillet: its trim lines, sections, and topology are kept. */
    BRepFilletAPI_MakeFillet circular(source.native);
    for (std::size_t index : selected) {
        circular.Add(setback, TopoDS::Edge(edges(static_cast<int>(index + 1))));
    }
    circular.Build();
    if (!circular.IsDone()) {
        throw std::runtime_error("OCCT could not place the fillet trim lines for this setback");
    }
    const TopoDS_Shape rounded = circular.Shape();
    TopTools_IndexedMapOfShape created;
    for (int surface = 1; surface <= circular.NbSurfaces(); ++surface) {
        for (TopTools_ListOfShape::Iterator it(circular.NewFaces(surface)); it.More(); it.Next()) {
            created.Add(it.Value());
        }
    }
    if (created.IsEmpty()) {
        throw std::runtime_error("OCCT fillet produced no round faces");
    }
    TopTools_IndexedDataMapOfShapeListOfShape ancestors;
    TopExp::MapShapesAndAncestors(rounded, TopAbs_EDGE, TopAbs_FACE, ancestors);

    /* 2. Sort the created faces into rounds (two trim lines on kept faces),
       closed rounds (with a seam), and corner patches (no trim lines). */
    std::vector<Round> rounds;
    std::vector<TopoDS_Face> corner_faces;
    std::vector<TopoDS_Face> closed_faces;
    std::vector<std::vector<std::pair<TopoDS_Edge, TopoDS_Face>>> closed_springs;
    std::vector<std::vector<std::pair<TopoDS_Edge, TopoDS_Face>>> closed_ends;
    TopTools_IndexedMapOfShape round_map;
    TopTools_IndexedMapOfShape corner_map;
    for (int index = 1; index <= created.Extent(); ++index) {
        const TopoDS_Face face = oriented_face(rounded, created(index));
        std::vector<std::pair<TopoDS_Edge, TopoDS_Face>> springs;
        std::vector<std::pair<TopoDS_Edge, TopoDS_Face>> others;
        bool closed = false;
        TopTools_IndexedMapOfShape face_edges;
        TopExp::MapShapes(face, TopAbs_EDGE, face_edges);
        for (int e = 1; e <= face_edges.Extent(); ++e) {
            const TopoDS_Edge edge = TopoDS::Edge(face_edges(e));
            if (BRep_Tool::Degenerated(edge)) continue;  // poles have no neighbour
            if (BRep_Tool::IsClosed(edge, face)) {
                closed = true;
                continue;
            }
            const TopoDS_Face neighbour = other_face(ancestors, edge, face);
            if (!created.Contains(neighbour) && tangent_along(face, neighbour, edge)) {
                springs.emplace_back(edge, neighbour);
            } else {
                others.emplace_back(edge, neighbour);
            }
        }
        if (springs.empty()) {
            corner_map.Add(face);
            corner_faces.push_back(face);
        } else if (springs.size() != 2) {
            throw std::runtime_error(
                "smooth fillet could not identify the two trim lines of a round face");
        } else if (closed) {
            for (const auto& [edge, neighbour] : others) {
                if (created.Contains(neighbour)) {
                    throw std::runtime_error(
                        "smooth fillet does not support closed rounds that meet other rounds");
                }
            }
            closed_faces.push_back(face);
            closed_springs.push_back(springs);
            closed_ends.push_back(others);
        } else {
            round_map.Add(face);
            rounds.push_back(make_round(face, springs));
        }
    }

    /* 3. Classify both ends of every round. */
    for (std::size_t r = 0; r < rounds.size(); ++r) {
        Round& round = rounds[r];
        bool found[2] {false, false};
        TopTools_IndexedMapOfShape face_edges;
        TopExp::MapShapes(round.face, TopAbs_EDGE, face_edges);
        for (int e = 1; e <= face_edges.Extent(); ++e) {
            const TopoDS_Edge edge = TopoDS::Edge(face_edges(e));
            if (BRep_Tool::Degenerated(edge) || edge.IsSame(round.spring[0].edge)
                || edge.IsSame(round.spring[1].edge)) {
                continue;
            }
            const int end = end_of(round, edge);
            if (end < 0 || found[end]) {
                throw std::runtime_error(
                    "smooth fillet supports rounds closed by one edge at each end; this round "
                    "ends on several faces");
            }
            found[end] = true;
            RoundEnd& info = round.ends[end];
            info.edge = edge;
            info.neighbour = other_face(ancestors, edge, round.face);
            const bool tangent = tangent_along(round.face, info.neighbour, edge);
            if (round_map.Contains(info.neighbour)) {
                info.kind = tangent ? EndKind::Junction : EndKind::Miter;
                info.other = round_map.FindIndex(info.neighbour) - 1;
            } else if (corner_map.Contains(info.neighbour)) {
                if (!tangent) {
                    throw std::runtime_error("smooth fillet corner patch meets a round at an angle");
                }
                info.kind = EndKind::Corner;
                info.other = corner_map.FindIndex(info.neighbour) - 1;
            } else if (created.Contains(info.neighbour)) {
                throw std::runtime_error("smooth fillet met a closed round at a round end");
            } else {
                if (tangent) {
                    throw std::runtime_error(
                        "smooth fillet rounds that end tangent to an unrounded face are not "
                        "supported");
                }
                info.kind = EndKind::Cap;
            }
            if (info.kind != EndKind::Miter && !iso_end(round, end)) {
                throw std::runtime_error(
                    "smooth fillet does not yet support this corner: a round ends on a "
                    "boundary that is not one of its cross sections (typical of tapered "
                    "corners)");
            }
        }
        if (!found[0] || !found[1]) {
            throw std::runtime_error("smooth fillet could not find both ends of a round");
        }
        for (int end = 0; end < 2; ++end) {
            if (round.ends[end].kind == EndKind::Miter) {
                round.margin[end] = 0.1 * (round.last - round.first);
            }
        }
    }

    /* 4. Chains of tangent rounds share their junction sections and one tension. */
    std::vector<int> parent(rounds.size());
    std::iota(parent.begin(), parent.end(), 0);
    for (std::size_t r = 0; r < rounds.size(); ++r) {
        for (int end = 0; end < 2; ++end) {
            const RoundEnd& info = rounds[r].ends[end];
            if (info.kind != EndKind::Junction || info.other < static_cast<int>(r)) continue;
            Round& a = rounds[r];
            Round& b = rounds[static_cast<std::size_t>(info.other)];
            const int b_end = b.ends[0].kind == EndKind::Junction && b.ends[0].edge.IsSame(info.edge)
                ? 0 : 1;
            const BlendFrames fa(
                contact_frame(a, 0, end_spine(a, end)), contact_frame(a, 1, end_spine(a, end)));
            const BlendFrames fb(
                contact_frame(b, 0, end_spine(b, b_end)), contact_frame(b, 1, end_spine(b, b_end)));
            const bool same = fa.first.point.Distance(fb.first.point)
                < fa.first.point.Distance(fb.second.point);
            const BlendFrame& b_for_a0 = same ? fb.first : fb.second;
            const BlendFrame& b_for_a1 = same ? fb.second : fb.first;
            if (fa.first.point.Distance(b_for_a0.point) > 1.0e-5
                || fa.second.point.Distance(b_for_a1.point) > 1.0e-5) {
                throw std::runtime_error("tangent rounds do not share their junction section");
            }
            const BlendFrame shared0 = average(fa.first, b_for_a0);
            const BlendFrame shared1 = average(fa.second, b_for_a1);
            a.fixed[end] = true;
            a.end_frames[end] = BlendFrames(shared0, shared1);
            b.fixed[b_end] = true;
            b.end_frames[b_end] = same ? BlendFrames(shared0, shared1) : BlendFrames(shared1, shared0);
            parent[static_cast<std::size_t>(find_root(parent, static_cast<int>(r)))] =
                find_root(parent, info.other);
        }
    }
    std::vector<double> chain_tension(rounds.size(), tension);
    if (tension == 0.0) {
        std::vector<std::vector<BlendFrames>> probes(rounds.size());
        for (std::size_t r = 0; r < rounds.size(); ++r) {
            const Round& round = rounds[r];
            auto& list = probes[static_cast<std::size_t>(find_root(parent, static_cast<int>(r)))];
            for (int k = 0; k < 16; ++k) {
                list.push_back(round_frames(
                    round, round.first + (round.last - round.first) * (k + 0.5) / 16.0));
            }
        }
        for (std::size_t r = 0; r < rounds.size(); ++r) {
            if (!probes[r].empty()) {
                chain_tension[r] = blend_tension(probes[r], continuity, continuity);
            }
        }
        for (std::size_t r = 0; r < rounds.size(); ++r) {
            rounds[r].chain = find_root(parent, static_cast<int>(r));
        }
    }

    /* 5. Blend every round between its contact curves, v = OCCT's spine. */
    const BlendOptions options {tolerance, 0, -1};
    for (Round& round : rounds) {
        const double factor = tension == 0.0
            ? chain_tension[static_cast<std::size_t>(round.chain)] : tension;
        const Round* pointer = &round;
        round.blend = blend_along(
            [pointer](double t) { return round_frames(*pointer, t); },
            round.first - round.margin[0], round.last + round.margin[1],
            continuity, factor, continuity, factor, options);
    }
    for (std::size_t r = 0; r < rounds.size(); ++r) {
        for (int end = 0; end < 2; ++end) {
            const RoundEnd& info = rounds[r].ends[end];
            if (info.kind == EndKind::Miter && info.other > static_cast<int>(r)) {
                compute_miter(rounds, static_cast<int>(r), end);
            }
        }
    }

    /* 6. New faces: rebuilt rounds, corner patches, closed rounds; end faces
       re-bounded by the sections that now end the rounds. */
    BRepTools_ReShape reshape;
    std::vector<TopoDS_Face> faces;
    for (const Round& round : rounds) {
        faces.push_back(round_face(round));
        for (int end = 0; end < 2; ++end) {
            if (round.ends[end].kind == EndKind::Cap) {
                replace_cap_edge(
                    reshape, round.ends[end].neighbour, round.ends[end].edge,
                    round.blend.surface->VIso(end_spine(round, end)), tolerance);
            }
        }
    }
    std::vector<std::vector<CornerSide>> corner_sides;
    for (const TopoDS_Face& corner : corner_faces) {
        std::vector<CornerSide> sides;
        const TopoDS_Wire outer = BRepTools::OuterWire(corner);
        for (BRepTools_WireExplorer explorer(outer, corner); explorer.More(); explorer.Next()) {
            const TopoDS_Edge& edge = explorer.Current();
            if (BRep_Tool::Degenerated(edge)) continue;
            const TopoDS_Face neighbour = other_face(ancestors, edge, corner);
            if (!round_map.Contains(neighbour)) {
                throw std::runtime_error(
                    "smooth fillet corner patches that touch unrounded faces are not supported "
                    "yet; use equal setbacks on the meeting edges");
            }
            CornerSide side;
            side.round = round_map.FindIndex(neighbour) - 1;
            const Round& round = rounds[static_cast<std::size_t>(side.round)];
            side.end = round.ends[0].kind == EndKind::Corner && round.ends[0].edge.IsSame(edge)
                ? 0 : 1;
            const gp_Pnt start = BRep_Tool::Pnt(TopExp::FirstVertex(edge, true));
            const double t = end_spine(round, side.end);
            side.reversed = round.blend.surface->Value(1.0, t).Distance(start)
                < round.blend.surface->Value(0.0, t).Distance(start);
            sides.push_back(side);
        }
        if (sides.size() < 3) {
            throw std::runtime_error("smooth fillet corner patch has fewer than three sides");
        }
        corner_sides.push_back(std::move(sides));
    }
    /* Corner patches are independent and only evaluate B-spline geometry,
       which is reentrant: build and fit them in parallel. */
    std::vector<std::unique_ptr<CornerPatch>> patches(corner_sides.size());
    parallel_for(corner_sides.size(), [&](std::size_t k) {
        patches[k] = std::make_unique<CornerPatch>(rounds, corner_sides[k]);
        patches[k]->fair(6, 60);
    });
    std::vector<std::pair<std::size_t, int>> quads;
    for (std::size_t k = 0; k < patches.size(); ++k) {
        for (int i = 0; i < patches[k]->sides(); ++i) quads.emplace_back(k, i);
    }
    std::vector<Handle(Geom_BSplineSurface)> quad_surfaces(quads.size());
    parallel_for(quads.size(), [&](std::size_t q) {
        quad_surfaces[q] = corner_quad(*patches[quads[q].first], quads[q].second);
    });
    for (const Handle(Geom_BSplineSurface)& surface : quad_surfaces) {
        BRepBuilderAPI_MakeFace face(surface, 1.0e-7);
        if (!face.IsDone()) {
            throw std::runtime_error("OCCT could not make a corner patch face");
        }
        faces.push_back(face.Face());
    }
    for (std::size_t k = 0; k < closed_faces.size(); ++k) {
        faces.push_back(closed_round_face(closed_springs[k], continuity, tension, tolerance));
        const BRepAdaptor_Surface blend_surface(faces.back(), false);
        const Handle(Geom_Surface) geometry = BRep_Tool::Surface(faces.back());
        for (const auto& [edge, cap] : closed_ends[k]) {
            const BRepAdaptor_Curve old_curve(edge);
            const gp_Pnt middle = old_curve.Value(
                0.5 * (old_curve.FirstParameter() + old_curve.LastParameter()));
            const bool at_start = geometry->Value(0.5, 0.0).Distance(middle)
                < geometry->Value(0.5, 1.0).Distance(middle);
            replace_cap_edge(reshape, cap, edge, geometry->VIso(at_start ? 0.0 : 1.0), tolerance);
        }
    }

    /* 7. Sew kept faces, re-bounded end faces, and new faces into one solid. */
    BRepBuilderAPI_Sewing sewing(std::max(10.0 * tolerance, 1.0e-5));
    for (TopExp_Explorer explorer(rounded, TopAbs_FACE); explorer.More(); explorer.Next()) {
        if (!created.Contains(explorer.Current())) {
            sewing.Add(reshape.Apply(explorer.Current()));
        }
    }
    for (const TopoDS_Face& face : faces) {
        sewing.Add(face);
    }
    sewing.Perform();
    const TopoDS_Shape sewn = sewing.SewedShape();
    TopoDS_Shell shell;
    int shells = 0;
    for (TopExp_Explorer explorer(sewn, TopAbs_SHELL); explorer.More(); explorer.Next()) {
        shell = TopoDS::Shell(explorer.Current());
        ++shells;
    }
    if (shells != 1 || sewing.NbFreeEdges() != 0) {
        throw std::runtime_error("smooth fillet faces did not close into one shell");
    }
    BRepBuilderAPI_MakeSolid make_solid(shell);
    if (!make_solid.IsDone()) {
        throw std::runtime_error("smooth fillet could not make a solid");
    }
    TopoDS_Solid solid = make_solid.Solid();
    BRepLib::OrientClosedSolid(solid);
    if (!BRepCheck_Analyzer(solid, true).IsValid()) {
        throw std::runtime_error("smooth fillet produced an invalid solid");
    }
    GProp_GProps properties;
    BRepGProp::VolumeProperties(solid, properties);
    if (!(properties.Mass() > 0.0)) {
        throw std::runtime_error("smooth fillet produced a solid with non-positive volume");
    }
    core::Shape output {core::Shape::Kind::SmoothFillet, setback, 0, 0, id, 0};
    output.native = solid;
    return core::store(session, std::move(output));
#else
    (void)session;
    (void)id;
    throw std::runtime_error("smooth fillet requires the OCCT backend");
#endif
}

}  // namespace cadflow::kernel
