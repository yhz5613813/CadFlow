#include "runtime/graph.h"

#include "kernel/construction.h"
#include "kernel/advanced.h"
#include "kernel/edge_features.h"
#include "kernel/features.h"
#include "kernel/operations.h"
#include "kernel/queries.h"
#include "kernel/surfaces.h"

#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

namespace cadflow::runtime {
namespace {

using core::Shape;
using core::ShapeId;

template <typename... Values>
void read_values(std::istringstream& row, const std::string& error, Values&... values) {
    if (!(row >> ... >> values)) {
        throw std::invalid_argument(error);
    }
}

ShapeId resolve_id(const std::string& token, const std::vector<ShapeId>& results) {
    if (!token.empty() && token.front() == '$') {
        const std::size_t index = std::stoull(token.substr(1));
        if (index >= results.size() || results[index] == 0) {
            throw std::invalid_argument("graph reference is not a shape: " + token);
        }
        return results[index];
    }
    return std::stoull(token);
}

void emit_shape(ShapeId id, std::vector<ShapeId>& results, std::ostringstream& output) {
    results.push_back(id);
    output << id << '\n';
}

}  // namespace

std::string execute_graph(core::Session& session, const std::string& program) {
    std::istringstream input(program);
    std::ostringstream output;
    output << std::setprecision(17);
    std::vector<ShapeId> results;

    std::string line;
    while (std::getline(input, line)) {
        std::istringstream row(line);
        std::string operation;
        if (!(row >> operation) || operation.front() == '#') {
            continue;
        }

        if (operation == "box") {
            double width;
            double depth;
            double height;
            read_values(row, "box expects 3 numbers", width, depth, height);
            emit_shape(kernel::make_box(session, width, depth, height), results, output);
        } else if (operation == "cylinder") {
            double radius;
            double height;
            read_values(row, "cylinder expects 2 numbers", radius, height);
            emit_shape(kernel::make_cylinder(session, radius, height), results, output);
        } else if (operation == "sphere") {
            double radius;
            read_values(row, "sphere expects a radius", radius);
            emit_shape(kernel::make_sphere(session, radius), results, output);
        } else if (operation == "cone") {
            double radius1;
            double radius2;
            double height;
            read_values(row, "cone expects 3 numbers", radius1, radius2, height);
            emit_shape(kernel::make_cone(session, radius1, radius2, height), results, output);
        } else if (operation == "polyline") {
            int closed;
            std::size_t count;
            read_values(row, "polyline expects closed flag and point count", closed, count);
            std::vector<double> points(count * 3);
            for (double& value : points) {
                read_values(row, "polyline point data is incomplete", value);
            }
            emit_shape(
                kernel::make_polyline(session, points.data(), count, closed != 0),
                results,
                output);
        } else if (operation == "circle_profile") {
            double radius;
            double cx;
            double cy;
            double cz;
            double nx;
            double ny;
            double nz;
            read_values(
                row,
                "circle_profile expects radius, center, and normal",
                radius,
                cx,
                cy,
                cz,
                nx,
                ny,
                nz);
            emit_shape(
                kernel::make_circle_profile(session, cx, cy, cz, nx, ny, nz, radius),
                results,
                output);
        } else if (operation == "arc") {
            double points[9];
            for (double& value : points) {
                read_values(row, "arc expects three 3D points", value);
            }
            emit_shape(kernel::make_arc(session, points), results, output);
        } else if (operation == "interpolate") {
            int periodic;
            double tolerance;
            std::size_t count;
            read_values(
                row,
                "interpolate expects periodic flag, tolerance, and point count",
                periodic,
                tolerance,
                count);
            std::vector<double> points(count * 3);
            for (double& value : points) {
                read_values(row, "interpolation point data is incomplete", value);
            }
            emit_shape(
                kernel::make_interpolated_curve(
                    session, points.data(), count, periodic != 0, tolerance),
                results,
                output);
        } else if (operation == "helix") {
            double pitch;
            double height;
            double radius;
            double cx;
            double cy;
            double cz;
            double dx;
            double dy;
            double dz;
            read_values(
                row,
                "helix expects pitch, height, radius, center, and direction",
                pitch,
                height,
                radius,
                cx,
                cy,
                cz,
                dx,
                dy,
                dz);
            emit_shape(
                kernel::make_helix(
                    session, pitch, height, radius, cx, cy, cz, dx, dy, dz),
                results,
                output);
        } else if (operation == "import_brep" || operation == "import_stl") {
            std::string path;
            read_values(row, operation + " expects a path", path);
            emit_shape(
                operation == "import_brep" ? kernel::import_brep(session, path.c_str())
                                            : kernel::import_stl(session, path.c_str()),
                results, output);
        } else if (operation == "face") {
            std::string profile;
            read_values(row, "face expects a wire handle", profile);
            emit_shape(kernel::make_face(session, resolve_id(profile, results)), results, output);
        } else if (operation == "bezier_surface") {
            std::size_t rows;
            std::size_t columns;
            int weighted;
            read_values(
                row,
                "bezier_surface expects rows, columns, and weight flag",
                rows,
                columns,
                weighted);
            std::vector<double> points(rows * columns * 3);
            for (double& value : points) {
                read_values(row, "Bezier surface point data is incomplete", value);
            }
            std::vector<double> weights;
            if (weighted) {
                weights.resize(rows * columns);
                for (double& value : weights) {
                    read_values(row, "Bezier surface weight data is incomplete", value);
                }
            }
            emit_shape(
                kernel::make_bezier_surface(
                    session,
                    points.data(),
                    rows,
                    columns,
                    weights.empty() ? nullptr : weights.data()),
                results,
                output);
        } else if (operation == "fit_surface") {
            std::size_t rows;
            std::size_t columns;
            double tolerance;
            int degree_min;
            int degree_max;
            read_values(
                row,
                "fit_surface expects dimensions, tolerance, and degrees",
                rows,
                columns,
                tolerance,
                degree_min,
                degree_max);
            std::vector<double> points(rows * columns * 3);
            for (double& value : points) {
                read_values(row, "surface fitting point data is incomplete", value);
            }
            emit_shape(
                kernel::fit_point_grid_surface(
                    session,
                    points.data(),
                    rows,
                    columns,
                    tolerance,
                    degree_min,
                    degree_max),
                results,
                output);
        } else if (operation == "extrude") {
            std::string profile;
            double x;
            double y;
            double z;
            read_values(row, "extrude expects profile handle and vector", profile, x, y, z);
            emit_shape(
                kernel::extrude(session, resolve_id(profile, results), x, y, z),
                results,
                output);
        } else if (operation == "revolve") {
            std::string profile;
            double ox;
            double oy;
            double oz;
            double ax;
            double ay;
            double az;
            double degrees;
            read_values(
                row,
                "revolve expects profile handle, origin, axis, and degrees",
                profile,
                ox,
                oy,
                oz,
                ax,
                ay,
                az,
                degrees);
            emit_shape(
                kernel::revolve(
                    session,
                    resolve_id(profile, results),
                    ox,
                    oy,
                    oz,
                    ax,
                    ay,
                    az,
                    degrees),
                results,
                output);
        } else if (operation == "fillet" || operation == "chamfer") {
            std::string source;
            double size;
            std::size_t count;
            read_values(
                row,
                operation + " expects a shape, size, and edge count",
                source,
                size,
                count);
            std::vector<std::size_t> indices(count);
            for (std::size_t& index : indices) {
                read_values(row, operation + " edge index data is incomplete", index);
            }
            const ShapeId source_id = resolve_id(source, results);
            const std::size_t* selected = indices.empty() ? nullptr : indices.data();
            const ShapeId result = operation == "fillet"
                ? kernel::fillet(session, source_id, size, selected, indices.size())
                : kernel::chamfer(session, source_id, size, selected, indices.size());
            emit_shape(result, results, output);
        } else if (operation == "shell") {
            std::string source;
            double thickness;
            double tolerance;
            std::size_t count;
            read_values(
                row,
                "shell expects a shape, thickness, tolerance, and face count",
                source,
                thickness,
                tolerance,
                count);
            std::vector<std::size_t> indices(count);
            for (std::size_t& index : indices) {
                read_values(row, "shell face index data is incomplete", index);
            }
            emit_shape(
                kernel::shell(
                    session,
                    resolve_id(source, results),
                    thickness,
                    indices.empty() ? nullptr : indices.data(),
                    indices.size(),
                    tolerance),
                results,
                output);
        } else if (operation == "loft") {
            int solid;
            int ruled;
            std::size_t count;
            read_values(row, "loft expects flags and profile count", solid, ruled, count);
            std::vector<ShapeId> profiles(count);
            for (ShapeId& profile : profiles) {
                std::string token;
                read_values(row, "loft profile data is incomplete", token);
                profile = resolve_id(token, results);
            }
            emit_shape(
                kernel::loft(
                    session, profiles.data(), profiles.size(), solid != 0, ruled != 0),
                results,
                output);
        } else if (operation == "sweep") {
            std::string profile;
            std::string path;
            int solid;
            int frenet;
            read_values(
                row, "sweep expects profile, path, and flags", profile, path, solid, frenet);
            emit_shape(
                kernel::sweep(
                    session,
                    resolve_id(profile, results),
                    resolve_id(path, results),
                    solid != 0,
                    frenet != 0),
                results,
                output);
        } else if (operation == "bspline") {
            std::size_t pole_count;
            int degree;
            std::size_t knot_count;
            std::size_t multiplicity_count;
            int weighted;
            int periodic;
            read_values(row, "bspline expects pole count, degree, knot count, multiplicity count, weight flag, and periodic flag", pole_count, degree, knot_count, multiplicity_count, weighted, periodic);
            std::vector<double> poles(pole_count * 3);
            for (double& value : poles) read_values(row, "bspline pole data is incomplete", value);
            std::vector<double> knots(knot_count);
            for (double& value : knots) read_values(row, "bspline knot data is incomplete", value);
            std::vector<int> mults(multiplicity_count);
            for (int& value : mults) read_values(row, "bspline multiplicity data is incomplete", value);
            std::vector<double> weights;
            if (weighted) {
                weights.resize(pole_count);
                for (double& value : weights) read_values(row, "bspline weight data is incomplete", value);
            }
            emit_shape(kernel::make_bspline(session, poles.data(), pole_count, degree, knots.data(), knot_count, mults.data(), mults.size(), weights.empty() ? nullptr : weights.data(), periodic != 0), results, output);
        } else if (operation == "twisted_sweep") {
            std::string profile;
            double distance, twist, ox, oy, oz, ax, ay, az, radius;
            read_values(row, "twisted_sweep expects profile, distance, twist, origin, axis, and guide radius", profile, distance, twist, ox, oy, oz, ax, ay, az, radius);
            emit_shape(kernel::twisted_sweep(session, resolve_id(profile, results), distance, twist, ox, oy, oz, ax, ay, az, radius), results, output);
        } else if (operation == "ruled_surface") {
            std::string a, b;
            read_values(row, "ruled_surface expects two wires", a, b);
            emit_shape(kernel::ruled_surface(session, resolve_id(a, results), resolve_id(b, results)), results, output);
        } else if (operation == "filling_surface" || operation == "sew") {
            double tolerance;
            std::size_t count;
            read_values(row, operation + " expects tolerance and count", tolerance, count);
            std::vector<ShapeId> ids(count);
            for (ShapeId& id : ids) { std::string token; read_values(row, operation + " input data is incomplete", token); id = resolve_id(token, results); }
            emit_shape(operation == "sew" ? kernel::sew(session, ids.data(), ids.size(), tolerance) : kernel::filling_surface(session, ids.data(), ids.size(), tolerance), results, output);
        } else if (operation == "gordon_surface") {
            double tolerance;
            std::size_t profile_count, guide_count;
            read_values(row, "gordon_surface expects tolerance and profile/guide counts", tolerance, profile_count, guide_count);
            std::vector<ShapeId> profiles(profile_count), guides(guide_count);
            for (ShapeId& id : profiles) { std::string token; read_values(row, "Gordon profile data is incomplete", token); id = resolve_id(token, results); }
            for (ShapeId& id : guides) { std::string token; read_values(row, "Gordon guide data is incomplete", token); id = resolve_id(token, results); }
            emit_shape(kernel::gordon_surface(session, profiles.data(), profiles.size(), guides.data(), guides.size(), tolerance), results, output);
        } else if (operation == "shell_to_solid") {
            std::string shell;
            read_values(row, "shell_to_solid expects a shell", shell);
            emit_shape(kernel::shell_to_solid(session, resolve_id(shell, results)), results, output);
        } else if (
            operation == "cut" || operation == "union" || operation == "intersect") {
            std::string left;
            std::string right;
            read_values(row, operation + " expects 2 handles", left, right);
            const Shape::Kind kind = operation == "cut"
                ? Shape::Kind::Cut
                : (operation == "union" ? Shape::Kind::Union : Shape::Kind::Intersect);
            emit_shape(
                kernel::boolean_operation(
                    session, kind, resolve_id(left, results), resolve_id(right, results)),
                results,
                output);
        } else if (operation == "translate") {
            std::string source;
            double x;
            double y;
            double z;
            read_values(row, "translate expects handle and 3 numbers", source, x, y, z);
            emit_shape(
                kernel::translate(session, resolve_id(source, results), x, y, z),
                results,
                output);
        } else if (operation == "rotate") {
            std::string source;
            double ox;
            double oy;
            double oz;
            double ax;
            double ay;
            double az;
            double degrees;
            read_values(
                row,
                "rotate expects handle, origin, axis, and degrees",
                source,
                ox,
                oy,
                oz,
                ax,
                ay,
                az,
                degrees);
            emit_shape(
                kernel::rotate(
                    session,
                    resolve_id(source, results),
                    ox,
                    oy,
                    oz,
                    ax,
                    ay,
                    az,
                    degrees),
                results,
                output);
        } else if (operation == "mirror") {
            std::string source;
            double ox;
            double oy;
            double oz;
            double nx;
            double ny;
            double nz;
            read_values(
                row,
                "mirror expects handle, origin, and normal",
                source,
                ox,
                oy,
                oz,
                nx,
                ny,
                nz);
            emit_shape(
                kernel::mirror(
                    session, resolve_id(source, results), ox, oy, oz, nx, ny, nz),
                results,
                output);
        } else if (operation == "scale") {
            std::string source;
            double cx;
            double cy;
            double cz;
            double factor;
            read_values(
                row, "scale expects handle, center, and factor", source, cx, cy, cz, factor);
            emit_shape(
                kernel::scale(session, resolve_id(source, results), cx, cy, cz, factor),
                results,
                output);
        } else if (operation == "distance") {
            std::string left;
            std::string right;
            read_values(row, "distance expects 2 handles", left, right);
            output << kernel::distance(
                          session, resolve_id(left, results), resolve_id(right, results))
                   << '\n';
            results.push_back(0);
        } else if (
            operation == "volume" || operation == "area" || operation == "length"
            || operation == "center" || operation == "kind" || operation == "bbox") {
            std::string source;
            read_values(row, operation + " expects a handle", source);
            const ShapeId id = resolve_id(source, results);
            if (operation == "volume") {
                output << kernel::volume(session, id) << '\n';
            } else if (operation == "area") {
                output << kernel::area(session, id) << '\n';
            } else if (operation == "length") {
                output << kernel::length(session, id) << '\n';
            } else if (operation == "center") {
                double center[3];
                kernel::center_of_mass(session, id, center);
                output << center[0] << ' ' << center[1] << ' ' << center[2] << '\n';
            } else if (operation == "kind") {
                output << kernel::kind(core::get_shape(session, id)) << '\n';
            } else {
                const core::Box3 box = kernel::bounding_box(session, id);
                output << box.min[0] << ' ' << box.min[1] << ' ' << box.min[2] << ' '
                       << box.max[0] << ' ' << box.max[1] << ' ' << box.max[2] << '\n';
            }
            results.push_back(0);
        } else {
            throw std::invalid_argument("unknown graph op: " + operation);
        }
    }
    return output.str();
}

}  // namespace cadflow::runtime
