#include "cadflow_core.h"

#include <cstddef>
#include <iostream>
#include <limits>
#include <string>

namespace {

bool require(bool condition, const char* message) {
    if (!condition) {
        std::cerr << message << '\n';
    }
    return condition;
}

}  // namespace

int main() {
    const cad_presentation_appearance_t appearances[] = {
        {
            "painted-steel",
            {0.72, 0.03, 0.02, 1.0},
            0.75,
            0.22,
            CADFLOW_PRESENTATION_ALPHA_OPAQUE,
            0,
            {0.05, 0.05, 0.05, 1.0},
        },
    };
    const cad_presentation_scene_node_t nodes[] = {
        {"instance/root", 0, 1},
        {"instance/root/body", 1, 1},
    };
    const cad_presentation_node_override_t overrides[] = {
        {"instance/root", 1, 0, nullptr},
        {"instance/root/body", 0, 0, "painted-steel"},
    };
    const cad_presentation_camera_t cameras[] = {
        {
            "hero",
            "instance/root",
            CADFLOW_PRESENTATION_CAMERA_PERSPECTIVE,
            0.1,
            1000.0,
            42.0,
        },
    };
    int visibility[2] = {};
    std::size_t appearance_indices[2] = {};
    std::size_t camera_parent_indices[1] = {};

    if (!require(
            cadflow_evaluate_presentation(
                "optimus",
                "optimus",
                appearances,
                1,
                nodes,
                2,
                overrides,
                2,
                cameras,
                1,
                visibility,
                appearance_indices,
                camera_parent_indices) == 1,
            cadflow_last_error())) {
        return 1;
    }
    const std::size_t unset = std::numeric_limits<std::size_t>::max();
    if (!require(visibility[0] == 0 && visibility[1] == 1,
                 "visibility evaluation failed") ||
        !require(appearance_indices[0] == unset && appearance_indices[1] == 0,
                 "appearance evaluation failed") ||
        !require(camera_parent_indices[0] == 0,
                 "camera parent evaluation failed")) {
        return 1;
    }

    const cad_presentation_node_override_t invalid_override[] = {
        {"instance/root", 0, 0, "painted-steel"},
    };
    if (!require(
            cadflow_evaluate_presentation(
                "optimus",
                "optimus",
                appearances,
                1,
                nodes,
                2,
                invalid_override,
                1,
                nullptr,
                0,
                visibility,
                appearance_indices,
                nullptr) == 0,
            "non-renderable appearance target was accepted") ||
        !require(
            std::string(cadflow_last_error()).find("not a Part or Shape") !=
                std::string::npos,
            "invalid target did not produce the expected native error")) {
        return 1;
    }
    return 0;
}
