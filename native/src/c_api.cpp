#include "cadflow_core.h"

#include "core/session.h"
#include "flexible/shell_mesh.h"
#include "io/exchange.h"
#include "kernel/construction.h"
#include "kernel/advanced.h"
#include "kernel/edge_features.h"
#include "kernel/features.h"
#include "kernel/operations.h"
#include "kernel/queries.h"
#include "kernel/surfaces.h"
#include "physics/connections.h"
#include "runtime/graph.h"

#include <cstdlib>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>

namespace {

using cadflow::core::Session;
using cadflow::core::Shape;

template <typename Function>
auto with_session(cad_session_t handle, Function&& function) -> decltype(function(
    std::declval<Session&>())) {
    Session& session = cadflow::core::as_session(handle);
    std::lock_guard<std::mutex> lock(session.mutex);
    return function(session);
}

}  // namespace

extern "C" {

const char* cadflow_version(void) {
#ifdef CADFLOW_WITH_OCCT
    return "cadflow-core/0.3-occt-7.9.3";
#else
    return "cadflow-core/0.3-analytic";
#endif
}

cad_session_t cadflow_session_create(void) {
    return cadflow::core::guarded([]() -> cad_session_t { return new Session(); });
}

void cadflow_session_destroy(cad_session_t handle) {
    try {
        delete static_cast<Session*>(handle);
    } catch (...) {
        // Session destruction is a C ABI noexcept boundary.
    }
}

unsigned long long cadflow_box(
    cad_session_t handle, double width, double depth, double height) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_box(session, width, depth, height);
        });
    });
}

unsigned long long cadflow_cylinder(cad_session_t handle, double radius, double height) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_cylinder(session, radius, height);
        });
    });
}

unsigned long long cadflow_sphere(cad_session_t handle, double radius) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_sphere(session, radius);
        });
    });
}

unsigned long long cadflow_cone(
    cad_session_t handle, double radius1, double radius2, double height) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_cone(session, radius1, radius2, height);
        });
    });
}

unsigned long long cadflow_import_step(cad_session_t handle, const char* path) {
    return cadflow::core::guarded([&] {
        if (!path) {
            throw std::invalid_argument("STEP path is null");
        }
        return with_session(handle, [&](Session& session) {
            return cadflow::io::import_step(session, path);
        });
    });
}

unsigned long long cadflow_import_brep(cad_session_t handle, const char* path) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::import_brep(session, path);
        });
    });
}

unsigned long long cadflow_import_stl(cad_session_t handle, const char* path) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::import_stl(session, path);
        });
    });
}

unsigned long long cadflow_polyline(
    cad_session_t handle, const double* xyz, size_t point_count, int closed) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_polyline(
                session, xyz, point_count, closed != 0);
        });
    });
}

unsigned long long cadflow_circle_profile(
    cad_session_t handle,
    double cx,
    double cy,
    double cz,
    double nx,
    double ny,
    double nz,
    double radius) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_circle_profile(
                session, cx, cy, cz, nx, ny, nz, radius);
        });
    });
}

unsigned long long cadflow_arc(cad_session_t handle, const double points_xyz[9]) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_arc(session, points_xyz);
        });
    });
}

unsigned long long cadflow_interpolate(
    cad_session_t handle,
    const double* xyz,
    size_t point_count,
    int periodic,
    double tolerance) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_interpolated_curve(
                session, xyz, point_count, periodic != 0, tolerance);
        });
    });
}

unsigned long long cadflow_helix(
    cad_session_t handle,
    double pitch,
    double height,
    double radius,
    double cx,
    double cy,
    double cz,
    double dx,
    double dy,
    double dz) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_helix(
                session, pitch, height, radius, cx, cy, cz, dx, dy, dz);
        });
    });
}

unsigned long long cadflow_face(cad_session_t handle, unsigned long long wire) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_face(session, wire);
        });
    });
}

unsigned long long cadflow_bezier_surface(
    cad_session_t handle,
    const double* xyz,
    size_t rows,
    size_t columns,
    const double* weights) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_bezier_surface(
                session, xyz, rows, columns, weights);
        });
    });
}

