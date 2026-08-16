#pragma once

#include <stddef.h>

#if defined(_WIN32)
#  if defined(CADFLOW_CORE_BUILD)
#    define CADFLOW_API __declspec(dllexport)
#  else
#    define CADFLOW_API __declspec(dllimport)
#  endif
#else
#  define CADFLOW_API __attribute__((visibility("default")))
#endif

#ifdef __cplusplus
extern "C" {
#endif

typedef void *cad_session_t;

typedef enum cad_physical_connection_mode_t {
    CADFLOW_CONNECTION_BONDED = 0,
    CADFLOW_CONNECTION_FRICTIONAL_CONTACT = 1,
    CADFLOW_CONNECTION_FASTENER = 2,
    CADFLOW_CONNECTION_INTERFERENCE = 3,
    CADFLOW_CONNECTION_COMPLIANT = 4
} cad_physical_connection_mode_t;

typedef struct cad_physical_connection_params_t {
    int response_mode;
    double axis[3];
    double normal_stiffness;
    double tangential_stiffness;
    double rotational_stiffness;
    double normal_damping;
    double tangential_damping;
    double rotational_damping;
    double friction_coefficient;
    double preload;
    double clearance;
    double interference;
    /* A zero limit disables the corresponding utilization check. */
    double tensile_limit;
    double shear_limit;
    double torque_limit;
} cad_physical_connection_params_t;

typedef struct cad_physical_connection_state_t {
    double relative_translation[3];
    double relative_rotation[3];
    double relative_linear_velocity[3];
    double relative_angular_velocity[3];
} cad_physical_connection_state_t;

typedef struct cad_physical_connection_response_t {
    double force[3];
    double torque[3];
    double normal_force;
    double shear_force;
    double tensile_utilization;
    double shear_utilization;
    double torque_utilization;
    int active;
    int failed;
} cad_physical_connection_response_t;

CADFLOW_API const char *cadflow_version(void);
CADFLOW_API cad_session_t cadflow_session_create(void);
CADFLOW_API void cadflow_session_destroy(cad_session_t session);

CADFLOW_API unsigned long long cadflow_box(
    cad_session_t session, double width, double depth, double height);
CADFLOW_API unsigned long long cadflow_cylinder(
    cad_session_t session, double radius, double height);
CADFLOW_API unsigned long long cadflow_sphere(
    cad_session_t session, double radius);
CADFLOW_API unsigned long long cadflow_cone(
    cad_session_t session, double radius1, double radius2, double height);
CADFLOW_API unsigned long long cadflow_import_step(
    cad_session_t session, const char *path);
CADFLOW_API unsigned long long cadflow_import_brep(
    cad_session_t session, const char *path);
CADFLOW_API unsigned long long cadflow_import_stl(
    cad_session_t session, const char *path);
CADFLOW_API unsigned long long cadflow_polyline(
    cad_session_t session, const double *xyz, size_t point_count, int closed);
CADFLOW_API unsigned long long cadflow_circle_profile(
    cad_session_t session,
    double cx, double cy, double cz,
    double nx, double ny, double nz,
    double radius);
CADFLOW_API unsigned long long cadflow_arc(
    cad_session_t session, const double points_xyz[9]);
CADFLOW_API unsigned long long cadflow_interpolate(
    cad_session_t session, const double *xyz, size_t point_count,
    int periodic, double tolerance);
CADFLOW_API unsigned long long cadflow_helix(
    cad_session_t session, double pitch, double height, double radius,
    double cx, double cy, double cz, double dx, double dy, double dz);
CADFLOW_API unsigned long long cadflow_face(
    cad_session_t session, unsigned long long wire);
CADFLOW_API unsigned long long cadflow_bezier_surface(
    cad_session_t session, const double *xyz, size_t rows, size_t columns,
    const double *weights);
CADFLOW_API unsigned long long cadflow_fit_surface(
    cad_session_t session, const double *xyz, size_t rows, size_t columns,
    double tolerance, int degree_min, int degree_max);
CADFLOW_API unsigned long long cadflow_extrude(
    cad_session_t session, unsigned long long profile,
    double x, double y, double z);
CADFLOW_API unsigned long long cadflow_revolve(
    cad_session_t session, unsigned long long profile,
    double ox, double oy, double oz,
    double ax, double ay, double az,
    double degrees);
/* Edge/face selections use zero-based indices in OCCT's deterministic
   subshape maps.  A null/empty edge selection means all unique edges;
   shell selections are always explicit face indices. */
CADFLOW_API unsigned long long cadflow_fillet(
    cad_session_t session, unsigned long long shape, double radius,
    const size_t *edge_indices, size_t edge_count);
CADFLOW_API unsigned long long cadflow_chamfer(
    cad_session_t session, unsigned long long shape, double distance,
    const size_t *edge_indices, size_t edge_count);
CADFLOW_API unsigned long long cadflow_shell(
    cad_session_t session, unsigned long long shape, double thickness,
    const size_t *face_indices, size_t face_count, double tolerance);
CADFLOW_API unsigned long long cadflow_loft(
    cad_session_t session, const unsigned long long *profiles,
    size_t profile_count, int solid, int ruled);
CADFLOW_API unsigned long long cadflow_sweep(
    cad_session_t session, unsigned long long profile,
    unsigned long long path, int solid, int frenet);
CADFLOW_API unsigned long long cadflow_bspline(
    cad_session_t session,
    const double *poles_xyz, size_t pole_count, int degree,
    const double *knots, size_t knot_count,
    const int *multiplicities, size_t multiplicity_count,
    const double *weights, int periodic);
CADFLOW_API unsigned long long cadflow_twisted_sweep(
    cad_session_t session, unsigned long long profile,
    double distance, double twist_degrees,
    double ox, double oy, double oz,
    double ax, double ay, double az, double guide_radius);
CADFLOW_API unsigned long long cadflow_ruled_surface(
    cad_session_t session, unsigned long long edge_a, unsigned long long edge_b);
CADFLOW_API unsigned long long cadflow_filling_surface(
    cad_session_t session, const unsigned long long *edges,
    size_t edge_count, double tolerance);
CADFLOW_API unsigned long long cadflow_gordon_surface(
    cad_session_t session, const unsigned long long *profiles,
    size_t profile_count, const unsigned long long *guides,
    size_t guide_count, double tolerance);
CADFLOW_API unsigned long long cadflow_sew(
    cad_session_t session, const unsigned long long *faces,
    size_t face_count, double tolerance);
CADFLOW_API unsigned long long cadflow_shell_to_solid(
    cad_session_t session, unsigned long long shell);
CADFLOW_API unsigned long long cadflow_cut(
    cad_session_t session, unsigned long long body, unsigned long long tool);
CADFLOW_API unsigned long long cadflow_union(
    cad_session_t session, unsigned long long left, unsigned long long right);
CADFLOW_API unsigned long long cadflow_intersect(
    cad_session_t session, unsigned long long left, unsigned long long right);
CADFLOW_API unsigned long long cadflow_translate(
    cad_session_t session, unsigned long long shape, double x, double y, double z);
CADFLOW_API unsigned long long cadflow_rotate(
    cad_session_t session,
    unsigned long long shape,
    double ox, double oy, double oz,
    double ax, double ay, double az,
    double degrees);
CADFLOW_API unsigned long long cadflow_mirror(
    cad_session_t session, unsigned long long shape,
    double ox, double oy, double oz,
    double nx, double ny, double nz);
CADFLOW_API unsigned long long cadflow_scale(
    cad_session_t session, unsigned long long shape,
    double cx, double cy, double cz, double factor);

CADFLOW_API double cadflow_volume(
    cad_session_t session, unsigned long long shape);
CADFLOW_API double cadflow_area(
    cad_session_t session, unsigned long long shape);
CADFLOW_API double cadflow_length(
    cad_session_t session, unsigned long long shape);
CADFLOW_API double cadflow_distance(
    cad_session_t session, unsigned long long left, unsigned long long right);
CADFLOW_API int cadflow_center_of_mass(
    cad_session_t session, unsigned long long shape, double out_xyz[3]);
CADFLOW_API int cadflow_bbox(
    cad_session_t session, unsigned long long shape, double out_min_max[6]);
CADFLOW_API int cadflow_topology_counts(
    cad_session_t session, unsigned long long shape, unsigned long long out_vefs[4]);
CADFLOW_API size_t cadflow_subshape_count(
    cad_session_t session, unsigned long long shape, int shape_type);
CADFLOW_API size_t cadflow_subshape_handles(
    cad_session_t session, unsigned long long shape, int shape_type,
    unsigned long long *output, size_t capacity);
CADFLOW_API size_t cadflow_free_boundary_count(
    cad_session_t session, unsigned long long shape, double tolerance);
CADFLOW_API size_t cadflow_free_boundary_handles(
    cad_session_t session, unsigned long long shape, double tolerance,
    unsigned long long *output, size_t capacity);
CADFLOW_API int cadflow_face_properties(
    cad_session_t session, unsigned long long face, double u, double v,
    double normal_out[3], double curvature_out[3]);
CADFLOW_API const char *cadflow_kind(
    cad_session_t session, unsigned long long shape);
CADFLOW_API int cadflow_export_step(
    cad_session_t session, unsigned long long shape, const char *path);
CADFLOW_API int cadflow_export_stl(
    cad_session_t session, unsigned long long shape, const char *path, int binary);
CADFLOW_API int cadflow_mesh_json(
    cad_session_t session, unsigned long long shape, double deflection, char **result);
/* Return a render-ready binary mesh buffer. The caller owns *result and must
   release it with cadflow_free_string. The buffer format is versioned and
   contains glTF-space float32 positions/normals plus compact triangle indices. */
CADFLOW_API int cadflow_preview_mesh_buffer(
    cad_session_t session, unsigned long long shape, double deflection,
    char **result, size_t *result_size);

/* Execute a complete graph in one native call.
   The compact line protocol is intentionally independent of Python objects:
   primitives and profiles | face | solid and edge features | booleans |
   transforms | properties. Returns newline-delimited results. */
CADFLOW_API int cadflow_execute(
    cad_session_t session, const char *program, char **result);

/* Stateless static mesh construction for flexible surface and thin-shell
   models. The count function defines the exact caller-owned buffer sizes. */
CADFLOW_API int cadflow_flexible_shell_mesh_counts(
    size_t sample_rows,
    size_t sample_columns,
    int periodic_columns,
    double thickness,
    size_t out_vertex_triangle_counts[2]);
CADFLOW_API int cadflow_build_flexible_shell_mesh(
    const double *control_xyz,
    size_t control_rows,
    size_t control_columns,
    size_t sample_rows,
    size_t sample_columns,
    int periodic_columns,
    double thickness,
    double *out_vertices_xyz,
    double *out_normals_xyz,
    unsigned int *out_triangles);

/* Stateless batched reduced-order physical connection response.  States and
   responses use connector A's local frame; force/torque act on component B. */
CADFLOW_API int cadflow_evaluate_physical_connections(
    const cad_physical_connection_params_t *parameters,
    const cad_physical_connection_state_t *states,
    size_t connection_count,
    cad_physical_connection_response_t *responses);

CADFLOW_API void cadflow_free_string(char *value);
CADFLOW_API const char *cadflow_last_error(void);

#ifdef __cplusplus
}
#endif
