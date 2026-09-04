#pragma once

#include "cadflow_core.h"

#include <cstddef>
#include <vector>

namespace cadflow::presentation {

struct Evaluation {
    std::vector<int> node_visibility;
    std::vector<std::size_t> node_appearance_indices;
    std::vector<std::size_t> camera_parent_indices;
};

Evaluation evaluate(
    const char* presentation_source_scene_id,
    const char* scene_id,
    const cad_presentation_appearance_t* appearances,
    std::size_t appearance_count,
    const cad_presentation_scene_node_t* nodes,
    std::size_t node_count,
    const cad_presentation_node_override_t* overrides,
    std::size_t override_count,
    const cad_presentation_camera_t* cameras,
    std::size_t camera_count);

}  // namespace cadflow::presentation
