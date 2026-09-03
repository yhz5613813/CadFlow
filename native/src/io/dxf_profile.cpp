#include "io/dxf_profile.h"

#include <algorithm>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iterator>
#include <sstream>
#include <stdexcept>
#include <string>
#include <system_error>
#include <utility>
#include <vector>

#ifdef CADFLOW_WITH_OCCT
#include <BRepAdaptor_Surface.hxx>
#include <BRepTools.hxx>
#include <BRepTools_WireExplorer.hxx>
#include <BRep_Tool.hxx>
#include <Geom2dAdaptor_Curve.hxx>
#include <Geom2d_Curve.hxx>
#include <GeomAbs_CurveType.hxx>
#include <Precision.hxx>
#include <TopAbs.hxx>
#include <TopExp_Explorer.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <TopoDS_Shape.hxx>
#include <TopoDS_Wire.hxx>
#include <gp_Circ2d.hxx>
#include <gp_Pnt2d.hxx>
#endif

namespace cadflow::io {
namespace {

namespace fs = std::filesystem;

std::string lowercase_extension(const fs::path& path) {
    std::string extension = path.extension().string();
    std::transform(
        extension.begin(), extension.end(), extension.begin(),
        [](unsigned char value) { return static_cast<char>(std::tolower(value)); });
    return extension;
}

#ifdef CADFLOW_WITH_OCCT

std::string temporary_suffix() {
    static std::atomic<unsigned long long> sequence {0};
    const auto ticks = std::chrono::steady_clock::now().time_since_epoch().count();
    return ".cadflow-" + std::to_string(ticks) + "-"
        + std::to_string(sequence.fetch_add(1, std::memory_order_relaxed));
}

class TemporaryFile {
public:
    explicit TemporaryFile(fs::path path) : path_(std::move(path)) {}

    ~TemporaryFile() {
        if (!committed_) {
            std::error_code ignored;
            fs::remove(path_, ignored);
        }
    }

