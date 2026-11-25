#include "analysis/surface_analysis.h"

#include "kernel/differential.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef CADFLOW_WITH_OCCT
#include <BOPAlgo_ArgumentAnalyzer.hxx>
#include <BOPAlgo_CheckResult.hxx>
#include <BRepAdaptor_Curve.hxx>
#include <BRepAdaptor_Curve2d.hxx>
#include <BRepAdaptor_Surface.hxx>
#include <BRepBndLib.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepClass_FaceClassifier.hxx>
#include <BRepGProp.hxx>
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRepTools.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Geom_BezierSurface.hxx>
#include <Poly_Triangulation.hxx>
#include <TColStd_Array1OfInteger.hxx>
#include <TColStd_Array1OfReal.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TopAbs.hxx>
#include <TopExp.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopTools_IndexedDataMapOfShapeListOfShape.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Pnt.hxx>
#include <gp_Pnt2d.hxx>
#include <gp_Vec.hxx>
#endif

namespace cadflow::analysis {
namespace {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();
[[maybe_unused]] constexpr double kDegrees = 180.0 / core::kPi;

void validate_tolerances(const ContinuityTolerances& tolerances) {
    if (!(tolerances.position > 0.0) || !std::isfinite(tolerances.position)) {
        throw std::invalid_argument("continuity position tolerance must be positive");
    }
    if (!(tolerances.angle_degrees > 0.0) || !std::isfinite(tolerances.angle_degrees)) {
        throw std::invalid_argument("continuity angle tolerance must be positive");
    }
    if (!(tolerances.curvature_ratio > 0.0)
        || !std::isfinite(tolerances.curvature_ratio)) {
        throw std::invalid_argument("continuity curvature tolerance must be positive");
    }
}

void validate_samples(std::size_t samples) {
    if (samples < 2 || samples > 100000) {
        throw std::invalid_argument("continuity samples must be between 2 and 100000");
    }
}

/* Minimal JSON emitter; every key is a compile-time literal and non-finite
   numbers are written as null so the output is always valid JSON. */
class Json {
public:
    Json() { out_ << std::setprecision(17); }

    Json& key(const char* name) {
        comma();
        out_ << '"' << name << "\":";
        fresh_ = true;
        return *this;
    }
    Json& number(double value) {
        comma();
        if (std::isfinite(value)) {
            out_ << value;
        } else {
            out_ << "null";
        }
        return *this;
    }
    Json& null() {
        comma();
        out_ << "null";
        return *this;
    }
    Json& integer(long long value) {
        comma();
        out_ << value;
        return *this;
    }
    Json& boolean(bool value) {
        comma();
        out_ << (value ? "true" : "false");
        return *this;
    }
    Json& string(const char* value) {
        comma();
        out_ << '"' << value << '"';
        return *this;
    }
    Json& point(const double values[3]) {
        begin_array();
        for (int axis = 0; axis < 3; ++axis) {
            number(values[axis]);
        }
        return end_array();
    }
    Json& begin_object() {
        comma();
        out_ << '{';
        fresh_ = true;
        return *this;
    }
    Json& end_object() {
        out_ << '}';
        fresh_ = false;
        return *this;
    }
    Json& begin_array() {
        comma();
        out_ << '[';
        fresh_ = true;
        return *this;
    }
    Json& end_array() {
        out_ << ']';
        fresh_ = false;
        return *this;
    }
    std::string str() const { return out_.str(); }

private:
    void comma() {
        if (!fresh_) {
            out_ << ',';
        }
        fresh_ = false;
    }

