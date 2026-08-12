#pragma once

#include "core/session.h"

#include <cstddef>

namespace cadflow::kernel {

core::ShapeId fillet(
    core::Session& session,
    core::ShapeId shape,
    double radius,
    const std::size_t* edge_indices,
    std::size_t edge_count);

core::ShapeId chamfer(
    core::Session& session,
    core::ShapeId shape,
    double distance,
    const std::size_t* edge_indices,
    std::size_t edge_count);

core::ShapeId shell(
    core::Session& session,
    core::ShapeId shape,
    double thickness,
    const std::size_t* face_indices,
    std::size_t face_count,
    double tolerance);

}  // namespace cadflow::kernel
