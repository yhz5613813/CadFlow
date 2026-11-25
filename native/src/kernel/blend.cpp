#include "kernel/blend.h"

#include "kernel/differential.h"

#include <algorithm>
#include <cmath>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#ifdef CADFLOW_WITH_OCCT
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Curve2d.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepTools.hxx>
#include <GCPnts_AbscissaPoint.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <Geom_BSplineCurve.hxx>
#include <Geom_BSplineSurface.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColStd_HArray1OfReal.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopAbs.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Vec.hxx>
#endif

namespace cadflow::kernel {
namespace {

void validate_side(const BlendSide& side, const char* name) {
    if (side.continuity < 0 || side.continuity > 2) {
        throw std::invalid_argument(std::string(name) + " continuity must be 0, 1, or 2");
    }
    if (!(side.tension >= 0.0) || !std::isfinite(side.tension)) {
        throw std::invalid_argument(
            std::string(name) + " tension must be positive, or 0 for automatic");
    }
}

#ifdef CADFLOW_WITH_OCCT

using differential::LocalGeometry;

using Frame = BlendFrame;

class Support {
public:
    Support(const TopoDS_Shape& face_shape, const TopoDS_Shape& edge_shape, const char* name)
        : name_(name) {
        if (face_shape.IsNull() || face_shape.ShapeType() != TopAbs_FACE) {
            throw std::invalid_argument(name_ + " support must be one BREP face");
        }
        if (edge_shape.IsNull() || edge_shape.ShapeType() != TopAbs_EDGE) {
            throw std::invalid_argument(name_ + " boundary must be one BREP edge");
        }
        face_ = TopoDS::Face(face_shape);
        bool bounds_face = false;
        for (TopExp_Explorer explorer(face_, TopAbs_EDGE); explorer.More(); explorer.Next()) {
            if (explorer.Current().IsSame(edge_shape)) {
                edge_ = TopoDS::Edge(explorer.Current());
                bounds_face = true;
                break;
            }
        }
        if (!bounds_face) {
            throw std::invalid_argument(name_ + " edge must be a boundary edge of its face");
        }
        surface_.Initialize(face_, false);
        curve_.Initialize(edge_);
        pcurve_.Initialize(edge_, face_);
        reversed_ = face_.Orientation() == TopAbs_REVERSED;
        length_ = GCPnts_AbscissaPoint::Length(curve_);
        if (!(length_ > 1.0e-12)) {
            throw std::invalid_argument(name_ + " edge has zero length");
        }
        orient_outward();
    }

    double length() const { return length_; }

    /* Curve parameter at a fraction of the arc length. */
    double parameter(double fraction) const {
        const double first = curve_.FirstParameter();
        if (fraction <= 0.0) return first;
        if (fraction >= 1.0) return curve_.LastParameter();
        const double guess = first + (curve_.LastParameter() - first) * fraction;
        GCPnts_AbscissaPoint abscissa(curve_, fraction * length_, first, guess);
        if (!abscissa.IsDone()) {
            throw std::runtime_error(name_ + " edge arc-length parameterization failed");
        }
        return abscissa.Parameter();
    }

    Frame frame(double fraction) const { return frame_at(parameter(fraction)); }

    gp_Pnt point(double fraction) const { return curve_.Value(parameter(fraction)); }

private:
    LocalGeometry geometry(double t, gp_Vec& tangent) const {
        gp_Pnt point;
        curve_.D1(t, point, tangent);
        const gp_Pnt2d uv = pcurve_.Value(t);
        const LocalGeometry local =
            differential::evaluate(surface_, reversed_, uv.X(), uv.Y());
        if (!local.regular || tangent.Magnitude() <= 1.0e-300) {
            throw std::runtime_error(
                name_ + " support has an undefined normal along the blend edge");
        }
        return local;
    }

    Frame frame_at(double t) const {
        gp_Vec tangent;
        const LocalGeometry local = geometry(t, tangent);
        gp_Vec out = local.normal.Crossed(tangent) * out_sign_;
        out /= out.Magnitude();
        Frame output;
        /* Use the edge's 3D point: it is what neighbouring topology shares. */
        output.point = curve_.Value(t);
        output.normal = local.normal;
        output.out = out;
        output.curvature = differential::normal_curvature(local, out);
        if (!std::isfinite(output.curvature)) {
            throw std::runtime_error(name_ + " support curvature is undefined");
        }
        return output;
    }