    const fs::path& path() const { return path_; }
    void committed() { committed_ = true; }

private:
    fs::path path_;
    bool committed_ {false};
};

void commit_file(TemporaryFile& temporary, const fs::path& output) {
    std::error_code error;
    fs::rename(temporary.path(), output, error);
    if (!error) {
        temporary.committed();
        return;
    }

    if (!fs::exists(output)) {
        throw std::runtime_error("failed to commit DXF output: " + error.message());
    }

    const fs::path backup = output.string() + temporary_suffix() + ".bak";
    error.clear();
    fs::rename(output, backup, error);
    if (error) {
        throw std::runtime_error("failed to replace existing DXF output: " + error.message());
    }

    error.clear();
    fs::rename(temporary.path(), output, error);
    if (error) {
        std::error_code restore_error;
        fs::rename(backup, output, restore_error);
        throw std::runtime_error("failed to commit DXF output: " + error.message());
    }
    temporary.committed();
    std::error_code ignored;
    fs::remove(backup, ignored);
}

constexpr double kPi = 3.141592653589793238462643383279502884;
constexpr int kMaxApproximationDepth = 24;
constexpr std::size_t kMaxProfileVertices = 100000;

struct DxfVertex {
    double x {0.0};
    double y {0.0};
    double bulge {0.0};
};

struct DxfLoop {
    std::string layer;
    std::vector<DxfVertex> vertices;
};

void require_finite(const gp_Pnt2d& point) {
    if (!std::isfinite(point.X()) || !std::isfinite(point.Y())) {
        throw std::runtime_error("DXF profile contains a non-finite coordinate");
    }
}

double point_segment_distance(
    const gp_Pnt2d& point, const gp_Pnt2d& start, const gp_Pnt2d& end) {
    const double dx = end.X() - start.X();
    const double dy = end.Y() - start.Y();
    const double length_squared = dx * dx + dy * dy;
    if (length_squared <= Precision::SquareConfusion()) {
        return point.Distance(start);
    }
    const double projection = std::clamp(
        ((point.X() - start.X()) * dx + (point.Y() - start.Y()) * dy)
            / length_squared,
        0.0,
        1.0);
    const gp_Pnt2d closest(
        start.X() + projection * dx,
        start.Y() + projection * dy);
    return point.Distance(closest);
}

bool interval_is_flat(
    const Handle(Geom2d_Curve)& curve,
    double first,
    double last,
    double tolerance) {
    const gp_Pnt2d start = curve->Value(first);
    const gp_Pnt2d end = curve->Value(last);
    require_finite(start);
    require_finite(end);
    for (const double fraction : {0.25, 0.5, 0.75}) {
        const gp_Pnt2d point = curve->Value(first + (last - first) * fraction);
        require_finite(point);
        if (point_segment_distance(point, start, end) > tolerance) {
            return false;
        }
    }
    return true;
}

void approximate_interval(
    const Handle(Geom2d_Curve)& curve,
    double first,
    double last,
    double tolerance,
    int depth,
    std::vector<gp_Pnt2d>& points) {
    if (points.size() > kMaxProfileVertices) {
        throw std::runtime_error("DXF profile exceeds the vertex safety limit");
    }
    if (interval_is_flat(curve, first, last, tolerance)) {
        points.push_back(curve->Value(last));
        return;
    }
    if (depth >= kMaxApproximationDepth) {
        throw std::runtime_error(
            "DXF curve approximation did not converge at the requested tolerance");
    }
    const double middle = first + (last - first) * 0.5;
    approximate_interval(curve, first, middle, tolerance, depth + 1, points);
    approximate_interval(curve, middle, last, tolerance, depth + 1, points);
}

std::pair<std::vector<DxfVertex>, gp_Pnt2d> edge_vertices(
    const TopoDS_Edge& edge,
    const TopoDS_Face& face,
    double tolerance) {
    double first = 0.0;
    double last = 0.0;
    Handle(Geom2d_Curve) curve = BRep_Tool::CurveOnSurface(edge, face, first, last);
    if (curve.IsNull()) {
        throw std::runtime_error("a profile edge has no curve on the selected face");
    }
    if (!std::isfinite(first) || !std::isfinite(last)) {
        throw std::runtime_error("a profile edge has an unbounded parameter range");
    }
    if (edge.Orientation() == TopAbs_REVERSED) {
        std::swap(first, last);
    }

    Geom2dAdaptor_Curve adaptor(curve);
    std::vector<DxfVertex> output;
    if (adaptor.GetType() == GeomAbs_Line) {
        const gp_Pnt2d start = curve->Value(first);
        const gp_Pnt2d end = curve->Value(last);
        require_finite(start);
        require_finite(end);
        output.push_back({start.X(), start.Y(), 0.0});
        return {std::move(output), end};
    }

    if (adaptor.GetType() == GeomAbs_Circle) {
        const gp_Circ2d circle = adaptor.Circle();
        const double parameter_sweep = last - first;
        const double signed_sweep = parameter_sweep * (circle.IsDirect() ? 1.0 : -1.0);
        const int segments = std::max(
            1,
            static_cast<int>(std::ceil(std::abs(signed_sweep) / (kPi / 2.0))));
        const double parameter_step = parameter_sweep / segments;
        const double bulge = std::tan((signed_sweep / segments) / 4.0);
        for (int index = 0; index < segments; ++index) {
            const gp_Pnt2d point = curve->Value(first + parameter_step * index);
            require_finite(point);
            output.push_back({point.X(), point.Y(), bulge});
        }
        const gp_Pnt2d end = curve->Value(last);
        require_finite(end);
        return {std::move(output), end};
    }

    std::vector<gp_Pnt2d> points {curve->Value(first)};
    require_finite(points.front());
    approximate_interval(curve, first, last, tolerance, 0, points);
    output.reserve(points.size() - 1);
    for (std::size_t index = 0; index + 1 < points.size(); ++index) {
        output.push_back({points[index].X(), points[index].Y(), 0.0});
    }
    return {std::move(output), points.back()};
}

bool points_are_close(const gp_Pnt2d& left, const gp_Pnt2d& right, double tolerance) {
    return left.SquareDistance(right) <= tolerance * tolerance;
}

DxfLoop extract_wire(
    const TopoDS_Wire& wire,
    const TopoDS_Face& face,
    std::string layer,
    double tolerance) {
    if (wire.IsNull()) {
        throw std::runtime_error("DXF profile face has a null boundary wire");
    }
    DxfLoop output {std::move(layer), {}};
    gp_Pnt2d first_point;
    gp_Pnt2d previous_end;
    bool has_edge = false;
    const double connection_tolerance = std::max(Precision::Confusion() * 10.0, tolerance * 1.0e-3);

    for (BRepTools_WireExplorer explorer(wire, face); explorer.More(); explorer.Next()) {
        const TopoDS_Edge edge = TopoDS::Edge(explorer.Current());
        if (BRep_Tool::Degenerated(edge)) {
            continue;
        }
        auto [vertices, end] = edge_vertices(edge, face, tolerance);
        if (vertices.empty()) {
            continue;
        }
        const gp_Pnt2d start(vertices.front().x, vertices.front().y);
        if (has_edge && !points_are_close(previous_end, start, connection_tolerance)) {
            throw std::runtime_error("DXF profile wire contains a disconnected edge");
        }
        if (!has_edge) {
            first_point = start;
        }
        output.vertices.insert(
            output.vertices.end(),
            std::make_move_iterator(vertices.begin()),
            std::make_move_iterator(vertices.end()));
        previous_end = end;
        has_edge = true;
    }

    if (!has_edge || output.vertices.size() < 2) {
        throw std::runtime_error("DXF profile wire has no exportable edges");
    }
    if (!points_are_close(previous_end, first_point, connection_tolerance)) {
        throw std::invalid_argument("DXF machining profile requires closed boundary wires");
    }
    if (output.vertices.size() > kMaxProfileVertices) {
        throw std::runtime_error("DXF profile exceeds the vertex safety limit");
    }
    return output;
}

std::vector<DxfLoop> extract_loops(const TopoDS_Face& face, double tolerance) {
    BRepAdaptor_Surface surface(face, true);
    if (surface.GetType() != GeomAbs_Plane) {
        throw std::invalid_argument("DXF machining profile requires a planar face");
    }

    const TopoDS_Wire outer = BRepTools::OuterWire(face);
    if (outer.IsNull()) {
        throw std::runtime_error("DXF profile face has no outer boundary");
    }
    std::vector<DxfLoop> loops;
    loops.push_back(extract_wire(outer, face, "PROFILE_OUTER", tolerance));
    for (TopExp_Explorer explorer(face, TopAbs_WIRE); explorer.More(); explorer.Next()) {
        const TopoDS_Wire wire = TopoDS::Wire(explorer.Current());
        if (!wire.IsSame(outer)) {
            loops.push_back(extract_wire(wire, face, "PROFILE_INNER", tolerance));
        }
    }
    return loops;
}

template <typename Value>
void pair(std::ostream& output, int code, const Value& value) {
    output << code << '\n' << value << '\n';
}

void write_layer(
    std::ostream& output,
    const char* handle,
    const char* table_handle,
    const char* name,
    int color) {
    pair(output, 0, "LAYER");
    pair(output, 5, handle);
    pair(output, 330, table_handle);
    pair(output, 100, "AcDbSymbolTableRecord");
    pair(output, 100, "AcDbLayerTableRecord");
    pair(output, 2, name);
    pair(output, 70, 0);
    pair(output, 62, color);
    pair(output, 6, "CONTINUOUS");
}

std::string make_dxf(const std::vector<DxfLoop>& loops, double tolerance) {
    std::ostringstream output;
    output << std::setprecision(17);
    pair(output, 999, "CadFlow planar machining profile");
    pair(output, 999, "Non-line/non-circle chord tolerance: " + std::to_string(tolerance) + " mm");
    pair(output, 0, "SECTION");
    pair(output, 2, "HEADER");
    pair(output, 9, "$ACADVER");
    pair(output, 1, "AC1015");
    pair(output, 9, "$INSUNITS");
    pair(output, 70, 4);
    pair(output, 9, "$MEASUREMENT");
    pair(output, 70, 1);
    pair(output, 0, "ENDSEC");

    pair(output, 0, "SECTION");
    pair(output, 2, "TABLES");
    pair(output, 0, "TABLE");
    pair(output, 2, "LAYER");
    pair(output, 5, "1");
    pair(output, 330, "0");
    pair(output, 100, "AcDbSymbolTable");
    pair(output, 70, 2);
    write_layer(output, "2", "1", "PROFILE_OUTER", 7);
    write_layer(output, "3", "1", "PROFILE_INNER", 1);
    pair(output, 0, "ENDTAB");
    pair(output, 0, "ENDSEC");

    pair(output, 0, "SECTION");
    pair(output, 2, "ENTITIES");
    for (const DxfLoop& loop : loops) {
        pair(output, 0, "LWPOLYLINE");
        pair(output, 100, "AcDbEntity");
        pair(output, 8, loop.layer);
        pair(output, 100, "AcDbPolyline");
        pair(output, 90, loop.vertices.size());
        pair(output, 70, 1);
        for (const DxfVertex& vertex : loop.vertices) {
            pair(output, 10, vertex.x);
            pair(output, 20, vertex.y);
            if (std::abs(vertex.bulge) > 1.0e-15) {
                pair(output, 42, vertex.bulge);
            }
        }
    }
    pair(output, 0, "ENDSEC");
    pair(output, 0, "EOF");
    return output.str();
}

#endif

}  // namespace

void export_dxf_profile(
    const core::Session& session,
    core::ShapeId id,
    const std::string& path,
    double tolerance) {
    if (path.empty()) {
        throw std::invalid_argument("DXF path is empty");
    }
    if (!std::isfinite(tolerance) || tolerance <= 0.0) {
        throw std::invalid_argument("DXF curve tolerance must be finite and positive");
    }
    const fs::path output = fs::absolute(path);
    if (lowercase_extension(output) != ".dxf") {
        throw std::invalid_argument("DXF export path must end with .dxf");
    }
    if (!fs::is_directory(output.parent_path())) {
        throw std::invalid_argument("DXF output directory does not exist");
    }

#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Shape& shape = core::get_shape(session, id).native;
    if (shape.IsNull() || shape.ShapeType() != TopAbs_FACE) {
        throw std::invalid_argument("DXF machining profile input must be one planar face");
    }
    const std::string contents = make_dxf(extract_loops(TopoDS::Face(shape), tolerance), tolerance);
    TemporaryFile temporary(output.string() + temporary_suffix() + ".tmp");
    std::ofstream stream(temporary.path(), std::ios::binary | std::ios::trunc);
    if (!stream) {
        throw std::runtime_error("failed to create temporary DXF output");
    }
    stream.write(contents.data(), static_cast<std::streamsize>(contents.size()));
    stream.close();
    if (!stream) {
        throw std::runtime_error("failed to write DXF output");
    }
    commit_file(temporary, output);
#else
    (void)session;
    (void)id;
    throw std::runtime_error("DXF profile export requires the OCCT backend");
#endif
}

}  // namespace cadflow::io