    std::ostringstream out_;
    bool fresh_ {true};
};

#ifdef CADFLOW_WITH_OCCT

TopoDS_Face require_face(const TopoDS_Shape& shape) {
    if (shape.IsNull() || shape.ShapeType() != TopAbs_FACE) {
        throw std::invalid_argument("surface analysis input must be one BREP face");
    }
    return TopoDS::Face(shape);
}

using kernel::differential::LocalGeometry;
using kernel::differential::PrincipalCurvature;
using kernel::differential::evaluate;
using kernel::differential::normal_curvature;
using kernel::differential::principal_curvature;

void copy_point(const gp_Pnt& point, double output[3]) {
    output[0] = point.X();
    output[1] = point.Y();
    output[2] = point.Z();
}

void copy_vector(const gp_Vec& vector, double output[3]) {
    output[0] = vector.X();
    output[1] = vector.Y();
    output[2] = vector.Z();
}

double edge_length(const TopoDS_Edge& edge) {
    GProp_GProps properties;
    BRepGProp::LinearProperties(edge, properties);
    return properties.Mass();
}

double shape_diagonal(const TopoDS_Shape& shape) {
    /* AddOptimal bounds the surface itself; Add would return the control-pole
       hull, which can be orders of magnitude larger for high-degree fits. */
    Bnd_Box box;
    BRepBndLib::AddOptimal(shape, box, false, false);
    if (box.IsVoid()) {
        return 0.0;
    }
    return std::sqrt(box.SquareExtent());
}

/* Closest parameter on a bounded edge curve: coarse scan plus clamped Newton. */
double closest_curve_parameter(
    const BRepAdaptor_Curve& curve, const gp_Pnt& reference, double& distance) {
    const double first = curve.FirstParameter();
    const double last = curve.LastParameter();
    double best = first;
    double best_squared = std::numeric_limits<double>::infinity();
    constexpr int samples = 32;
    for (int index = 0; index <= samples; ++index) {
        const double t = first + (last - first) * index / samples;
        const double squared = curve.Value(t).SquareDistance(reference);
        if (squared < best_squared) {
            best_squared = squared;
            best = t;
        }
    }
    for (int iteration = 0; iteration < 24; ++iteration) {
        gp_Pnt point;
        gp_Vec d1;
        gp_Vec d2;
        curve.D2(best, point, d1, d2);
        const gp_Vec residual(reference, point);
        const double gradient = residual.Dot(d1);
        const double hessian = d1.Dot(d1) + residual.Dot(d2);
        if (std::abs(hessian) <= 1.0e-30) {
            break;
        }
        const double next = std::clamp(best - gradient / hessian, first, last);
        const double step = next - best;
        best = next;
        if (std::abs(step) <= 1.0e-14 * std::max(1.0, std::abs(last - first))) {
            break;
        }
    }
    distance = curve.Value(best).Distance(reference);
    return best;
}

TopAbs_Orientation edge_orientation_in_face(
    const TopoDS_Edge& edge, const TopoDS_Face& face) {
    for (TopExp_Explorer explorer(face, TopAbs_EDGE); explorer.More(); explorer.Next()) {
        if (explorer.Current().IsSame(edge)) {
            return explorer.Current().Orientation();
        }
    }
    throw std::runtime_error("edge does not bound the face");
}

struct EdgeContinuity {
    std::size_t valid_samples {0};
    std::size_t singular_samples {0};
    double max_gap {0.0};
    double max_angle {0.0};
    double max_ratio {0.0};
    double max_curvature_gap {0.0};
    double curvature_a {kNaN};
    double curvature_b {kNaN};
    double gap_point[3] {kNaN, kNaN, kNaN};
    double angle_point[3] {kNaN, kNaN, kNaN};
    double curvature_point[3] {kNaN, kNaN, kNaN};
    bool orientation_flipped {false};
    double length {0.0};
};

const char* continuity_level(
    const EdgeContinuity& value, const ContinuityTolerances& tolerances) {
    if (value.valid_samples == 0) {
        return "unknown";
    }
    if (value.max_gap > tolerances.position) {
        return "gap";
    }
    if (value.max_angle > tolerances.angle_degrees) {
        return "G0";
    }
    if (value.max_ratio > tolerances.curvature_ratio) {
        return "G1";
    }
    return "G2";
}

/* Sample one boundary.  When `shared` the two sides use the same TopoDS edge
   and therefore the same curve parameter; otherwise the side-B parameter is
   found by projection and samples outside the overlap are ignored. */
EdgeContinuity measure_boundary(
    const TopoDS_Face& face_a, const TopoDS_Edge& edge_a,
    const TopoDS_Face& face_b, const TopoDS_Edge& edge_b,
    bool shared, std::size_t samples, double overlap_tolerance) {
    EdgeContinuity output;
    output.length = edge_length(edge_a);

    const BRepAdaptor_Surface surface_a(face_a, false);
    const BRepAdaptor_Surface surface_b(face_b, false);
    const BRepAdaptor_Curve2d pcurve_a(edge_a, face_a);
    const BRepAdaptor_Curve2d pcurve_b(edge_b, face_b);
    const BRepAdaptor_Curve curve_a(edge_a);
    const BRepAdaptor_Curve curve_b(edge_b);
    const bool reversed_a = face_a.Orientation() == TopAbs_REVERSED;
    const bool reversed_b = face_b.Orientation() == TopAbs_REVERSED;

    /* In a coherently oriented shell a shared edge is traversed in opposite
       directions by its two faces; equal directions mean flipped normals. */
    double normal_sign_b = 1.0;
    if (shared) {
        if (edge_orientation_in_face(edge_a, face_a)
            == edge_orientation_in_face(edge_b, face_b)) {
            normal_sign_b = -1.0;
            output.orientation_flipped = true;
        }
    }

    struct Sample {
        LocalGeometry a;
        LocalGeometry b;
        gp_Vec tangent;
    };
    std::vector<Sample> measured;
    measured.reserve(samples);
    const double first = curve_a.FirstParameter();
    const double last = curve_a.LastParameter();
    double flipped_votes = 0.0;
    for (std::size_t index = 0; index < samples; ++index) {
        const double fraction = samples == 1
            ? 0.5
            : 0.01 + 0.98 * static_cast<double>(index) / static_cast<double>(samples - 1);
        const double t = first + (last - first) * fraction;
        gp_Pnt edge_point;
        gp_Vec tangent;
        curve_a.D1(t, edge_point, tangent);
        double t_b = t;
        if (!shared) {
            double distance = 0.0;
            t_b = closest_curve_parameter(curve_b, edge_point, distance);
            if (distance > overlap_tolerance) {
                continue;
            }
        }
        const gp_Pnt2d uv_a = pcurve_a.Value(t);
        const gp_Pnt2d uv_b = pcurve_b.Value(t_b);
        Sample sample {
            evaluate(surface_a, reversed_a, uv_a.X(), uv_a.Y()),
            evaluate(surface_b, reversed_b, uv_b.X(), uv_b.Y()),
            tangent,
        };
        if (!sample.a.regular || !sample.b.regular
            || tangent.Magnitude() <= 1.0e-300) {
            ++output.singular_samples;
            continue;
        }
        if (!shared) {
            flipped_votes += sample.a.normal.Dot(sample.b.normal) < 0.0 ? 1.0 : -1.0;
        }
        measured.push_back(sample);
    }
    if (!shared && flipped_votes > 0.0) {
        /* Separate faces carry no shared orientation; treat normals as lines. */
        normal_sign_b = -1.0;
        output.orientation_flipped = true;
    }

    for (const Sample& sample : measured) {
        ++output.valid_samples;
        const double gap = sample.a.point.Distance(sample.b.point);
        if (gap >= output.max_gap) {
            output.max_gap = gap;
            copy_point(sample.a.point, output.gap_point);
        }
        const gp_Vec normal_b = sample.b.normal * normal_sign_b;
        const double cosine = std::clamp(sample.a.normal.Dot(normal_b), -1.0, 1.0);
        const double angle = std::acos(cosine) * kDegrees;
        if (angle >= output.max_angle) {
            output.max_angle = angle;
            copy_point(sample.a.point, output.angle_point);
        }
        gp_Vec across = sample.a.normal.Crossed(sample.tangent);
        const double across_length = across.Magnitude();
        if (across_length <= 1.0e-300) {
            continue;
        }
        across /= across_length;
        const double curvature_a = normal_curvature(sample.a, across);
        const double curvature_b = normal_curvature(sample.b, across, normal_sign_b);
        if (!std::isfinite(curvature_a) || !std::isfinite(curvature_b)) {
            continue;
        }
        const double difference = std::abs(curvature_a - curvature_b);
        /* Relative to how curved the surfaces are here, not only across the
           edge: where both across-curvatures vanish (a round's end section)
           a 1e-3 numerical difference would otherwise read as a 100% jump. */
        const PrincipalCurvature principal_a = principal_curvature(sample.a);
        const PrincipalCurvature principal_b = principal_curvature(sample.b);
        double scale = std::max(std::abs(curvature_a), std::abs(curvature_b));
        for (double k : {principal_a.k_min, principal_a.k_max, principal_b.k_min, principal_b.k_max}) {
            if (std::isfinite(k)) scale = std::max(scale, std::abs(k));
        }
        const double ratio = scale > 1.0e-12 ? difference / scale : 0.0;
        output.max_curvature_gap = std::max(output.max_curvature_gap, difference);
        if (ratio >= output.max_ratio) {
            output.max_ratio = ratio;
            output.curvature_a = curvature_a;
            output.curvature_b = curvature_b;
            copy_point(sample.a.point, output.curvature_point);
        }
    }
    return output;
}

void write_edge_metrics(
    Json& json, const EdgeContinuity& value, const ContinuityTolerances& tolerances) {
    json.key("level").string(continuity_level(value, tolerances));
    json.key("orientation_flipped").boolean(value.orientation_flipped);
    json.key("length").number(value.length);
    json.key("valid_samples").integer(static_cast<long long>(value.valid_samples));
    json.key("singular_samples").integer(static_cast<long long>(value.singular_samples));
    json.key("max_gap").number(value.max_gap);
    json.key("max_angle_degrees").number(value.max_angle);
    json.key("max_curvature_ratio").number(value.max_ratio);
    json.key("max_curvature_gap").number(value.max_curvature_gap);
    json.key("curvature_a").number(value.curvature_a);
    json.key("curvature_b").number(value.curvature_b);
    json.key("worst_gap_point").point(value.gap_point);
    json.key("worst_angle_point").point(value.angle_point);
    json.key("worst_curvature_point").point(value.curvature_point);
}

struct ContinuitySummary {
    std::size_t g2 {0};
    std::size_t g1 {0};
    std::size_t g0 {0};
    std::size_t gap {0};
    std::size_t unknown {0};
    double worst_gap {0.0};
    double worst_angle {0.0};
    double worst_ratio {0.0};

