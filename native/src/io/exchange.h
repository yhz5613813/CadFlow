#pragma once

#include "core/session.h"

#include <string>

namespace cadflow::io {

core::ShapeId import_step(core::Session& session, const std::string& path);
void export_step(
    const core::Session& session, core::ShapeId shape, const std::string& path);
void export_stl(
    const core::Session& session,
    core::ShapeId shape,
    const std::string& path,
    bool binary);
std::string mesh_json(
    const core::Session& session, core::ShapeId shape, double deflection);

}  // namespace cadflow::io