    void orient_outward() {
        const double t = 0.5 * (curve_.FirstParameter() + curve_.LastParameter());
        gp_Vec tangent;
        const LocalGeometry local = geometry(t, tangent);
        const gp_Vec probe = local.normal.Crossed(tangent);
        double a = 0.0;
        double b = 0.0;
        if (!differential::parameter_direction(local, probe, a, b)) {
            throw std::runtime_error(name_ + " support tangent plane is degenerate");
        }
        double u_min = 0.0;
        double u_max = 0.0;
        double v_min = 0.0;
        double v_max = 0.0;
        BRepTools::UVBounds(face_, u_min, u_max, v_min, v_max);
        const double span = std::max(u_max - u_min, v_max - v_min);
        const double norm = std::hypot(a, b);
        const gp_Pnt2d uv = pcurve_.Value(t);
        for (double step : {1.0e-4, 1.0e-3, 1.0e-2}) {
            const double scale = step * span / norm;
            const BRepClass_FaceClassifier forward(
                face_, gp_Pnt2d(uv.X() + a * scale, uv.Y() + b * scale), 1.0e-9);
            const BRepClass_FaceClassifier backward(
                face_, gp_Pnt2d(uv.X() - a * scale, uv.Y() - b * scale), 1.0e-9);
            const bool forward_in = forward.State() == TopAbs_IN;
            const bool backward_in = backward.State() == TopAbs_IN;
            if (forward_in != backward_in) {
                /* N x T points into the face exactly when the forward probe is inside. */
                out_sign_ = forward_in ? -1.0 : 1.0;
                return;
            }
        }
        throw std::runtime_error(name_ + " could not determine the face side of the edge");
    }

