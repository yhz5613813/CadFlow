#pragma once

#include "core/session.h"

#include <cstddef>
#include <string>

namespace cadflow::analysis {

struct ContinuityTolerances {
    double position {1.0e-3};
    double angle_degrees {0.5};
    double curvature_ratio {0.05};
};

/* Boundary continuity across every manifold edge shared by two faces. */
std::string continuity_json(
    const core::Session& session,
    core::ShapeId shape,
    std::size_t samples,
    const ContinuityTolerances& tolerances);

/* Boundary continuity between two separate faces whose boundaries touch.
   Coincident edges are matched geometrically, so the faces need not be sewn. */
std::string face_pair_continuity_json(
    const core::Session& session,
    core::ShapeId face_a,
    core::ShapeId face_b,
    std::size_t samples,
    const ContinuityTolerances& tolerances);

void curvature_samples(
    const core::Session& session,
    core::ShapeId face,
    std::size_t u_count,
    std::size_t v_count,
    cad_surface_sample_t* output);

/* Versioned binary buffer: tessellation plus exact per-vertex curvature. */
std::string curvature_mesh_buffer(
    const core::Session& session, core::ShapeId shape, double deflection);

std::string surface_quality_json(
    const core::Session& session,
    core::ShapeId shape,
    std::size_t samples,
    bool check_self_intersection);

}  // namespace cadflow::analysis
