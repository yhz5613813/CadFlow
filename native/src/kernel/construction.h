#pragma once

#include "core/session.h"

#include <cstddef>

namespace cadflow::kernel {

core::ShapeId make_box(core::Session& session, double width, double depth, double height);
core::ShapeId make_cylinder(core::Session& session, double radius, double height);
core::ShapeId make_sphere(core::Session& session, double radius);
core::ShapeId make_cone(
    core::Session& session, double radius1, double radius2, double height);
core::ShapeId make_polyline(
    core::Session& session, const double* xyz, std::size_t point_count, bool closed);
core::ShapeId make_circle_profile(
    core::Session& session,
    double cx,
    double cy,
    double cz,
    double nx,
    double ny,
    double nz,
    double radius);
core::ShapeId make_arc(core::Session& session, const double points_xyz[9]);
core::ShapeId make_interpolated_curve(
    core::Session& session,
    const double* xyz,
    std::size_t point_count,
    bool periodic,
    double tolerance);
core::ShapeId make_helix(
    core::Session& session,
    double pitch,
    double height,
    double radius,
    double cx,
    double cy,
    double cz,
    double dx,
    double dy,
    double dz);
core::ShapeId make_face(core::Session& session, core::ShapeId wire);

}  // namespace cadflow::kernel