    void add(const EdgeContinuity& value, const ContinuityTolerances& tolerances) {
        const std::string level = continuity_level(value, tolerances);
        if (level == "G2") ++g2;
        else if (level == "G1") ++g1;
        else if (level == "G0") ++g0;
        else if (level == "gap") ++gap;
        else ++unknown;
        if (value.valid_samples) {
            worst_gap = std::max(worst_gap, value.max_gap);
            worst_angle = std::max(worst_angle, value.max_angle);
            worst_ratio = std::max(worst_ratio, value.max_ratio);
        }
    }

    void write(Json& json) const {
        json.key("checked").integer(static_cast<long long>(g2 + g1 + g0 + gap + unknown));
        json.key("G2").integer(static_cast<long long>(g2));
        json.key("G1").integer(static_cast<long long>(g1));
        json.key("G0").integer(static_cast<long long>(g0));
        json.key("gap").integer(static_cast<long long>(gap));
        json.key("unknown").integer(static_cast<long long>(unknown));
        json.key("worst_gap").number(worst_gap);
        json.key("worst_angle_degrees").number(worst_angle);
        json.key("worst_curvature_ratio").number(worst_ratio);
    }
};

void write_header(
    Json& json, const char* mode, std::size_t samples,
    const ContinuityTolerances& tolerances) {
    json.key("mode").string(mode);
    json.key("samples").integer(static_cast<long long>(samples));
    json.key("tolerances").begin_object();
    json.key("position").number(tolerances.position);
    json.key("angle_degrees").number(tolerances.angle_degrees);
    json.key("curvature_ratio").number(tolerances.curvature_ratio);
    json.end_object();
}

/* Parameter-space bounds of a face, clipped to a finite range. */
void face_bounds(
    const TopoDS_Face& face, double& u_min, double& u_max, double& v_min, double& v_max) {
    BRepTools::UVBounds(face, u_min, u_max, v_min, v_max);
    if (!std::isfinite(u_min) || !std::isfinite(u_max)
        || !std::isfinite(v_min) || !std::isfinite(v_max)
        || !(u_max > u_min) || !(v_max > v_min)) {
        throw std::runtime_error("surface face has unbounded or empty parameters");
    }
}

bool inside_face(const TopoDS_Face& face, double u, double v) {
    const BRepClass_FaceClassifier classifier(face, gp_Pnt2d(u, v), 1.0e-9);
    const TopAbs_State state = classifier.State();
    return state == TopAbs_IN || state == TopAbs_ON;
}

const char* surface_type_name(GeomAbs_SurfaceType type) {
    switch (type) {
    case GeomAbs_Plane: return "plane";
    case GeomAbs_Cylinder: return "cylinder";
    case GeomAbs_Cone: return "cone";
    case GeomAbs_Sphere: return "sphere";
    case GeomAbs_Torus: return "torus";
    case GeomAbs_BezierSurface: return "bezier";
    case GeomAbs_BSplineSurface: return "bspline";
    case GeomAbs_SurfaceOfRevolution: return "revolution";
    case GeomAbs_SurfaceOfExtrusion: return "extrusion";
    case GeomAbs_OffsetSurface: return "offset";
    default: return "other";
    }
}

/* Lowest parametric continuity order at interior knots strictly inside
   [low, high]; -1 means no interior knot (smooth as the basis allows). */
int minimum_knot_continuity(
    const TColStd_Array1OfReal& knots, const TColStd_Array1OfInteger& multiplicities,
    int degree, double low, double high) {
    int result = -1;
    const double margin = 1.0e-9 * std::max(1.0, std::abs(high - low));
    for (int index = knots.Lower() + 1; index < knots.Upper(); ++index) {
        const double knot = knots(index);
        if (knot <= low + margin || knot >= high - margin) {
            continue;
        }
        const int order = degree - multiplicities(index);
        result = result < 0 ? order : std::min(result, order);
    }
    return result;
}

/* Count direction reversals of second differences along control-net rows. */
int control_net_reversals(const TColgp_Array2OfPnt& poles, bool along_rows) {
    const int outer_low = along_rows ? poles.LowerRow() : poles.LowerCol();
    const int outer_high = along_rows ? poles.UpperRow() : poles.UpperCol();
    const int inner_low = along_rows ? poles.LowerCol() : poles.LowerRow();
    const int inner_high = along_rows ? poles.UpperCol() : poles.UpperRow();
    int worst = 0;
    for (int outer = outer_low; outer <= outer_high; ++outer) {
        auto pole = [&](int inner) -> const gp_Pnt& {
            return along_rows ? poles(outer, inner) : poles(inner, outer);
        };
        double span = 0.0;
        for (int inner = inner_low + 1; inner <= inner_high; ++inner) {
            span += pole(inner).Distance(pole(inner - 1));
        }
        const double threshold = 1.0e-9 * std::max(span, 1.0e-300);
        int reversals = 0;
        bool has_previous = false;
        gp_Vec previous;
        for (int inner = inner_low + 1; inner < inner_high; ++inner) {
            const gp_Vec second(
                pole(inner + 1).XYZ() - 2.0 * pole(inner).XYZ() + pole(inner - 1).XYZ());
            if (second.Magnitude() <= threshold) {
                continue;
            }
            if (has_previous && second.Dot(previous) < 0.0) {
                ++reversals;
            }
            previous = second;
            has_previous = true;
        }
        worst = std::max(worst, reversals);
    }
    return worst;
}

int sign_changes(const std::vector<double>& values) {
    double scale = 0.0;
    for (double value : values) {
        if (std::isfinite(value)) {
            scale = std::max(scale, std::abs(value));
        }
    }
    const double threshold = std::max(1.0e-3 * scale, 1.0e-12);
    int changes = 0;
    int previous = 0;
    for (double value : values) {
        if (!std::isfinite(value) || std::abs(value) <= threshold) {
            continue;
        }
        const int sign = value > 0.0 ? 1 : -1;
        if (previous != 0 && sign != previous) {
            ++changes;
        }
        previous = sign;
    }
    return changes;
}

struct Issue {
    const char* severity;
    const char* code;
    std::string message;
    const char* hint;
};

void write_issue(Json& json, const Issue& issue) {
    json.begin_object();
    json.key("severity").string(issue.severity);
    json.key("code").string(issue.code);
    json.key("message").string(issue.message.c_str());
    json.key("hint").string(issue.hint);
    json.end_object();
}

std::string format_number(double value) {
    std::ostringstream stream;
    stream << std::setprecision(6) << value;
    return stream.str();
}

void analyze_face_quality(
    Json& json, const TopoDS_Face& face, std::size_t face_index,
    std::size_t samples, std::vector<Issue>& shape_issues) {
    std::vector<Issue> issues;
    const BRepAdaptor_Surface surface(face, true);
    const bool reversed = face.Orientation() == TopAbs_REVERSED;
    double u_min = 0.0;
    double u_max = 0.0;
    double v_min = 0.0;
    double v_max = 0.0;
    face_bounds(face, u_min, u_max, v_min, v_max);
    const double diagonal = shape_diagonal(face);

    json.begin_object();
    json.key("face_index").integer(static_cast<long long>(face_index));
    json.key("surface_type").string(surface_type_name(surface.GetType()));
    json.key("uv_bounds").begin_array()
        .number(u_min).number(u_max).number(v_min).number(v_max).end_array();
    GProp_GProps properties;
    BRepGProp::SurfaceProperties(face, properties);
    json.key("area").number(properties.Mass());

    const bool valid = BRepCheck_Analyzer(face, true).IsValid();
    json.key("valid").boolean(valid);
    if (!valid) {
        issues.push_back({
            "error", "surface.invalid_topology",
            "BRepCheck reports the face as invalid.",
            "Rebuild the face from clean boundary curves or sew with a tighter tolerance.",
        });
    }

    double max_tolerance = BRep_Tool::Tolerance(face);
    int degenerated = 0;
    for (TopExp_Explorer explorer(face, TopAbs_EDGE); explorer.More(); explorer.Next()) {
        const TopoDS_Edge edge = TopoDS::Edge(explorer.Current());
        max_tolerance = std::max(max_tolerance, BRep_Tool::Tolerance(edge));
        if (BRep_Tool::Degenerated(edge)) {
            ++degenerated;
        }
    }
    for (TopExp_Explorer explorer(face, TopAbs_VERTEX); explorer.More(); explorer.Next()) {
        max_tolerance = std::max(
            max_tolerance, BRep_Tool::Tolerance(TopoDS::Vertex(explorer.Current())));
    }
    json.key("max_tolerance").number(max_tolerance);
    json.key("degenerated_edges").integer(degenerated);
    if (max_tolerance > 1.0e-3) {
        issues.push_back({
            "warning", "surface.large_tolerance",
            "Face, edge, or vertex tolerance reaches " + format_number(max_tolerance) + ".",
            "Large tolerances usually hide boundary gaps; repair the boundary geometry "
            "instead of sewing with a loose tolerance.",
        });
    }

    /* Polynomial structure and hidden internal continuity breaks. */
    json.key("definition").begin_object();
    if (surface.GetType() == GeomAbs_BSplineSurface) {
        const Handle(Geom_BSplineSurface) bspline = surface.BSpline();
        json.key("u_degree").integer(bspline->UDegree());
        json.key("v_degree").integer(bspline->VDegree());
        json.key("u_poles").integer(bspline->NbUPoles());
        json.key("v_poles").integer(bspline->NbVPoles());
        json.key("u_knots").integer(bspline->NbUKnots());
        json.key("v_knots").integer(bspline->NbVKnots());
        json.key("rational").boolean(bspline->IsURational() || bspline->IsVRational());
        json.key("u_periodic").boolean(bspline->IsUPeriodic());
        json.key("v_periodic").boolean(bspline->IsVPeriodic());
        const int u_continuity = minimum_knot_continuity(
            bspline->UKnots(), bspline->UMultiplicities(), bspline->UDegree(),
            u_min, u_max);
        const int v_continuity = minimum_knot_continuity(
            bspline->VKnots(), bspline->VMultiplicities(), bspline->VDegree(),
            v_min, v_max);
        json.key("internal_u_continuity");
        if (u_continuity < 0) json.null(); else json.integer(u_continuity);
        json.key("internal_v_continuity");
        if (v_continuity < 0) json.null(); else json.integer(v_continuity);
        const int internal = (u_continuity < 0) ? v_continuity
            : (v_continuity < 0) ? u_continuity : std::min(u_continuity, v_continuity);
        if (internal == 0) {
            issues.push_back({
                "warning", "surface.internal_crease",
                "An interior knot has full multiplicity, so the face is only C0 inside: "
                "it can hide a tangent discontinuity.",
                "Remove the knot or split the face at the knot and check boundary continuity.",
            });
        } else if (internal == 1) {
            issues.push_back({
                "info", "surface.internal_c1",
                "An interior knot limits the face to C1, so curvature jumps inside the face.",
                "Reduce the knot multiplicity if curvature-continuous (G2) quality is required.",
            });
        }
        const TColgp_Array2OfPnt& poles = bspline->Poles();
        const int u_reversals = control_net_reversals(poles, false);
        const int v_reversals = control_net_reversals(poles, true);
        json.key("control_net_reversals_u").integer(u_reversals);
        json.key("control_net_reversals_v").integer(v_reversals);
        if (std::max(u_reversals, v_reversals) >= 3) {
            issues.push_back({
                "warning", "surface.control_net_undulation",
                "The control net changes bending direction "
                    + std::to_string(std::max(u_reversals, v_reversals))
                    + " times along one row; the surface is likely wavy.",
                "Smooth the control net, reduce the number of poles, or refit with "
                "a lower degree-of-freedom approximation.",
            });
        }
    } else if (surface.GetType() == GeomAbs_BezierSurface) {
        const Handle(Geom_BezierSurface) bezier = surface.Bezier();
        json.key("u_degree").integer(bezier->UDegree());
        json.key("v_degree").integer(bezier->VDegree());
        json.key("u_poles").integer(bezier->NbUPoles());
        json.key("v_poles").integer(bezier->NbVPoles());
        json.key("rational").boolean(bezier->IsURational() || bezier->IsVRational());
        const TColgp_Array2OfPnt& poles = bezier->Poles();
        const int u_reversals = control_net_reversals(poles, false);
        const int v_reversals = control_net_reversals(poles, true);
        json.key("control_net_reversals_u").integer(u_reversals);
        json.key("control_net_reversals_v").integer(v_reversals);
        if (std::max(u_reversals, v_reversals) >= 3) {
            issues.push_back({
                "warning", "surface.control_net_undulation",
                "The control net changes bending direction "
                    + std::to_string(std::max(u_reversals, v_reversals))
                    + " times along one row; the surface is likely wavy.",
                "Smooth the control net or lower the surface degree.",
            });
        }
    }
    json.end_object();

    /* Sampled curvature over the trimmed face. */
    std::size_t inside_count = 0;
    std::size_t singular_count = 0;
    double k_low = std::numeric_limits<double>::infinity();
    double k_high = -std::numeric_limits<double>::infinity();
    double gaussian_low = std::numeric_limits<double>::infinity();
    double gaussian_high = -std::numeric_limits<double>::infinity();
    double max_abs = 0.0;
    double max_abs_point[3] {kNaN, kNaN, kNaN};
    std::vector<double> grid_u(samples * samples, kNaN);
    std::vector<double> grid_v(samples * samples, kNaN);
    for (std::size_t i = 0; i < samples; ++i) {
        const double u = u_min + (u_max - u_min) * static_cast<double>(i) / (samples - 1);
        for (std::size_t j = 0; j < samples; ++j) {
            const double v = v_min + (v_max - v_min) * static_cast<double>(j) / (samples - 1);
            if (!inside_face(face, u, v)) {
                continue;
            }
            ++inside_count;
            const LocalGeometry geometry = evaluate(surface, reversed, u, v);
            if (!geometry.regular) {
                ++singular_count;
                continue;
            }
            const PrincipalCurvature curvature = principal_curvature(geometry);
            if (!std::isfinite(curvature.k_min) || !std::isfinite(curvature.k_max)) {
                ++singular_count;
                continue;
            }
            k_low = std::min(k_low, curvature.k_min);
            k_high = std::max(k_high, curvature.k_max);
            gaussian_low = std::min(gaussian_low, curvature.gaussian);
            gaussian_high = std::max(gaussian_high, curvature.gaussian);
            const double local = std::max(std::abs(curvature.k_min), std::abs(curvature.k_max));
            if (local > max_abs) {
                max_abs = local;
                copy_point(geometry.point, max_abs_point);
            }
            grid_u[i * samples + j] = normal_curvature(geometry, geometry.du);
            grid_v[i * samples + j] = normal_curvature(geometry, geometry.dv);
        }
    }
    int inflections_u = 0;
    int inflections_v = 0;
    for (std::size_t j = 0; j < samples; ++j) {
        std::vector<double> line;
        for (std::size_t i = 0; i < samples; ++i) line.push_back(grid_u[i * samples + j]);
        inflections_u = std::max(inflections_u, sign_changes(line));
    }
    for (std::size_t i = 0; i < samples; ++i) {
        std::vector<double> line(
            grid_v.begin() + static_cast<std::ptrdiff_t>(i * samples),
            grid_v.begin() + static_cast<std::ptrdiff_t>((i + 1) * samples));
        inflections_v = std::max(inflections_v, sign_changes(line));
    }
    const bool measured = std::isfinite(k_low);
    json.key("curvature").begin_object();
    json.key("samples_inside").integer(static_cast<long long>(inside_count));
    json.key("singular_samples").integer(static_cast<long long>(singular_count));
    json.key("principal_min").number(measured ? k_low : kNaN);
    json.key("principal_max").number(measured ? k_high : kNaN);
    json.key("gaussian_min").number(measured ? gaussian_low : kNaN);
    json.key("gaussian_max").number(measured ? gaussian_high : kNaN);
    json.key("minimum_radius").number(max_abs > 0.0 ? 1.0 / max_abs : kNaN);
    json.key("minimum_radius_point").point(max_abs_point);
    json.key("inflections_u").integer(inflections_u);
    json.key("inflections_v").integer(inflections_v);
    json.end_object();

    if (singular_count > 0) {
        issues.push_back({
            "info", "surface.singular_points",
            std::to_string(singular_count) + " sample(s) have an undefined normal "
                "(collapsed boundary or pole).",
            "Poles are expected on spheres and revolved apexes; elsewhere they cause "
            "shading and offset failures.",
        });
    }
    if (max_abs > 0.0 && diagonal > 0.0 && 1.0 / max_abs < 1.0e-3 * diagonal) {
        issues.push_back({
            "warning", "surface.tight_curvature",
            "Minimum curvature radius " + format_number(1.0 / max_abs)
                + " is below 0.1% of the face size.",
            "Very tight radii usually indicate a near-crease, a fold, or a bad pole; "
            "offsets and fillets thicker than the radius will fail.",
        });
    }
    if (std::max(inflections_u, inflections_v) >= 3) {
        issues.push_back({
            "warning", "surface.curvature_oscillation",
            "Normal curvature changes sign "
                + std::to_string(std::max(inflections_u, inflections_v))
                + " times along one isoparametric line.",
            "Repeated inflections are visible as waves in reflections; smooth or refit "
            "the surface.",
        });
    }

    json.key("issues").begin_array();
    for (const Issue& issue : issues) {
        write_issue(json, issue);
        if (std::strcmp(issue.severity, "info") != 0) {
            shape_issues.push_back({
                issue.severity, issue.code,
                "face " + std::to_string(face_index) + ": " + issue.message,
                issue.hint,
            });
        }
    }
    json.end_array();
    json.end_object();
}

#endif

#ifndef CADFLOW_WITH_OCCT
[[noreturn]] void require_occt() {
    throw std::runtime_error("surface analysis requires the OCCT native backend");
}
#endif

}  // namespace

std::string continuity_json(
    const core::Session& session,
    core::ShapeId id,
    std::size_t samples,
    const ContinuityTolerances& tolerances) {
    validate_tolerances(tolerances);
    validate_samples(samples);
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Shape& shape = core::get_shape(session, id).native;
    TopTools_IndexedMapOfShape edges;
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_EDGE, edges);
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    TopTools_IndexedDataMapOfShapeListOfShape ancestors;
    TopExp::MapShapesAndAncestors(shape, TopAbs_EDGE, TopAbs_FACE, ancestors);