unsigned long long cadflow_fit_surface(
    cad_session_t handle,
    const double* xyz,
    size_t rows,
    size_t columns,
    double tolerance,
    int degree_min,
    int degree_max) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::fit_point_grid_surface(
                session, xyz, rows, columns, tolerance, degree_min, degree_max);
        });
    });
}

unsigned long long cadflow_extrude(
    cad_session_t handle,
    unsigned long long profile,
    double x,
    double y,
    double z) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::extrude(session, profile, x, y, z);
        });
    });
}

unsigned long long cadflow_revolve(
    cad_session_t handle,
    unsigned long long profile,
    double ox,
    double oy,
    double oz,
    double ax,
    double ay,
    double az,
    double degrees) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::revolve(
                session, profile, ox, oy, oz, ax, ay, az, degrees);
        });
    });
}

unsigned long long cadflow_fillet(
    cad_session_t handle,
    unsigned long long shape,
    double radius,
    const size_t* edge_indices,
    size_t edge_count) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::fillet(
                session, shape, radius, edge_indices, edge_count);
        });
    });
}

unsigned long long cadflow_chamfer(
    cad_session_t handle,
    unsigned long long shape,
    double distance,
    const size_t* edge_indices,
    size_t edge_count) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::chamfer(
                session, shape, distance, edge_indices, edge_count);
        });
    });
}

unsigned long long cadflow_shell(
    cad_session_t handle,
    unsigned long long shape,
    double thickness,
    const size_t* face_indices,
    size_t face_count,
    double tolerance) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::shell(
                session, shape, thickness, face_indices, face_count, tolerance);
        });
    });
}

unsigned long long cadflow_loft(
    cad_session_t handle,
    const unsigned long long* profiles,
    size_t profile_count,
    int solid,
    int ruled) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::loft(
                session, profiles, profile_count, solid != 0, ruled != 0);
        });
    });
}

unsigned long long cadflow_sweep(
    cad_session_t handle,
    unsigned long long profile,
    unsigned long long path,
    int solid,
    int frenet) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::sweep(
                session, profile, path, solid != 0, frenet != 0);
        });
    });
}

unsigned long long cadflow_bspline(
    cad_session_t handle, const double* poles_xyz, size_t pole_count, int degree,
    const double* knots, size_t knot_count, const int* multiplicities,
    size_t multiplicity_count, const double* weights, int periodic) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::make_bspline(
                session, poles_xyz, pole_count, degree, knots, knot_count,
                multiplicities, multiplicity_count, weights, periodic != 0);
        });
    });
}

unsigned long long cadflow_twisted_sweep(
    cad_session_t handle, unsigned long long profile, double distance,
    double twist_degrees, double ox, double oy, double oz, double ax, double ay,
    double az, double guide_radius) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::twisted_sweep(
                session, profile, distance, twist_degrees, ox, oy, oz, ax, ay, az,
                guide_radius);
        });
    });
}

unsigned long long cadflow_ruled_surface(
    cad_session_t handle, unsigned long long edge_a, unsigned long long edge_b) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::ruled_surface(session, edge_a, edge_b);
        });
    });
}

unsigned long long cadflow_filling_surface(
    cad_session_t handle, const unsigned long long* edges, size_t edge_count,
    double tolerance) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::filling_surface(session, edges, edge_count, tolerance);
        });
    });
}

unsigned long long cadflow_gordon_surface(
    cad_session_t handle, const unsigned long long* profiles, size_t profile_count,
    const unsigned long long* guides, size_t guide_count, double tolerance) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::gordon_surface(
                session, profiles, profile_count, guides, guide_count, tolerance);
        });
    });
}

unsigned long long cadflow_sew(
    cad_session_t handle, const unsigned long long* faces, size_t face_count,
    double tolerance) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::sew(session, faces, face_count, tolerance);
        });
    });
}

unsigned long long cadflow_shell_to_solid(cad_session_t handle, unsigned long long shell) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::shell_to_solid(session, shell);
        });
    });
}

