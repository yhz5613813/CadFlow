#pragma once

#include "core/session.h"

#include <cstddef>

namespace cadflow::kernel {

/* Round edges with a curvature-continuous (G2) or tangent (G1) blend instead
   of a circular arc. OCCT's circular fillet with radius `setback` places the
   trim lines on the adjacent faces; each round face is then replaced by a
   quintic Hermite blend between the same trim lines and the end faces are
   re-bounded by the blend's end sections. Empty selection means all edges. */
core::ShapeId smooth_fillet(
    core::Session& session,
    core::ShapeId shape,
    double setback,
    const std::size_t* edge_indices,
    std::size_t edge_count,
    int continuity,
    double tension,
    double tolerance);

}  // namespace cadflow::kernel