    Json json;
    ContinuitySummary summary;
    std::size_t free_edges = 0;
    std::size_t seam_edges = 0;
    std::size_t degenerated_edges = 0;
    std::size_t non_manifold_edges = 0;

    json.begin_object();
    write_header(json, "shape", samples, tolerances);
    json.key("edges").begin_array();
    for (int edge_index = 1; edge_index <= edges.Extent(); ++edge_index) {
        const TopoDS_Edge edge = TopoDS::Edge(edges(edge_index));
        if (BRep_Tool::Degenerated(edge)) {
            ++degenerated_edges;
            continue;
        }
        std::vector<TopoDS_Face> adjacent;
        const int ancestor_index = ancestors.FindIndex(edge);
        if (ancestor_index > 0) {
            for (TopTools_ListOfShape::Iterator iterator(ancestors(ancestor_index));
                 iterator.More(); iterator.Next()) {
                const TopoDS_Face face = TopoDS::Face(iterator.Value());
                const bool known = std::any_of(
                    adjacent.begin(), adjacent.end(),
                    [&](const TopoDS_Face& other) { return other.IsSame(face); });
                if (!known) {
                    adjacent.push_back(face);
                }
            }
        }
        if (adjacent.size() == 1) {
            if (BRep_Tool::IsClosed(edge, adjacent.front())) {
                ++seam_edges;
            } else {
                ++free_edges;
            }
            continue;
        }
        if (adjacent.size() != 2) {
            if (adjacent.size() > 2) {
                ++non_manifold_edges;
            } else {
                ++free_edges;
            }
            continue;
        }
        const EdgeContinuity value = measure_boundary(
            adjacent[0], edge, adjacent[1], edge, true, samples, 0.0);
        summary.add(value, tolerances);
        json.begin_object();
        json.key("edge_index").integer(edge_index - 1);
        json.key("faces").begin_array()
            .integer(faces.FindIndex(adjacent[0]) - 1)
            .integer(faces.FindIndex(adjacent[1]) - 1)
            .end_array();
        json.key("shared").boolean(true);
        write_edge_metrics(json, value, tolerances);
        json.end_object();
    }
    json.end_array();
    json.key("summary").begin_object();
    summary.write(json);
    json.key("free").integer(static_cast<long long>(free_edges));
    json.key("seam").integer(static_cast<long long>(seam_edges));
    json.key("degenerated").integer(static_cast<long long>(degenerated_edges));
    json.key("non_manifold").integer(static_cast<long long>(non_manifold_edges));
    json.end_object();
    json.end_object();
    return json.str();
#else
    (void)session;
    (void)id;
    require_occt();
#endif
}

