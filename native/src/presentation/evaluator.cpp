#include "presentation/evaluator.h"

#include <cmath>
#include <limits>
#include <stdexcept>
#include <string>
#include <unordered_map>

namespace cadflow::presentation {
namespace {

constexpr std::size_t kMaxAppearances = 25'000;
constexpr std::size_t kMaxNodes = 100'000;
constexpr std::size_t kMaxCameras = 1'000;
constexpr std::size_t kUnsetIndex = std::numeric_limits<std::size_t>::max();

template <typename Value>
void require_array(const Value* values, std::size_t count, const char* name) {
    if (count != 0 && values == nullptr) {
        throw std::invalid_argument(std::string(name) + " array is null");
    }
}

std::string required_string(const char* value, const char* name) {
    if (value == nullptr || value[0] == '\0') {
        throw std::invalid_argument(std::string(name) + " must not be empty");
    }
    return value;
}

void require_boolean(int value, const char* name) {
    if (value != 0 && value != 1) {
        throw std::invalid_argument(std::string(name) + " must be 0 or 1");
    }
}

void require_unit_interval(double value, const char* name) {
    if (!std::isfinite(value) || value < 0.0 || value > 1.0) {
        throw std::invalid_argument(
            std::string(name) + " must be finite and between 0 and 1");
    }
}

void validate_appearance(const cad_presentation_appearance_t& appearance) {
    required_string(appearance.name, "appearance name");
    for (double component : appearance.base_color) {
        require_unit_interval(component, "appearance base color component");
    }
    for (double component : appearance.edge_color) {
        require_unit_interval(component, "appearance edge color component");
    }
    if (appearance.base_color[3] != 1.0 || appearance.edge_color[3] != 1.0) {
        throw std::invalid_argument(
            "presentation appearance alpha components must equal 1");
    }
    require_unit_interval(appearance.metallic, "appearance metallic");
    require_unit_interval(appearance.roughness, "appearance roughness");
    if (appearance.alpha_mode < CADFLOW_PRESENTATION_ALPHA_OPAQUE ||
        appearance.alpha_mode > CADFLOW_PRESENTATION_ALPHA_BLEND) {
        throw std::invalid_argument("unknown presentation alpha mode");
    }
    require_boolean(appearance.double_sided, "appearance double_sided");
}

void validate_camera(const cad_presentation_camera_t& camera) {
    required_string(camera.name, "camera name");
    if (!std::isfinite(camera.near_plane) || camera.near_plane <= 0.0 ||
        !std::isfinite(camera.far_plane) ||
        camera.far_plane <= camera.near_plane) {
        throw std::invalid_argument(
            "camera near and far planes must be finite, positive, and ordered");
    }
    if (!std::isfinite(camera.projection_value) ||
        camera.projection_value <= 0.0) {
        throw std::invalid_argument(
            "camera projection value must be finite and positive");
    }
    if (camera.projection == CADFLOW_PRESENTATION_CAMERA_PERSPECTIVE) {
        if (camera.projection_value >= 180.0) {
            throw std::invalid_argument(
                "perspective camera vertical FOV must be less than 180 degrees");
        }
    } else if (camera.projection != CADFLOW_PRESENTATION_CAMERA_ORTHOGRAPHIC) {
        throw std::invalid_argument("unknown presentation camera projection");
    }
}

}  // namespace

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
    std::size_t camera_count) {
    const std::string source_scene = required_string(
        presentation_source_scene_id, "presentation source_scene_id");
    const std::string target_scene = required_string(scene_id, "scene_id");
    if (source_scene != target_scene) {
        throw std::invalid_argument(
            "presentation source_scene_id does not match scene_id");
    }
    if (appearance_count > kMaxAppearances) {
        throw std::invalid_argument("presentation appearances exceed resource limit");
    }
    if (node_count > kMaxNodes || override_count > kMaxNodes) {
        throw std::invalid_argument("presentation nodes exceed resource limit");
    }
    if (camera_count > kMaxCameras) {
        throw std::invalid_argument("presentation cameras exceed resource limit");
    }
    require_array(appearances, appearance_count, "appearance");
    require_array(nodes, node_count, "node");
    require_array(overrides, override_count, "override");
    require_array(cameras, camera_count, "camera");

    std::unordered_map<std::string, std::size_t> appearance_indices;
    appearance_indices.reserve(appearance_count);
    for (std::size_t index = 0; index < appearance_count; ++index) {
        validate_appearance(appearances[index]);
        const std::string name = appearances[index].name;
        if (!appearance_indices.emplace(name, index).second) {
            throw std::invalid_argument("presentation appearance names must be unique");
        }
    }

    Evaluation result;
    result.node_visibility.reserve(node_count);
    result.node_appearance_indices.assign(node_count, kUnsetIndex);
    std::unordered_map<std::string, std::size_t> node_indices;
    node_indices.reserve(node_count);
    for (std::size_t index = 0; index < node_count; ++index) {
        const auto& node = nodes[index];
        const std::string node_id = required_string(node.node_id, "node_id");
        require_boolean(node.appearance_capable, "node appearance_capable");
        require_boolean(node.visible, "node visible");
        if (!node_indices.emplace(node_id, index).second) {
            throw std::invalid_argument("scene node IDs must be unique");
        }
        result.node_visibility.push_back(node.visible);
    }

    std::unordered_map<std::string, std::size_t> overridden_nodes;
    overridden_nodes.reserve(override_count);
    for (std::size_t index = 0; index < override_count; ++index) {
        const auto& override_value = overrides[index];
        const std::string node_id = required_string(
            override_value.node_id, "override node_id");
        const auto node = node_indices.find(node_id);
        if (node == node_indices.end()) {
            throw std::invalid_argument(
                "presentation override target does not exist in the scene");
        }
        if (!overridden_nodes.emplace(node_id, index).second) {
            throw std::invalid_argument(
                "presentation overrides must target unique scene nodes");
        }
        require_boolean(override_value.has_visible, "override has_visible");
        if (override_value.has_visible != 0) {
            require_boolean(override_value.visible, "override visible");
            result.node_visibility[node->second] = override_value.visible;
        }
        if (override_value.appearance_name != nullptr) {
            const std::string appearance_name = required_string(
                override_value.appearance_name, "override appearance_name");
            const auto appearance = appearance_indices.find(appearance_name);
            if (appearance == appearance_indices.end()) {
                throw std::invalid_argument(
                    "presentation override appearance does not exist");
            }
            if (nodes[node->second].appearance_capable == 0) {
                throw std::invalid_argument(
                    "presentation appearance override target is not a Part or Shape");
            }
            result.node_appearance_indices[node->second] = appearance->second;
        } else if (override_value.has_visible == 0) {
            throw std::invalid_argument(
                "presentation override must set visible or appearance_name");
        }
    }

    result.camera_parent_indices.assign(camera_count, kUnsetIndex);
    std::unordered_map<std::string, std::size_t> camera_names;
    camera_names.reserve(camera_count);
    for (std::size_t index = 0; index < camera_count; ++index) {
        const auto& camera = cameras[index];
        validate_camera(camera);
        if (!camera_names.emplace(camera.name, index).second) {
            throw std::invalid_argument("presentation camera names must be unique");
        }
        if (camera.parent_node_id != nullptr) {
            const std::string parent_id = required_string(
                camera.parent_node_id, "camera parent_node_id");
            const auto parent = node_indices.find(parent_id);
            if (parent == node_indices.end()) {
                throw std::invalid_argument(
                    "presentation camera parent does not exist in the scene");
            }
            result.camera_parent_indices[index] = parent->second;
        }
    }
    return result;
}

}  // namespace cadflow::presentation