unsigned long long cadflow_cut(
    cad_session_t handle, unsigned long long left, unsigned long long right) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::boolean_operation(
                session, Shape::Kind::Cut, left, right);
        });
    });
}

unsigned long long cadflow_union(
    cad_session_t handle, unsigned long long left, unsigned long long right) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::boolean_operation(
                session, Shape::Kind::Union, left, right);
        });
    });
}

unsigned long long cadflow_intersect(
    cad_session_t handle, unsigned long long left, unsigned long long right) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::boolean_operation(
                session, Shape::Kind::Intersect, left, right);
        });
    });
}

unsigned long long cadflow_translate(
    cad_session_t handle, unsigned long long shape, double x, double y, double z) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::translate(session, shape, x, y, z);
        });
    });
}

unsigned long long cadflow_rotate(
    cad_session_t handle,
    unsigned long long shape,
    double ox,
    double oy,
    double oz,
    double ax,
    double ay,
    double az,
    double degrees) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::rotate(
                session, shape, ox, oy, oz, ax, ay, az, degrees);
        });
    });
}

unsigned long long cadflow_mirror(
    cad_session_t handle,
    unsigned long long shape,
    double ox,
    double oy,
    double oz,
    double nx,
    double ny,
    double nz) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::mirror(session, shape, ox, oy, oz, nx, ny, nz);
        });
    });
}

unsigned long long cadflow_scale(
    cad_session_t handle,
    unsigned long long shape,
    double cx,
    double cy,
    double cz,
    double factor) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::scale(session, shape, cx, cy, cz, factor);
        });
    });
}

double cadflow_volume(cad_session_t handle, unsigned long long shape) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::volume(session, shape);
        });
    });
}

double cadflow_area(cad_session_t handle, unsigned long long shape) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::area(session, shape);
        });
    });
}

double cadflow_length(cad_session_t handle, unsigned long long shape) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::length(session, shape);
        });
    });
}

double cadflow_distance(
    cad_session_t handle, unsigned long long left, unsigned long long right) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::distance(session, left, right);
        });
    });
}

int cadflow_center_of_mass(
    cad_session_t handle, unsigned long long shape, double output[3]) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            cadflow::kernel::center_of_mass(session, shape, output);
            return 1;
        });
    });
}

int cadflow_bbox(cad_session_t handle, unsigned long long shape, double output[6]) {
    return cadflow::core::guarded([&] {
        if (!output) {
            throw std::invalid_argument("bbox output is null");
        }
        return with_session(handle, [&](Session& session) {
            const cadflow::core::Box3 box = cadflow::kernel::bounding_box(session, shape);
            for (int axis = 0; axis < 3; ++axis) {
                output[axis] = box.min[axis];
                output[axis + 3] = box.max[axis];
            }
            return 1;
        });
    });
}

int cadflow_topology_counts(
    cad_session_t handle, unsigned long long shape, unsigned long long output[4]) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            cadflow::kernel::topology_counts(session, shape, output);
            return 1;
        });
    });
}

size_t cadflow_subshape_count(
    cad_session_t handle, unsigned long long shape, int shape_type) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::subshape_count(session, shape, shape_type);
        });
    });
}

size_t cadflow_subshape_handles(
    cad_session_t handle, unsigned long long shape, int shape_type,
    unsigned long long* output, size_t capacity) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::subshape_handles(
                session, shape, shape_type, output, capacity);
        });
    });
}

size_t cadflow_free_boundary_count(
    cad_session_t handle, unsigned long long shape, double tolerance) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::free_boundary_count(session, shape, tolerance);
        });
    });
}

size_t cadflow_free_boundary_handles(
    cad_session_t handle, unsigned long long shape, double tolerance,
    unsigned long long* output, size_t capacity) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::free_boundary_handles(
                session, shape, tolerance, output, capacity);
        });
    });
}

int cadflow_face_properties(
    cad_session_t handle, unsigned long long face, double u, double v,
    double normal_out[3], double curvature_out[3]) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            cadflow::kernel::face_properties(
                session, face, u, v, normal_out, curvature_out);
            return 1;
        });
    });
}