std::string face_pair_continuity_json(
    const core::Session& session,
    core::ShapeId face_a_id,
    core::ShapeId face_b_id,
    std::size_t samples,
    const ContinuityTolerances& tolerances) {
    validate_tolerances(tolerances);
    validate_samples(samples);
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Face face_a = require_face(core::get_shape(session, face_a_id).native);
    const TopoDS_Face face_b = require_face(core::get_shape(session, face_b_id).native);
    TopTools_IndexedMapOfShape edges_a;
    TopTools_IndexedMapOfShape edges_b;
    TopExp::MapShapes(face_a, TopAbs_EDGE, edges_a);
    TopExp::MapShapes(face_b, TopAbs_EDGE, edges_b);
    /* Geometric matching window: generous enough to report real G0 gaps,
       tight enough not to pair unrelated boundaries. */
    const double overlap = std::max(50.0 * tolerances.position, 1.0e-7);

    Json json;
    ContinuitySummary summary;
    json.begin_object();
    write_header(json, "face_pair", samples, tolerances);
    json.key("edges").begin_array();
    for (int index_a = 1; index_a <= edges_a.Extent(); ++index_a) {
        const TopoDS_Edge edge_a = TopoDS::Edge(edges_a(index_a));
        if (BRep_Tool::Degenerated(edge_a)) {
            continue;
        }
        const BRepAdaptor_Curve curve_a(edge_a);
        for (int index_b = 1; index_b <= edges_b.Extent(); ++index_b) {
            const TopoDS_Edge edge_b = TopoDS::Edge(edges_b(index_b));
            if (BRep_Tool::Degenerated(edge_b)) {
                continue;
            }
            const bool shared = edge_a.IsSame(edge_b);
            if (!shared) {
                const BRepAdaptor_Curve curve_b(edge_b);
                int near = 0;
                constexpr int probes = 9;
                for (int probe = 0; probe < probes; ++probe) {
                    const double t = curve_a.FirstParameter()
                        + (curve_a.LastParameter() - curve_a.FirstParameter())
                            * (0.05 + 0.9 * probe / (probes - 1));
                    double distance = 0.0;
                    closest_curve_parameter(curve_b, curve_a.Value(t), distance);
                    if (distance <= overlap) {
                        ++near;
                    }
                }
                if (near < 2) {
                    continue;
                }
            }
            const EdgeContinuity value = measure_boundary(
                face_a, edge_a, face_b, edge_b, shared, samples, overlap);
            if (value.valid_samples == 0) {
                continue;
            }
            summary.add(value, tolerances);
            json.begin_object();
            json.key("edge_a_index").integer(index_a - 1);
            json.key("edge_b_index").integer(index_b - 1);
            json.key("shared").boolean(shared);
            write_edge_metrics(json, value, tolerances);
            json.end_object();
        }
    }
    json.end_array();
    json.key("summary").begin_object();
    summary.write(json);
    json.end_object();
    json.end_object();
    return json.str();
#else
    (void)session;
    (void)face_a_id;
    (void)face_b_id;
    require_occt();
#endif
}

