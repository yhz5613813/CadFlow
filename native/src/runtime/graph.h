#pragma once

#include "core/session.h"

#include <string>

namespace cadflow::runtime {

std::string execute_graph(core::Session& session, const std::string& program);

}  // namespace cadflow::runtime
