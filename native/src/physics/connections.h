#pragma once

#include "cadflow_core.h"

#include <cstddef>

namespace cadflow::physics {

void evaluate_connection_responses(
    const cad_physical_connection_params_t* parameters,
    const cad_physical_connection_state_t* states,
    std::size_t connection_count,
    cad_physical_connection_response_t* responses);

}  // namespace cadflow::physics