void curvature_samples(
    const core::Session& session,
    core::ShapeId face_id,
    std::size_t u_count,
    std::size_t v_count,
    cad_surface_sample_t* output) {
    if (!output) {
        throw std::invalid_argument("curvature sample output is null");
    }
    if (u_count < 2 || v_count < 2 || u_count > 4096 || v_count > 4096) {
        throw std::invalid_argument("curvature sample counts must be between 2 and 4096");
    }
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Face face = require_face(core::get_shape(session, face_id).native);
    const BRepAdaptor_Surface surface(face, true);
    const bool reversed = face.Orientation() == TopAbs_REVERSED;
    double u_min = 0.0;
    double u_max = 0.0;
    double v_min = 0.0;
    double v_max = 0.0;
    face_bounds(face, u_min, u_max, v_min, v_max);
    for (std::size_t i = 0; i < u_count; ++i) {
        const double u = u_min + (u_max - u_min) * static_cast<double>(i) / (u_count - 1);
        for (std::size_t j = 0; j < v_count; ++j) {
            const double v = v_min + (v_max - v_min) * static_cast<double>(j) / (v_count - 1);
            cad_surface_sample_t& sample = output[i * v_count + j];
            sample = cad_surface_sample_t {};
            sample.u = u;
            sample.v = v;
            sample.inside = inside_face(face, u, v) ? 1 : 0;
            const LocalGeometry geometry = evaluate(surface, reversed, u, v);
            copy_point(geometry.point, sample.point);
            const PrincipalCurvature curvature = principal_curvature(geometry);
            sample.singular = geometry.regular && std::isfinite(curvature.k_min) ? 0 : 1;
            if (sample.singular) {
                sample.normal[0] = sample.normal[1] = sample.normal[2] = kNaN;
                sample.principal_curvature_min = kNaN;
                sample.principal_curvature_max = kNaN;
                sample.mean_curvature = kNaN;
                sample.gaussian_curvature = kNaN;
                for (int axis = 0; axis < 3; ++axis) {
                    sample.direction_min[axis] = kNaN;
                    sample.direction_max[axis] = kNaN;
                }
                continue;
            }
            copy_vector(geometry.normal, sample.normal);
            sample.principal_curvature_min = curvature.k_min;
            sample.principal_curvature_max = curvature.k_max;
            sample.mean_curvature = curvature.mean;
            sample.gaussian_curvature = curvature.gaussian;
            copy_vector(curvature.direction_min, sample.direction_min);
            copy_vector(curvature.direction_max, sample.direction_max);
        }
    }
#else
    (void)session;
    (void)face_id;
    require_occt();
#endif
}