const char* cadflow_kind(cad_session_t handle, unsigned long long shape) {
    return cadflow::core::guarded([&] {
        return with_session(handle, [&](Session& session) {
            return cadflow::kernel::kind(cadflow::core::get_shape(session, shape));
        });
    });
}

int cadflow_export_step(
    cad_session_t handle, unsigned long long shape, const char* path) {
    return cadflow::core::guarded([&] {
        if (!path) {
            throw std::invalid_argument("STEP path is null");
        }
        return with_session(handle, [&](Session& session) {
            cadflow::io::export_step(session, shape, path);
            return 1;
        });
    });
}

int cadflow_export_stl(
    cad_session_t handle, unsigned long long shape, const char* path, int binary) {
    return cadflow::core::guarded([&] {
        if (!path) {
            throw std::invalid_argument("STL path is null");
        }
        return with_session(handle, [&](Session& session) {
            cadflow::io::export_stl(session, shape, path, binary != 0);
            return 1;
        });
    });
}

int cadflow_mesh_json(
    cad_session_t handle, unsigned long long shape, double deflection, char** result) {
    return cadflow::core::guarded([&] {
        if (!result) {
            throw std::invalid_argument("mesh result is null");
        }
        return with_session(handle, [&](Session& session) {
            *result = cadflow::core::copy_string(
                cadflow::io::mesh_json(session, shape, deflection));
            return 1;
        });
    });
}

int cadflow_preview_mesh_buffer(
    cad_session_t handle,
    unsigned long long shape,
    double deflection,
    char** result,
    size_t* result_size) {
    return cadflow::core::guarded([&] {
        if (!result || !result_size) {
            throw std::invalid_argument("preview mesh result and size are required");
        }
        return with_session(handle, [&](Session& session) {
            const std::string buffer =
                cadflow::io::preview_mesh_buffer(session, shape, deflection);
            *result = cadflow::core::copy_string(buffer);
            *result_size = buffer.size();
            return 1;
        });
    });
}

int cadflow_execute(cad_session_t handle, const char* program, char** result) {
    return cadflow::core::guarded([&] {
        if (!program || !result) {
            throw std::invalid_argument("program and result are required");
        }
        return with_session(handle, [&](Session& session) {
            *result = cadflow::core::copy_string(
                cadflow::runtime::execute_graph(session, program));
            return 1;
        });
    });
}

int cadflow_flexible_shell_mesh_counts(
    size_t sample_rows,
    size_t sample_columns,
    int periodic_columns,
    double thickness,
    size_t output[2]) {
    return cadflow::core::guarded([&] {
        if (!output) {
            throw std::invalid_argument("flexible shell count output is null");
        }
        const cadflow::flexible::ShellMeshCounts counts =
            cadflow::flexible::shell_mesh_counts(
                sample_rows, sample_columns, periodic_columns != 0, thickness);
        output[0] = counts.vertex_count;
        output[1] = counts.triangle_count;
        return 1;
    });
}

int cadflow_build_flexible_shell_mesh(
    const double* control_xyz,
    size_t control_rows,
    size_t control_columns,
    size_t sample_rows,
    size_t sample_columns,
    int periodic_columns,
    double thickness,
    double* out_vertices_xyz,
    double* out_normals_xyz,
    unsigned int* out_triangles) {
    return cadflow::core::guarded([&] {
        cadflow::flexible::build_shell_mesh(
            {
                control_xyz,
                control_rows,
                control_columns,
                sample_rows,
                sample_columns,
                periodic_columns != 0,
                thickness,
            },
            {out_vertices_xyz, out_normals_xyz, out_triangles});
        return 1;
    });
}

int cadflow_evaluate_physical_connections(
    const cad_physical_connection_params_t* parameters,
    const cad_physical_connection_state_t* states,
    size_t connection_count,
    cad_physical_connection_response_t* responses) {
    return cadflow::core::guarded([&] {
        cadflow::physics::evaluate_connection_responses(
            parameters, states, connection_count, responses);
        return 1;
    });
}

void cadflow_free_string(char* value) {
    std::free(value);
}

const char* cadflow_last_error(void) {
    return cadflow::core::last_error.c_str();
}

}  // extern "C"
