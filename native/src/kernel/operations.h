#pragma once

#include "core/session.h"

namespace cadflow::kernel {

core::ShapeId boolean_operation(
    core::Session& session,
    core::Shape::Kind kind,
    core::ShapeId left,
    core::ShapeId right);
core::ShapeId translate(
    core::Session& session, core::ShapeId shape, double x, double y, double z);
core::ShapeId rotate(
    core::Session& session,
    core::ShapeId shape,
    double ox,
    double oy,
    double oz,
    double ax,
    double ay,
    double az,
    double degrees);
core::ShapeId mirror(
    core::Session& session,
    core::ShapeId shape,
    double ox,
    double oy,
    double oz,
    double nx,
    double ny,
    double nz);
core::ShapeId scale(
    core::Session& session,
    core::ShapeId shape,
    double cx,
    double cy,
    double cz,
    double factor);

}  // namespace cadflow::kernel