std::string curvature_mesh_buffer(
    const core::Session& session, core::ShapeId id, double deflection) {
    if (!(deflection > 0.0) || !std::isfinite(deflection)) {
        throw std::invalid_argument("curvature mesh deflection must be positive and finite");
    }
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Shape& shape = core::get_shape(session, id).native;
    /* A tight angular deflection keeps curved faces dense enough for
       reflection-line views even when the linear deflection is coarse. */
    BRepMesh_IncrementalMesh mesher(shape, deflection, false, 0.1, true);
    if (!mesher.IsDone()) {
        throw std::runtime_error("OCCT curvature tessellation failed");
    }
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);

    std::vector<float> positions;
    std::vector<float> normals;
    std::vector<float> curvature;
    std::vector<std::uint32_t> face_indices;
    std::vector<std::uint32_t> triangles;
    for (int face_index = 1; face_index <= faces.Extent(); ++face_index) {
        const TopoDS_Face face = TopoDS::Face(faces(face_index));
        TopLoc_Location location;
        const Handle(Poly_Triangulation) triangulation =
            BRep_Tool::Triangulation(face, location);
        if (triangulation.IsNull() || !triangulation->HasUVNodes()) {
            continue;
        }
        const BRepAdaptor_Surface surface(face, false);
        const bool reversed = face.Orientation() == TopAbs_REVERSED;
        double u_min = 0.0;
        double u_max = 0.0;
        double v_min = 0.0;
        double v_max = 0.0;
        BRepTools::UVBounds(face, u_min, u_max, v_min, v_max);
        const double u_center = 0.5 * (u_min + u_max);
        const double v_center = 0.5 * (v_min + v_max);
        const std::size_t base = positions.size() / 3;
        if (base + static_cast<std::size_t>(triangulation->NbNodes())
            > std::numeric_limits<std::uint32_t>::max()) {
            throw std::runtime_error("curvature mesh exceeds uint32 vertex indices");
        }
        for (int node = 1; node <= triangulation->NbNodes(); ++node) {
            const gp_Pnt point =
                triangulation->Node(node).Transformed(location.Transformation());
            const gp_Pnt2d uv = triangulation->UVNode(node);
            LocalGeometry geometry = evaluate(surface, reversed, uv.X(), uv.Y());
            PrincipalCurvature values = principal_curvature(geometry);
            gp_Vec normal = geometry.normal;
            if (!geometry.regular) {
                /* Borrow the normal just inside a pole; curvature stays NaN. */
                const LocalGeometry nudged = evaluate(
                    surface, reversed,
                    uv.X() + 1.0e-6 * (u_center - uv.X()),
                    uv.Y() + 1.0e-6 * (v_center - uv.Y()));
                normal = nudged.regular ? nudged.normal : gp_Vec(0.0, 0.0, 1.0);
                values = PrincipalCurvature {};
            }
            positions.insert(positions.end(), {
                static_cast<float>(point.X()),
                static_cast<float>(point.Y()),
                static_cast<float>(point.Z()),
            });
            normals.insert(normals.end(), {
                static_cast<float>(normal.X()),
                static_cast<float>(normal.Y()),
                static_cast<float>(normal.Z()),
            });
            curvature.insert(curvature.end(), {
                static_cast<float>(values.k_min),
                static_cast<float>(values.k_max),
                static_cast<float>(values.mean),
                static_cast<float>(values.gaussian),
            });
            face_indices.push_back(static_cast<std::uint32_t>(face_index - 1));
        }
        for (int index = 1; index <= triangulation->NbTriangles(); ++index) {
            int first = 0;
            int second = 0;
            int third = 0;
            triangulation->Triangle(index).Get(first, second, third);
            if (reversed) {
                std::swap(second, third);
            }
            triangles.insert(triangles.end(), {
                static_cast<std::uint32_t>(base + first - 1),
                static_cast<std::uint32_t>(base + second - 1),
                static_cast<std::uint32_t>(base + third - 1),
            });
        }
    }
    if (positions.empty() || triangles.empty()) {
        throw std::runtime_error("curvature mesh is empty; the shape has no faces");
    }
    const std::uint32_t header[4] = {
        0x41434643u,  // "CFCA" little-endian
        1u,
        static_cast<std::uint32_t>(positions.size() / 3),
        static_cast<std::uint32_t>(triangles.size() / 3),
    };
    std::string buffer;
    auto append = [&](const void* data, std::size_t bytes) {
        buffer.append(static_cast<const char*>(data), bytes);
    };
    append(header, sizeof(header));
    append(positions.data(), positions.size() * sizeof(float));
    append(normals.data(), normals.size() * sizeof(float));
    append(curvature.data(), curvature.size() * sizeof(float));
    append(face_indices.data(), face_indices.size() * sizeof(std::uint32_t));
    append(triangles.data(), triangles.size() * sizeof(std::uint32_t));
    return buffer;
