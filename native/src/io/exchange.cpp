#include "io/exchange.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstring>
#include <iomanip>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <utility>
#include <vector>

#ifdef CADFLOW_WITH_OCCT
#include <BRepMesh_IncrementalMesh.hxx>
#include <BRep_Tool.hxx>
#include <Poly_Triangulation.hxx>
#ifdef CADFLOW_WITH_STEP
#include <STEPControl_Reader.hxx>
#include <STEPControl_Writer.hxx>
#endif
#include <StlAPI_Writer.hxx>
#include <TopAbs.hxx>
#include <TopExp_Explorer.hxx>
#include <TopLoc_Location.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Pnt.hxx>
#endif

namespace cadflow::io {

namespace {

constexpr std::uint32_t kPreviewMeshVersion = 1;
constexpr std::uint32_t kUnsignedShortComponent = 5123;
constexpr std::uint32_t kUnsignedIntComponent = 5125;
constexpr std::size_t kPreviewMeshHeaderBytes = 44;

void append_u32(std::string& output, std::uint32_t value) {
    output.push_back(static_cast<char>(value & 0xff));
    output.push_back(static_cast<char>((value >> 8) & 0xff));
    output.push_back(static_cast<char>((value >> 16) & 0xff));
    output.push_back(static_cast<char>((value >> 24) & 0xff));
}

void append_f32(std::string& output, float value) {
    static_assert(sizeof(float) == sizeof(std::uint32_t), "float32 is required");
    std::uint32_t bits = 0;
    std::memcpy(&bits, &value, sizeof(bits));
    append_u32(output, bits);
}

void append_u16(std::string& output, std::uint16_t value) {
    output.push_back(static_cast<char>(value & 0xff));
    output.push_back(static_cast<char>((value >> 8) & 0xff));
}

float preview_coordinate(double value) {
    const float converted = static_cast<float>(value / 1000.0);
    if (!std::isfinite(converted)) {
        throw std::overflow_error("preview mesh coordinate exceeds float32 range");
    }
    return converted == 0.0F ? 0.0F : converted;
}

#ifdef CADFLOW_WITH_OCCT
struct PreviewMesh {
    std::vector<float> positions;
    std::vector<float> normals;
    std::vector<std::uint32_t> indices;
    float minimum[3] {
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
        std::numeric_limits<float>::infinity(),
    };
    float maximum[3] {
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
        -std::numeric_limits<float>::infinity(),
    };
};

PreviewMesh build_preview_mesh(
    const TopoDS_Shape& shape, double deflection) {
    BRepMesh_IncrementalMesh mesher(shape, deflection, false, 0.5, true);
    mesher.Perform();
    if (!mesher.IsDone()) {
        throw std::runtime_error("OCCT preview tessellation failed");
    }

    PreviewMesh mesh;
    for (TopExp_Explorer explorer(shape, TopAbs_FACE); explorer.More(); explorer.Next()) {
        const TopoDS_Face face = TopoDS::Face(explorer.Current());
        TopLoc_Location location;
        const Handle(Poly_Triangulation) triangulation =
            BRep_Tool::Triangulation(face, location);
        if (triangulation.IsNull()) {
            continue;
        }
        const std::size_t current_vertices = mesh.positions.size() / 3;
        const std::size_t face_vertices =
            static_cast<std::size_t>(triangulation->NbNodes());
        if (current_vertices + face_vertices
            > std::numeric_limits<std::uint32_t>::max()) {
            throw std::overflow_error("preview mesh has too many vertices");
        }
        const std::uint32_t base = static_cast<std::uint32_t>(current_vertices);
        for (int index = 1; index <= triangulation->NbNodes(); ++index) {
            const gp_Pnt point =
                triangulation->Node(index).Transformed(location.Transformation());
            const float converted[3] {
                preview_coordinate(point.X()),
                preview_coordinate(point.Z()),
                preview_coordinate(-point.Y()),
            };
            for (int axis = 0; axis < 3; ++axis) {
                mesh.positions.push_back(converted[axis]);
                mesh.minimum[axis] = std::min(mesh.minimum[axis], converted[axis]);
                mesh.maximum[axis] = std::max(mesh.maximum[axis], converted[axis]);
            }
        }
        for (int index = 1; index <= triangulation->NbTriangles(); ++index) {
            int first;
            int second;
            int third;
            triangulation->Triangle(index).Get(first, second, third);
            if (face.Orientation() == TopAbs_REVERSED) {
                std::swap(second, third);
            }
            mesh.indices.insert(
                mesh.indices.end(),
                {
                    base + static_cast<std::uint32_t>(first - 1),
                    base + static_cast<std::uint32_t>(second - 1),
                    base + static_cast<std::uint32_t>(third - 1),
                });
        }
    }
    if (mesh.positions.empty() || mesh.indices.empty()) {
        throw std::runtime_error("preview tessellation produced an empty mesh");
    }

    std::vector<std::array<std::uint32_t, 3>> triangles;
    triangles.reserve(mesh.indices.size() / 3);
    for (std::size_t offset = 0; offset < mesh.indices.size(); offset += 3) {
        const std::array<std::uint32_t, 3> original {
            mesh.indices[offset],
            mesh.indices[offset + 1],
            mesh.indices[offset + 2],
        };
        const std::array<std::uint32_t, 3> rotate_left {
            original[1], original[2], original[0],
        };
        const std::array<std::uint32_t, 3> rotate_right {
            original[2], original[0], original[1],
        };
        triangles.push_back(std::min({original, rotate_left, rotate_right}));
    }
    std::sort(triangles.begin(), triangles.end());
    mesh.indices.clear();
    mesh.indices.reserve(triangles.size() * 3);
    for (const auto& triangle : triangles) {
        mesh.indices.insert(mesh.indices.end(), triangle.begin(), triangle.end());
    }

    mesh.normals.assign(mesh.positions.size(), 0.0F);
    for (std::size_t offset = 0; offset < mesh.indices.size(); offset += 3) {
        const std::uint32_t first = mesh.indices[offset];
        const std::uint32_t second = mesh.indices[offset + 1];
        const std::uint32_t third = mesh.indices[offset + 2];
        const float ax = mesh.positions[second * 3] - mesh.positions[first * 3];
        const float ay = mesh.positions[second * 3 + 1] - mesh.positions[first * 3 + 1];
        const float az = mesh.positions[second * 3 + 2] - mesh.positions[first * 3 + 2];
        const float bx = mesh.positions[third * 3] - mesh.positions[first * 3];
        const float by = mesh.positions[third * 3 + 1] - mesh.positions[first * 3 + 1];
        const float bz = mesh.positions[third * 3 + 2] - mesh.positions[first * 3 + 2];
        const float normal[3] {
            ay * bz - az * by,
            az * bx - ax * bz,
            ax * by - ay * bx,
        };
        for (const std::uint32_t vertex : {first, second, third}) {
            mesh.normals[vertex * 3] += normal[0];
            mesh.normals[vertex * 3 + 1] += normal[1];
            mesh.normals[vertex * 3 + 2] += normal[2];
        }
    }
    for (std::size_t offset = 0; offset < mesh.normals.size(); offset += 3) {
        const double x = mesh.normals[offset];
        const double y = mesh.normals[offset + 1];
        const double z = mesh.normals[offset + 2];
        const double length = std::sqrt(x * x + y * y + z * z);
        if (length > 0.0 && std::isfinite(length)) {
            const float normalized[3] {
                static_cast<float>(x / length),
                static_cast<float>(y / length),
                static_cast<float>(z / length),
            };
            for (int axis = 0; axis < 3; ++axis) {
                mesh.normals[offset + axis] =
                    normalized[axis] == 0.0F ? 0.0F : normalized[axis];
            }
        } else {
            mesh.normals[offset] = 0.0F;
            mesh.normals[offset + 1] = 1.0F;
            mesh.normals[offset + 2] = 0.0F;
        }
    }
    return mesh;
}
#endif

}  // namespace

core::ShapeId import_step(core::Session& session, const std::string& path) {
    if (path.empty()) {
        throw std::invalid_argument("STEP path is empty");
    }
#if defined(CADFLOW_WITH_OCCT) && defined(CADFLOW_WITH_STEP)
    STEPControl_Reader reader;
    if (reader.ReadFile(path.c_str()) != IFSelect_RetDone || reader.TransferRoots() <= 0) {
        throw std::runtime_error("OCCT STEP import failed");
    }
    core::Shape output {core::Shape::Kind::Imported};
    output.native = reader.OneShape();
    if (output.native.IsNull()) {
        throw std::runtime_error("OCCT STEP import returned a null shape");
    }
    return core::store(session, std::move(output));
#else
    (void)session;
    throw std::runtime_error("STEP import requires the OCCT backend");
#endif
}

void export_step(
    const core::Session& session, core::ShapeId id, const std::string& path) {
    if (path.empty()) {
        throw std::invalid_argument("STEP path is empty");
    }
#if defined(CADFLOW_WITH_OCCT) && defined(CADFLOW_WITH_STEP)
    STEPControl_Writer writer;
    if (writer.Transfer(core::get_shape(session, id).native, STEPControl_AsIs)
            != IFSelect_RetDone
        || writer.Write(path.c_str()) != IFSelect_RetDone) {
        throw std::runtime_error("OCCT STEP export failed");
    }
#else
    (void)session;
    (void)id;
    throw std::runtime_error("STEP export requires the OCCT backend");
#endif
}

void export_stl(
    const core::Session& session, core::ShapeId id, const std::string& path, bool binary) {
    if (path.empty()) {
        throw std::invalid_argument("STL path is empty");
    }
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Shape& shape = core::get_shape(session, id).native;
    BRepMesh_IncrementalMesh mesher(shape, 0.1, false, 0.5, true);
    mesher.Perform();
    if (!mesher.IsDone()) {
        throw std::runtime_error("OCCT STL tessellation failed");
    }
    StlAPI_Writer writer;
    writer.ASCIIMode() = !binary;
    if (!writer.Write(shape, path.c_str())) {
        throw std::runtime_error("OCCT STL export failed");
    }
#else
    (void)session;
    (void)id;
    (void)binary;
    throw std::runtime_error("STL export requires the OCCT backend");
#endif
}

std::string mesh_json(
    const core::Session& session, core::ShapeId id, double deflection) {
    if (!(deflection > 0.0)) {
        throw std::invalid_argument("mesh deflection must be positive");
    }
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Shape& shape = core::get_shape(session, id).native;
    BRepMesh_IncrementalMesh mesher(shape, deflection, false, 0.5, true);
    std::vector<double> vertices;
    std::vector<int> triangles;
    for (TopExp_Explorer explorer(shape, TopAbs_FACE); explorer.More(); explorer.Next()) {
        const TopoDS_Face face = TopoDS::Face(explorer.Current());
        TopLoc_Location location;
        const Handle(Poly_Triangulation) triangulation =
            BRep_Tool::Triangulation(face, location);
        if (triangulation.IsNull()) {
            continue;
        }
        const int base = static_cast<int>(vertices.size() / 3);
        for (int index = 1; index <= triangulation->NbNodes(); ++index) {
            const gp_Pnt point =
                triangulation->Node(index).Transformed(location.Transformation());
            vertices.insert(vertices.end(), {point.X(), point.Y(), point.Z()});
        }
        for (int index = 1; index <= triangulation->NbTriangles(); ++index) {
            int first;
            int second;
            int third;
            triangulation->Triangle(index).Get(first, second, third);
            triangles.insert(
                triangles.end(), {base + first - 1, base + second - 1, base + third - 1});
        }
    }
    std::ostringstream output;
    output << std::setprecision(17) << "{\"vertices\":[";
    for (std::size_t index = 0; index < vertices.size(); ++index) {
        if (index) {
            output << ',';
        }
        output << vertices[index];
    }
    output << "],\"triangles\":[";
    for (std::size_t index = 0; index < triangles.size(); ++index) {
        if (index) {
            output << ',';
        }
        output << triangles[index];
    }
    output << "]}";
    return output.str();
#else
    (void)session;
    (void)id;
    throw std::runtime_error("mesh export requires the OCCT backend");
#endif
}

std::string preview_mesh_buffer(
    const core::Session& session, core::ShapeId id, double deflection) {
    if (!(deflection > 0.0) || !std::isfinite(deflection)) {
        throw std::invalid_argument("preview mesh deflection must be positive and finite");
    }
#ifdef CADFLOW_WITH_OCCT
    const PreviewMesh mesh =
        build_preview_mesh(core::get_shape(session, id).native, deflection);
    if (mesh.indices.size() / 3
        > std::numeric_limits<std::uint32_t>::max()) {
        throw std::overflow_error("preview mesh has too many triangles");
    }
    const std::uint32_t vertex_count =
        static_cast<std::uint32_t>(mesh.positions.size() / 3);
    const std::uint32_t triangle_count =
        static_cast<std::uint32_t>(mesh.indices.size() / 3);
    const std::uint32_t component_type = vertex_count <= 65536
        ? kUnsignedShortComponent
        : kUnsignedIntComponent;
    const std::size_t index_bytes = mesh.indices.size()
        * (component_type == kUnsignedShortComponent ? sizeof(std::uint16_t)
                                                     : sizeof(std::uint32_t));
    std::string output;
    output.reserve(
        kPreviewMeshHeaderBytes
        + mesh.positions.size() * sizeof(float)
        + mesh.normals.size() * sizeof(float)
        + index_bytes);
    output.append("CFMB", 4);
    append_u32(output, kPreviewMeshVersion);
    append_u32(output, vertex_count);
    append_u32(output, triangle_count);
    append_u32(output, component_type);
    for (const float value : mesh.minimum) {
        append_f32(output, value);
    }
    for (const float value : mesh.maximum) {
        append_f32(output, value);
    }
    for (const float value : mesh.positions) {
        append_f32(output, value);
    }
    for (const float value : mesh.normals) {
        append_f32(output, value);
    }
    if (component_type == kUnsignedShortComponent) {
        for (const std::uint32_t value : mesh.indices) {
            append_u16(output, static_cast<std::uint16_t>(value));
        }
    } else {
        for (const std::uint32_t value : mesh.indices) {
            append_u32(output, value);
        }
    }
    return output;
#else
    (void)session;
    (void)id;
    throw std::runtime_error("preview mesh export requires the OCCT backend");
#endif
}

}  // namespace cadflow::io
