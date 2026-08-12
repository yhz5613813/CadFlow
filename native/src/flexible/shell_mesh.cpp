#include "flexible/shell_mesh.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <limits>
#include <stdexcept>
#include <vector>

namespace cadflow::flexible {
namespace {

using Vec3 = std::array<double, 3>;
using Triangle = std::array<unsigned int, 3>;

std::size_t checked_multiply(std::size_t left, std::size_t right) {
    if (left != 0 && right > std::numeric_limits<std::size_t>::max() / left) {
        throw std::invalid_argument("flexible shell mesh size overflows size_t");
    }
    return left * right;
}

std::size_t checked_add(std::size_t left, std::size_t right) {
    if (right > std::numeric_limits<std::size_t>::max() - left) {
        throw std::invalid_argument("flexible shell mesh size overflows size_t");
    }
    return left + right;
}

Vec3 add(const Vec3& left, const Vec3& right) {
    return {left[0] + right[0], left[1] + right[1], left[2] + right[2]};
}

Vec3 subtract(const Vec3& left, const Vec3& right) {
    return {left[0] - right[0], left[1] - right[1], left[2] - right[2]};
}

Vec3 multiply(const Vec3& value, double scale) {
    return {value[0] * scale, value[1] * scale, value[2] * scale};
}

Vec3 cross(const Vec3& left, const Vec3& right) {
    return {
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    };
}

double norm(const Vec3& value) {
    return std::sqrt(
        value[0] * value[0] + value[1] * value[1] + value[2] * value[2]);
}

Vec3 catmull_rom(
    const Vec3& p0,
    const Vec3& p1,
    const Vec3& p2,
    const Vec3& p3,
    double t) {
    const double t2 = t * t;
    const double t3 = t2 * t;
    Vec3 result {};
    for (std::size_t axis = 0; axis < 3; ++axis) {
        result[axis] = 0.5 * (
            2.0 * p1[axis] +
            (-p0[axis] + p2[axis]) * t +
            (2.0 * p0[axis] - 5.0 * p1[axis] + 4.0 * p2[axis] - p3[axis]) * t2 +
            (-p0[axis] + 3.0 * p1[axis] - 3.0 * p2[axis] + p3[axis]) * t3);
    }
    return result;
}

std::size_t clamp_index(long long value, std::size_t count) {
    if (value < 0) {
        return 0;
    }
    return std::min(static_cast<std::size_t>(value), count - 1);
}

std::size_t wrap_index(long long value, std::size_t count) {
    const long long modulus = static_cast<long long>(count);
    const long long wrapped = (value % modulus + modulus) % modulus;
    return static_cast<std::size_t>(wrapped);
}

Vec3 control_point(const ShellMeshInput& input, std::size_t row, std::size_t column) {
    const std::size_t offset = (row * input.control_columns + column) * 3;
    return {
        input.control_xyz[offset],
        input.control_xyz[offset + 1],
        input.control_xyz[offset + 2],
    };
}

Vec3 sample_control_grid(const ShellMeshInput& input, std::size_t row, std::size_t column) {
    const double row_parameter = static_cast<double>(row) *
        static_cast<double>(input.control_rows - 1) /
        static_cast<double>(input.sample_rows - 1);
    const long long row_segment = static_cast<long long>(std::floor(row_parameter));
    const double row_t = row_parameter - static_cast<double>(row_segment);

    double column_parameter = 0.0;
    if (input.periodic_columns) {
        column_parameter = static_cast<double>(column) *
            static_cast<double>(input.control_columns) /
            static_cast<double>(input.sample_columns);
    } else {
        column_parameter = static_cast<double>(column) *
            static_cast<double>(input.control_columns - 1) /
            static_cast<double>(input.sample_columns - 1);
    }
    const long long column_segment =
        static_cast<long long>(std::floor(column_parameter));
    const double column_t = column_parameter - static_cast<double>(column_segment);

    Vec3 row_samples[4];
    for (long long row_offset = -1; row_offset <= 2; ++row_offset) {
        const std::size_t source_row = clamp_index(
            row_segment + row_offset, input.control_rows);
        Vec3 points[4];
        for (long long column_offset = -1; column_offset <= 2; ++column_offset) {
            const long long raw_column = column_segment + column_offset;
            const std::size_t source_column = input.periodic_columns
                ? wrap_index(raw_column, input.control_columns)
                : clamp_index(raw_column, input.control_columns);
            points[column_offset + 1] =
                control_point(input, source_row, source_column);
        }
        row_samples[row_offset + 1] = catmull_rom(
            points[0], points[1], points[2], points[3], column_t);
    }
    return catmull_rom(
        row_samples[0], row_samples[1], row_samples[2], row_samples[3], row_t);
}

std::size_t grid_index(
    std::size_t row, std::size_t column, std::size_t columns) {
    return row * columns + column;
}

void append_surface_triangles(
    std::vector<Triangle>& triangles,
    std::size_t rows,
    std::size_t columns,
    bool periodic_columns) {
    const std::size_t column_spans = periodic_columns ? columns : columns - 1;
    for (std::size_t row = 0; row + 1 < rows; ++row) {
        for (std::size_t column = 0; column < column_spans; ++column) {
            const std::size_t next_column = (column + 1) % columns;
            const auto a = static_cast<unsigned int>(grid_index(row, column, columns));
            const auto b = static_cast<unsigned int>(grid_index(row, next_column, columns));
            const auto c = static_cast<unsigned int>(grid_index(row + 1, column, columns));
            const auto d = static_cast<unsigned int>(grid_index(row + 1, next_column, columns));
            triangles.push_back({a, b, c});
            triangles.push_back({b, d, c});
        }
    }
}

std::vector<Vec3> vertex_normals(
    const std::vector<Vec3>& vertices, const std::vector<Triangle>& triangles) {
    std::vector<Vec3> normals(vertices.size(), Vec3 {0.0, 0.0, 0.0});
    for (const Triangle& triangle : triangles) {
        const Vec3 edge_a = subtract(vertices[triangle[1]], vertices[triangle[0]]);
        const Vec3 edge_b = subtract(vertices[triangle[2]], vertices[triangle[0]]);
        const Vec3 face_normal = cross(edge_a, edge_b);
        if (norm(face_normal) <= 1e-14) {
            continue;
        }
        for (unsigned int vertex : triangle) {
            normals[vertex] = add(normals[vertex], face_normal);
        }
    }
    for (Vec3& normal : normals) {
        const double length = norm(normal);
        if (!(length > 1e-14) || !std::isfinite(length)) {
            throw std::invalid_argument(
                "flexible surface has a degenerate sampled vertex normal");
        }
        normal = multiply(normal, 1.0 / length);
    }
    return normals;
}

void append_wall(
    std::vector<Triangle>& triangles,
    unsigned int first,
    unsigned int second,
    unsigned int layer_offset) {
    triangles.push_back({second, first, first + layer_offset});
    triangles.push_back({second, first + layer_offset, second + layer_offset});
}

void append_boundary_walls(
    std::vector<Triangle>& triangles,
    std::size_t rows,
    std::size_t columns,
    bool periodic_columns,
    unsigned int layer_offset) {
    const std::size_t column_spans = periodic_columns ? columns : columns - 1;
    for (std::size_t column = 0; column < column_spans; ++column) {
        const std::size_t next_column = (column + 1) % columns;
        append_wall(
            triangles,
            static_cast<unsigned int>(grid_index(0, column, columns)),
            static_cast<unsigned int>(grid_index(0, next_column, columns)),
            layer_offset);
        append_wall(
            triangles,
            static_cast<unsigned int>(grid_index(rows - 1, next_column, columns)),
            static_cast<unsigned int>(grid_index(rows - 1, column, columns)),
            layer_offset);
    }
    if (periodic_columns) {
        return;
    }
    for (std::size_t row = 0; row + 1 < rows; ++row) {
        append_wall(
            triangles,
            static_cast<unsigned int>(grid_index(row + 1, 0, columns)),
            static_cast<unsigned int>(grid_index(row, 0, columns)),
            layer_offset);
        append_wall(
            triangles,
            static_cast<unsigned int>(grid_index(row, columns - 1, columns)),
            static_cast<unsigned int>(grid_index(row + 1, columns - 1, columns)),
            layer_offset);
    }
}

void validate(const ShellMeshInput& input, const ShellMeshOutput& output) {
    if (!input.control_xyz || !output.vertices_xyz || !output.normals_xyz ||
        !output.triangles) {
        throw std::invalid_argument("flexible shell input and output arrays are required");
    }
    if (input.control_rows < 2 || input.control_columns < 2 ||
        input.sample_rows < input.control_rows ||
        input.sample_columns < input.control_columns) {
        throw std::invalid_argument(
            "flexible shell sample grid must not be smaller than its control grid");
    }
    if (input.periodic_columns && input.control_columns < 3) {
        throw std::invalid_argument(
            "periodic flexible shell requires at least three control columns");
    }
    if (!std::isfinite(input.thickness) || input.thickness < 0.0) {
        throw std::invalid_argument("flexible shell thickness must be finite and non-negative");
    }
    const std::size_t control_value_count = checked_multiply(
        checked_multiply(input.control_rows, input.control_columns), 3);
    for (std::size_t index = 0; index < control_value_count; ++index) {
        if (!std::isfinite(input.control_xyz[index])) {
            throw std::invalid_argument("flexible shell control points must be finite");
        }
    }
    const ShellMeshCounts counts = shell_mesh_counts(
        input.sample_rows,
        input.sample_columns,
        input.periodic_columns,
        input.thickness);
    if (counts.vertex_count > std::numeric_limits<unsigned int>::max()) {
        throw std::invalid_argument("flexible shell mesh exceeds 32-bit index capacity");
    }
}

}  // namespace

ShellMeshCounts shell_mesh_counts(
    std::size_t sample_rows,
    std::size_t sample_columns,
    bool periodic_columns,
    double thickness) {
    if (sample_rows < 2 || sample_columns < 2 ||
        (periodic_columns && sample_columns < 3)) {
        throw std::invalid_argument("invalid flexible shell sample grid dimensions");
    }
    if (!std::isfinite(thickness) || thickness < 0.0) {
        throw std::invalid_argument("flexible shell thickness must be finite and non-negative");
    }
    const std::size_t row_spans = sample_rows - 1;
    const std::size_t column_spans =
        periodic_columns ? sample_columns : sample_columns - 1;
    const std::size_t surface_triangles = checked_multiply(
        checked_multiply(2, row_spans), column_spans);
    const std::size_t grid_vertices =
        checked_multiply(sample_rows, sample_columns);
    if (thickness == 0.0) {
        return {grid_vertices, surface_triangles};
    }
    const std::size_t boundary_edges = checked_add(
        checked_multiply(2, column_spans),
        periodic_columns ? 0 : checked_multiply(2, row_spans));
    return {
        checked_multiply(2, grid_vertices),
        checked_add(
            checked_multiply(2, surface_triangles),
            checked_multiply(2, boundary_edges)),
    };
}

void build_shell_mesh(const ShellMeshInput& input, const ShellMeshOutput& output) {
    validate(input, output);
    const ShellMeshCounts counts = shell_mesh_counts(
        input.sample_rows,
        input.sample_columns,
        input.periodic_columns,
        input.thickness);
    const std::size_t grid_vertex_count = input.sample_rows * input.sample_columns;
    std::vector<Vec3> center_vertices(grid_vertex_count);
    for (std::size_t row = 0; row < input.sample_rows; ++row) {
        for (std::size_t column = 0; column < input.sample_columns; ++column) {
            center_vertices[grid_index(row, column, input.sample_columns)] =
                sample_control_grid(input, row, column);
        }
    }

    std::vector<Triangle> surface_triangles;
    surface_triangles.reserve(
        2 * (input.sample_rows - 1) *
        (input.periodic_columns ? input.sample_columns : input.sample_columns - 1));
    append_surface_triangles(
        surface_triangles,
        input.sample_rows,
        input.sample_columns,
        input.periodic_columns);
    const std::vector<Vec3> center_normals =
        vertex_normals(center_vertices, surface_triangles);

    std::vector<Vec3> vertices;
    std::vector<Vec3> normals;
    std::vector<Triangle> triangles = surface_triangles;
    vertices.reserve(counts.vertex_count);
    normals.reserve(counts.vertex_count);
    if (input.thickness == 0.0) {
        vertices = center_vertices;
        normals = center_normals;
    } else {
        const double half_thickness = input.thickness * 0.5;
        for (std::size_t index = 0; index < grid_vertex_count; ++index) {
            vertices.push_back(add(
                center_vertices[index], multiply(center_normals[index], half_thickness)));
            normals.push_back(center_normals[index]);
        }
        for (std::size_t index = 0; index < grid_vertex_count; ++index) {
            vertices.push_back(subtract(
                center_vertices[index], multiply(center_normals[index], half_thickness)));
            normals.push_back(multiply(center_normals[index], -1.0));
        }
        const auto layer_offset = static_cast<unsigned int>(grid_vertex_count);
        triangles.reserve(counts.triangle_count);
        for (const Triangle& triangle : surface_triangles) {
            triangles.push_back({
                triangle[0] + layer_offset,
                triangle[2] + layer_offset,
                triangle[1] + layer_offset,
            });
        }
        append_boundary_walls(
            triangles,
            input.sample_rows,
            input.sample_columns,
            input.periodic_columns,
            layer_offset);
    }

    if (vertices.size() != counts.vertex_count || triangles.size() != counts.triangle_count) {
        throw std::runtime_error("flexible shell mesh count invariant failed");
    }
    for (std::size_t index = 0; index < vertices.size(); ++index) {
        for (std::size_t axis = 0; axis < 3; ++axis) {
            output.vertices_xyz[index * 3 + axis] = vertices[index][axis];
            output.normals_xyz[index * 3 + axis] = normals[index][axis];
        }
    }
    for (std::size_t index = 0; index < triangles.size(); ++index) {
        for (std::size_t corner = 0; corner < 3; ++corner) {
            output.triangles[index * 3 + corner] = triangles[index][corner];
        }
    }
}

}  // namespace cadflow::flexible
