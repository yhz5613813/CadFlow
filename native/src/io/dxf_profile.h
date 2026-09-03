#pragma once

#include "core/session.h"

#include <string>

namespace cadflow::io {

void export_dxf_profile(
    const core::Session& session,
    core::ShapeId face,
    const std::string& path,
    double tolerance);

}  // namespace cadflow::io
