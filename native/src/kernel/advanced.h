#pragma once

#include "core/session.h"

#include <cstddef>

namespace cadflow::kernel {

core::ShapeId make_bspline(
    core::Session& session,
    const double* poles_xyz,
    std::size_t pole_count,
    int degree,
    const double* knots,
    std::size_t knot_count,
    const int* multiplicities,
    std::size_t multiplicity_count,
    const double* weights,
    bool periodic);

core::ShapeId twisted_sweep(
    core::Session& session,
    core::ShapeId profile,
    double distance,
    double twist_degrees,
    double ox,
    double oy,
    double oz,
    double ax,
    double ay,
    double az,
    double guide_radius);

core::ShapeId ruled_surface(
    core::Session& session, core::ShapeId edge_a, core::ShapeId edge_b);
core::ShapeId filling_surface(
    core::Session& session,
    const core::ShapeId* edges,
    std::size_t edge_count,
    double tolerance);
core::ShapeId gordon_surface(
    core::Session& session,
    const core::ShapeId* profiles,
    std::size_t profile_count,
    const core::ShapeId* guides,
    std::size_t guide_count,
    double tolerance);
core::ShapeId sew(
    core::Session& session,
    const core::ShapeId* faces,
    std::size_t face_count,
    double tolerance);
core::ShapeId shell_to_solid(core::Session& session, core::ShapeId shell);
core::ShapeId import_brep(core::Session& session, const char* path);
core::ShapeId import_stl(core::Session& session, const char* path);

std::size_t subshape_count(
    const core::Session& session, core::ShapeId shape, int shape_type);
std::size_t subshape_handles(
    core::Session& session,
    core::ShapeId shape,
    int shape_type,
    core::ShapeId* output,
    std::size_t capacity);
std::size_t free_boundary_count(
    const core::Session& session, core::ShapeId shape, double tolerance);
std::size_t free_boundary_handles(
    core::Session& session,
    core::ShapeId shape,
    double tolerance,
    core::ShapeId* output,
    std::size_t capacity);

void face_properties(
    const core::Session& session,
    core::ShapeId face,
    double u,
    double v,
    double normal_out[3],
    double curvature_out[3]);

}  // namespace cadflow::kernel
