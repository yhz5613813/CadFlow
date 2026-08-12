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
CADFLOW_API const char *cadflow_kind(
    cad_session_t session, unsigned long long shape);
CADFLOW_API int cadflow_export_step(
    cad_session_t session, unsigned long long shape, const char *path);
CADFLOW_API int cadflow_export_stl(
    cad_session_t session, unsigned long long shape, const char *path, int binary);
CADFLOW_API int cadflow_mesh_json(
    cad_session_t session, unsigned long long shape, double deflection, char **result);

/* Execute a complete graph in one native call.
   The compact line protocol is intentionally independent of Python objects:
   primitives and profiles | face | solid and edge features | booleans |
   transforms | properties. Returns newline-delimited results. */
CADFLOW_API int cadflow_execute(
    cad_session_t session, const char *program, char **result);
CADFLOW_API void cadflow_free_string(char *value);
CADFLOW_API const char *cadflow_last_error(void);

#ifdef __cplusplus
}
#endif