    std::string name_;
    TopoDS_Face face_;
    TopoDS_Edge edge_;
    BRepAdaptor_Surface surface_;
    BRepAdaptor_Curve curve_;
    BRepAdaptor_Curve2d pcurve_;
    bool reversed_ {false};
    double length_ {0.0};
    double out_sign_ {1.0};
};

/* Quintic Hermite cross section: three poles from each support.
   With P1 = P0 + d T and P2 = P0 + 2 d T + (5/4) k d^2 N the curve leaves the
   support along T with normal curvature exactly k: C'(0) = 5 d T and
   C''(0) . N = 20 (P2 - 2 P1 + P0) . N = 25 k d^2 = k |C'(0)|^2.
   Handle lengths are d = factor * chord / 5; factor 1 spaces the poles
   evenly along a straight bridge. */
void hermite_poles(
    const Frame& a, const Frame& b, int continuity_a, int continuity_b,
    double factor_a, double factor_b, gp_Pnt output[6]) {
    const double chord = a.point.Distance(b.point);
    auto near_end = [&](const Frame& frame, const Frame& other, int continuity,
                        double factor, gp_Pnt& first, gp_Pnt& second) {
        if (continuity == 0) {
            const gp_Vec toward(frame.point, other.point);
            first = frame.point.Translated(toward / 5.0);
            second = frame.point.Translated(toward * (2.0 / 5.0));
            return;
        }
        const double d = factor * chord / 5.0;
        first = frame.point.Translated(frame.out * d);
        gp_Vec offset = frame.out * (2.0 * d);
        if (continuity == 2) {
            offset += frame.normal * (1.25 * frame.curvature * d * d);
        }
        second = frame.point.Translated(offset);
    };
    output[0] = a.point;
    output[5] = b.point;
    near_end(a, b, continuity_a, factor_a, output[1], output[2]);
    near_end(b, a, continuity_b, factor_b, output[4], output[3]);
}

/* de Casteljau evaluation of a Bezier vector polynomial with `count` coefficients. */
gp_Vec bezier_value(const gp_Vec* coefficients, int count, double t) {
    gp_Vec work[6];
    for (int i = 0; i < count; ++i) work[i] = coefficients[i];
    for (int level = count - 1; level > 0; --level) {
        for (int i = 0; i < level; ++i) work[i] = work[i] * (1.0 - t) + work[i + 1] * t;
    }
    return work[0];
}

/* Scale-free minimum-variation fairness L^3 * integral (d kappa / ds)^2 ds:
   the class-A criterion for a curvature profile that rises and falls once. */
double fairness(const gp_Pnt poles[6]) {
    gp_Vec first[5];
    gp_Vec second[4];
    for (int i = 0; i < 5; ++i) first[i] = gp_Vec(poles[i], poles[i + 1]) * 5.0;
    for (int i = 0; i < 4; ++i) second[i] = (first[i + 1] - first[i]) * 4.0;
    constexpr int samples = 64;
    double previous_kappa = 0.0;
    double previous_s = 0.0;
    double s = 0.0;
    double energy = 0.0;
    double previous_speed = 0.0;
    for (int j = 0; j <= samples; ++j) {
        const double t = static_cast<double>(j) / samples;
        const gp_Vec d1 = bezier_value(first, 5, t);
        const gp_Vec d2 = bezier_value(second, 4, t);
        const double speed = d1.Magnitude();
        if (!(speed > 1.0e-300)) return std::numeric_limits<double>::infinity();
        const double kappa = d1.Crossed(d2).Magnitude() / (speed * speed * speed);
        if (j > 0) {
            s += 0.5 * (speed + previous_speed) / samples;
            const double ds = s - previous_s;
            if (ds > 0.0) {
                const double slope = (kappa - previous_kappa) / ds;
                energy += slope * slope * ds;
            }
        }
        previous_kappa = kappa;
        previous_s = s;
        previous_speed = speed;
    }
    return energy * s * s * s;
}

void section_poles(
    const Frame& a, const Frame& b, int continuity_a, int continuity_b,
    double tension_a, double tension_b, gp_Pnt output[6]) {
    if (!(a.point.Distance(b.point) > 1.0e-12)) {
        throw std::invalid_argument(
            "blend supports touch along the edges; the bridge would be degenerate");
    }
    hermite_poles(a, b, continuity_a, continuity_b, tension_a, tension_b, output);
}

Handle(Geom_BSplineSurface) build_surface(
    const BlendFrameSource& source, double first, double last,
    int continuity_a, double tension_a, int continuity_b, double tension_b,
    std::size_t sections) {
    std::vector<std::vector<gp_Pnt>> rows(6, std::vector<gp_Pnt>(sections));
    Handle(TColStd_HArray1OfReal) parameters =
        new TColStd_HArray1OfReal(1, static_cast<int>(sections));
    for (std::size_t i = 0; i < sections; ++i) {
        const double s = i + 1 == sections
            ? last
            : first + (last - first) * static_cast<double>(i) / static_cast<double>(sections - 1);
        parameters->SetValue(static_cast<int>(i) + 1, s);
        const BlendFrames frames = source(s);
        gp_Pnt poles[6];
        section_poles(
            frames.first, frames.second, continuity_a, continuity_b, tension_a, tension_b, poles);
        for (int row = 0; row < 6; ++row) {
            rows[row][i] = poles[row];
        }
    }
    std::vector<Handle(Geom_BSplineCurve)> curves;
    for (const auto& row : rows) {
        Handle(TColgp_HArray1OfPnt) points =
            new TColgp_HArray1OfPnt(1, static_cast<int>(sections));
        for (std::size_t i = 0; i < sections; ++i) {
            points->SetValue(static_cast<int>(i) + 1, row[i]);
        }
        GeomAPI_Interpolate interpolate(points, parameters, false, 1.0e-12);
        interpolate.Perform();
        if (!interpolate.IsDone()) {
            throw std::runtime_error("blend section interpolation failed");
        }
        curves.push_back(interpolate.Curve());
    }
    const Handle(Geom_BSplineCurve)& reference = curves.front();
    for (const auto& curve : curves) {
        if (curve->NbPoles() != reference->NbPoles() || curve->Degree() != reference->Degree()
            || curve->NbKnots() != reference->NbKnots()) {
            throw std::runtime_error("blend rows produced incompatible interpolations");
        }
    }
    TColgp_Array2OfPnt poles(1, 6, 1, reference->NbPoles());
    for (int row = 0; row < 6; ++row) {
        for (int column = 1; column <= reference->NbPoles(); ++column) {
            poles.SetValue(row + 1, column, curves[row]->Pole(column));
        }
    }
    TColStd_Array1OfReal u_knots(1, 2);
    u_knots.SetValue(1, 0.0);
    u_knots.SetValue(2, 1.0);
    TColStd_Array1OfInteger u_mults(1, 2);
    u_mults.SetValue(1, 6);
    u_mults.SetValue(2, 6);
    return new Geom_BSplineSurface(
        poles, u_knots, reference->Knots(), u_mults, reference->Multiplicities(),
        5, reference->Degree());
}

/* Worst boundary deviation of the surface from the frame points, sampled
   midway between sections where interpolation error peaks. */
double boundary_deviation(
    const Handle(Geom_BSplineSurface)& surface, const BlendFrameSource& source,
    double first, double last, std::size_t sections) {
    double worst = 0.0;
    const std::size_t probes = 2 * (sections - 1);
    for (std::size_t i = 0; i < probes; ++i) {
        const double s = first
            + (last - first) * (static_cast<double>(i) + 0.5) / static_cast<double>(probes);
        const BlendFrames frames = source(s);
        worst = std::max(worst, surface->Value(0.0, s).Distance(frames.first.point));
        worst = std::max(worst, surface->Value(1.0, s).Distance(frames.second.point));
    }
    return worst;
}

#endif

void validate_options(const BlendOptions& options) {
    if (!(options.tolerance > 0.0) || !std::isfinite(options.tolerance)) {
        throw std::invalid_argument("blend tolerance must be positive");
    }
    if (options.sections != 0 && (options.sections < 4 || options.sections > 4096)) {
        throw std::invalid_argument("blend sections must be between 4 and 4096");
    }
    if (options.reverse_b < -1 || options.reverse_b > 1) {
        throw std::invalid_argument("blend reverse_b must be -1, 0, or 1");
    }
}

}  // namespace

#ifdef CADFLOW_WITH_OCCT
namespace {

/* Minimize fairness summed over probe sections over the handle factors that
   are 0 (automatic); fixed factors stay as given. A single value adapts to
   the corner angle without letting the factor wander from section to
   section, which would ripple the surface along the edges. */
double optimal_tension(
    const std::vector<BlendFrames>& probes, int continuity_a, int continuity_b,
    double fixed_a, double fixed_b) {
    for (const auto& [frame_a, frame_b] : probes) {
        if (!(frame_a.point.Distance(frame_b.point) > 1.0e-12)) {
            throw std::invalid_argument(
                "blend supports touch along the edges; the bridge would be degenerate");
        }
    }
    if (probes.empty()) {
        throw std::invalid_argument("blend tension needs at least one probe section");
    }
    /* A tiny pull towards 1 breaks ties where every factor is equally fair,
       e.g. a straight bridge, without moving real optima. */
    auto cost = [&](double factor) {
        double total = 0.0;
        for (const auto& [frame_a, frame_b] : probes) {
            gp_Pnt poles[6];
            hermite_poles(
                frame_a, frame_b, continuity_a, continuity_b,
                fixed_a > 0.0 ? fixed_a : factor, fixed_b > 0.0 ? fixed_b : factor, poles);
            total += fairness(poles);
        }
        return total / static_cast<double>(probes.size())
            + 1.0e-6 * (factor - 1.0) * (factor - 1.0);
    };
    constexpr double low = 0.3;
    constexpr double high = 4.0;
    constexpr int scan = 74;
    double best = 1.0;
    double best_cost = std::numeric_limits<double>::infinity();
    for (int i = 0; i <= scan; ++i) {
        const double factor = low + (high - low) * i / scan;
        const double value = cost(factor);
        if (value < best_cost) {
            best_cost = value;
            best = factor;
        }
    }
    const double step = (high - low) / scan;
    double left = std::max(low, best - step);
    double right = std::min(high, best + step);
    constexpr double ratio = 0.6180339887498949;
    double x1 = right - ratio * (right - left);
    double x2 = left + ratio * (right - left);
    double f1 = cost(x1);
    double f2 = cost(x2);
    while (right - left > 1.0e-6) {
        if (f1 < f2) {
            right = x2;
            x2 = x1;
            f2 = f1;
            x1 = right - ratio * (right - left);
            f1 = cost(x1);
        } else {
            left = x1;
            x1 = x2;
            f1 = f2;
            x2 = left + ratio * (right - left);
            f2 = cost(x2);
        }
    }
    return 0.5 * (left + right);
}

std::vector<BlendFrames> probe_frames(const BlendFrameSource& source, double first, double last) {
    constexpr int probes = 16;
    std::vector<BlendFrames> output;
    for (int i = 0; i < probes; ++i) {
        output.push_back(source(first + (last - first) * (i + 0.5) / probes));
    }
    return output;
}

}  // namespace

double blend_tension(
    const std::vector<BlendFrames>& probes, int continuity_a, int continuity_b) {
    return optimal_tension(probes, continuity_a, continuity_b, 0.0, 0.0);
}

BlendGeometry blend_along(
    const BlendFrameSource& frames, double first, double last,
    int continuity_a, double tension_a, int continuity_b, double tension_b,
    const BlendOptions& options) {
    validate_options(options);
    if (!(last > first)) {
        throw std::invalid_argument("blend parameter range is empty");
    }
    BlendGeometry output;
    output.sections = options.sections ? options.sections : 16;
    while (true) {
        output.surface = build_surface(
            frames, first, last, continuity_a, tension_a, continuity_b, tension_b,
            output.sections);
        output.deviation =
            boundary_deviation(output.surface, frames, first, last, output.sections);
        if (output.deviation <= options.tolerance) {
            return output;
        }
        if (output.sections >= 1024) {
            std::ostringstream message;
            message << "blend boundary deviation " << output.deviation
                    << " exceeds tolerance " << options.tolerance
                    << " at 1024 sections; the support edges may be too irregular";
            throw std::runtime_error(message.str());
        }
        output.sections = std::min<std::size_t>(1024, 2 * output.sections);
    }
}

BlendGeometry blend_geometry(
    const TopoDS_Face& face_a, const TopoDS_Edge& edge_a, int continuity_a, double tension_a,
    const TopoDS_Face& face_b, const TopoDS_Edge& edge_b, int continuity_b, double tension_b,
    const BlendOptions& options) {
    BlendSide side_a {0, 0, continuity_a, tension_a};
    BlendSide side_b {0, 0, continuity_b, tension_b};
    validate_side(side_a, "blend side A");
    validate_side(side_b, "blend side B");
    validate_options(options);
    const Support a(face_a, edge_a, "blend side A");
    const Support b(face_b, edge_b, "blend side B");
    bool flip_b = options.reverse_b == 1;
    if (options.reverse_b == -1) {
        const double straight = a.point(0.0).Distance(b.point(0.0))
            + a.point(1.0).Distance(b.point(1.0));
        const double crossed = a.point(0.0).Distance(b.point(1.0))
            + a.point(1.0).Distance(b.point(0.0));
        flip_b = crossed < straight;
    }
    const BlendFrameSource source = [&](double s) {
        return BlendFrames(a.frame(s), b.frame(flip_b ? 1.0 - s : s));
    };
    const bool auto_a = continuity_a != 0 && tension_a == 0.0;
    const bool auto_b = continuity_b != 0 && tension_b == 0.0;
    if (auto_a || auto_b) {
        const double factor = optimal_tension(
            probe_frames(source, 0.0, 1.0), continuity_a, continuity_b,
            auto_a ? 0.0 : tension_a, auto_b ? 0.0 : tension_b);
        if (auto_a) tension_a = factor;
        if (auto_b) tension_b = factor;
    }
    return blend_along(
        source, 0.0, 1.0, continuity_a, tension_a, continuity_b, tension_b, options);
}
#endif

core::ShapeId blend_surface(
    core::Session& session,
    const BlendSide& side_a,
    const BlendSide& side_b,
    const BlendOptions& options) {
    validate_side(side_a, "blend side A");
    validate_side(side_b, "blend side B");
    validate_options(options);
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Shape& face_a = core::get_shape(session, side_a.face).native;
    const TopoDS_Shape& face_b = core::get_shape(session, side_b.face).native;
    const TopoDS_Shape& edge_a = core::get_shape(session, side_a.edge).native;
    const TopoDS_Shape& edge_b = core::get_shape(session, side_b.edge).native;
    auto require = [](const TopoDS_Shape& shape, TopAbs_ShapeEnum type, const char* message) {
        if (shape.IsNull() || shape.ShapeType() != type) {
            throw std::invalid_argument(message);
        }
    };
    require(face_a, TopAbs_FACE, "blend side A support must be one BREP face");
    require(face_b, TopAbs_FACE, "blend side B support must be one BREP face");
    require(edge_a, TopAbs_EDGE, "blend side A boundary must be one BREP edge");
    require(edge_b, TopAbs_EDGE, "blend side B boundary must be one BREP edge");
    const BlendGeometry geometry = blend_geometry(
        TopoDS::Face(face_a), TopoDS::Edge(edge_a), side_a.continuity, side_a.tension,
        TopoDS::Face(face_b), TopoDS::Edge(edge_b), side_b.continuity, side_b.tension,
        options);
    BRepBuilderAPI_MakeFace face(geometry.surface, std::max(options.tolerance, 1.0e-7));
    if (!face.IsDone()) {
        throw std::runtime_error("OCCT could not make a face from the blend surface");
    }
    core::Shape output {core::Shape::Kind::BlendSurface};
    output.native = face.Face();
    output.a = static_cast<double>(geometry.sections);
    output.b = geometry.deviation;
    return core::store(session, std::move(output));
#else
    (void)session;
    throw std::runtime_error("blend surfaces require the OCCT backend");
#endif
}

}  // namespace cadflow::kernel
