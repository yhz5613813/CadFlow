#pragma once

#include <cstddef>

namespace cadflow::flexible {

struct ShellMeshCounts {
    std::size_t vertex_count;
    std::size_t triangle_count;
};

struct ShellMeshInput {
    const double* control_xyz;
    std::size_t control_rows;
    std::size_t control_columns;
    std::size_t sample_rows;
    std::size_t sample_columns;
    bool periodic_columns;
    double thickness;
};

struct ShellMeshOutput {
    double* vertices_xyz;
    double* normals_xyz;
    unsigned int* triangles;
};

ShellMeshCounts shell_mesh_counts(
    std::size_t sample_rows,
    std::size_t sample_columns,
    bool periodic_columns,
    double thickness);

void build_shell_mesh(const ShellMeshInput& input, const ShellMeshOutput& output);

}  // namespace cadflow::flexible
