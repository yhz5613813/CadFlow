#pragma once

#include "core/session.h"

namespace cadflow::kernel {

double volume(const core::Session& session, core::ShapeId shape);
double area(const core::Session& session, core::ShapeId shape);
double length(const core::Session& session, core::ShapeId shape);
double distance(
    const core::Session& session, core::ShapeId left, core::ShapeId right);
core::Box3 bounding_box(const core::Session& session, core::ShapeId shape);
void center_of_mass(
    const core::Session& session, core::ShapeId shape, double output[3]);
const char* kind(const core::Shape& shape);
void topology_counts(
    const core::Session& session, core::ShapeId shape, unsigned long long output[4]);

}  // namespace cadflow::kernel