#else
    (void)session;
    (void)id;
    require_occt();
#endif
}

std::string surface_quality_json(
    const core::Session& session,
    core::ShapeId id,
    std::size_t samples,
    bool check_self_intersection) {
    if (samples < 3 || samples > 512) {
        throw std::invalid_argument("surface quality samples must be between 3 and 512");
    }
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Shape& shape = core::get_shape(session, id).native;
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(shape, TopAbs_FACE, faces);
    if (faces.Extent() == 0) {
        throw std::invalid_argument("surface quality analysis requires at least one face");
    }
    std::vector<Issue> issues;
    Json json;
    json.begin_object();
    json.key("samples").integer(static_cast<long long>(samples));
    json.key("faces").begin_array();
    for (int index = 1; index <= faces.Extent(); ++index) {
        analyze_face_quality(
            json, TopoDS::Face(faces(index)), static_cast<std::size_t>(index - 1),
            samples, issues);
    }
    json.end_array();

    json.key("self_intersection");
    if (check_self_intersection) {
        BOPAlgo_ArgumentAnalyzer analyzer;
        analyzer.SetShape1(shape);
        analyzer.ArgumentTypeMode() = false;
        analyzer.SelfInterMode() = true;
        analyzer.SmallEdgeMode() = false;
        analyzer.RebuildFaceMode() = false;
        analyzer.TangentMode() = false;
        analyzer.MergeVertexMode() = false;
        analyzer.MergeEdgeMode() = false;
        analyzer.ContinuityMode() = false;
        analyzer.CurveOnSurfaceMode() = false;
        analyzer.Perform();
        int intersections = 0;
        for (BOPAlgo_ListIteratorOfListOfCheckResult iterator(analyzer.GetCheckResult());
             iterator.More(); iterator.Next()) {
            if (iterator.Value().GetCheckStatus() == BOPAlgo_SelfIntersect) {
                ++intersections;
            }
        }
        json.begin_object();
        json.key("checked").boolean(true);
        json.key("interfering_pairs").integer(intersections);
        json.end_object();
        if (intersections > 0) {
            issues.push_back({
                "error", "shape.self_intersection",
                std::to_string(intersections) + " pair(s) of sub-shapes intersect each other.",
                "Trim or rebuild the overlapping faces; booleans, offsets, and meshing "
                "are unreliable on self-intersecting shapes.",
            });
        }
    } else {
        json.null();
    }

    json.key("issues").begin_array();
    for (const Issue& issue : issues) {
        write_issue(json, issue);
    }
    json.end_array();
    json.end_object();
    return json.str();
#else
    (void)session;
    (void)id;
    (void)check_self_intersection;
    require_occt();
#endif
}

}  // namespace cadflow::analysis
