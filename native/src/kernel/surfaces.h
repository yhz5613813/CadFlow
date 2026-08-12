#pragma once

#include "core/session.h"

#include <cstddef>

namespace cadflow::kernel {

core::ShapeId make_bezier_surface(
    core::Session& session,
    const double* xyz,
    std::size_t rows,
    std::size_t columns,
    const double* weights);

core::ShapeId fit_point_grid_surface(
    core::Session& session,
    const double* xyz,
    std::size_t rows,
    std::size_t columns,
    double tolerance,
    int degree_min,
    int degree_max);

}  // namespace cadflow::kernel
