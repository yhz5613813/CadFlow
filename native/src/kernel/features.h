#pragma once

#include "core/session.h"

#include <cstddef>

namespace cadflow::kernel {

core::ShapeId extrude(
    core::Session& session, core::ShapeId profile, double x, double y, double z);
core::ShapeId revolve(
    core::Session& session,
    core::ShapeId profile,
    double ox,
    double oy,
    double oz,
    double ax,
    double ay,
    double az,
    double degrees);
core::ShapeId loft(
    core::Session& session,
    const core::ShapeId* profiles,
    std::size_t profile_count,
    bool solid,
    bool ruled);
core::ShapeId sweep(
    core::Session& session,
    core::ShapeId profile,
    core::ShapeId path,
    bool solid,
    bool frenet);

}  // namespace cadflow::kernel
