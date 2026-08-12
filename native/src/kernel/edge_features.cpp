#include "kernel/edge_features.h"

#include <cmath>
#include <stdexcept>
#include <utility>
#include <vector>

#ifdef CADFLOW_WITH_OCCT
#include <BRepFilletAPI_MakeChamfer.hxx>
#include <BRepFilletAPI_MakeFillet.hxx>
#include <BRepOffsetAPI_MakeThickSolid.hxx>
#include <BRepOffset_Mode.hxx>
#include <GeomAbs_JoinType.hxx>
#include <TopAbs.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopTools_ListOfShape.hxx>
#include <TopoDS.hxx>
#endif

namespace cadflow::kernel {
namespace {

using core::Shape;
using core::ShapeId;

#ifdef CADFLOW_WITH_OCCT
std::vector<std::size_t> selected_indices(
    const std::size_t* indices, std::size_t count, int available, bool select_all) {
    if (!indices && count != 0) {
        throw std::invalid_argument("subshape index array is null");
    }
    std::vector<std::size_t> output;
    if (count == 0 && select_all) {
        output.reserve(available);
        for (int index = 0; index < available; ++index) {
            output.push_back(static_cast<std::size_t>(index));
        }
    } else {
        if (count != 0) {
            output.assign(indices, indices + count);
        }
    }
    std::vector<bool> seen(static_cast<std::size_t>(available), false);
    for (std::size_t index : output) {
        if (index >= static_cast<std::size_t>(available)) {
            throw std::out_of_range("subshape index is out of range");
        }
        if (seen[index]) {
            throw std::invalid_argument("subshape indices must be unique");
        }
        seen[index] = true;
    }
    if (output.empty()) {
        throw std::invalid_argument("at least one subshape must be selected");
    }
    return output;
}
#endif

}  // namespace

ShapeId fillet(
    core::Session& session,
    ShapeId id,
    double radius,
    const std::size_t* edge_indices,
    std::size_t edge_count) {
    if (!(std::isfinite(radius) && radius > 0.0)) {
        throw std::invalid_argument("fillet radius must be finite and positive");
    }
#ifdef CADFLOW_WITH_OCCT
    const Shape& source = core::get_shape(session, id);
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(source.native, TopAbs_EDGE, edges);
    const std::vector<std::size_t> selected =
        selected_indices(edge_indices, edge_count, edges.Extent(), true);
    BRepFilletAPI_MakeFillet builder(source.native);
    for (std::size_t index : selected) {
        builder.Add(radius, TopoDS::Edge(edges(static_cast<int>(index + 1))));
    }
    builder.Build();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT fillet failed");
    }
    Shape output {Shape::Kind::Fillet, radius, 0, 0, id, 0};
    output.native = builder.Shape();
    return core::store(session, std::move(output));
#else
    (void)session;
    (void)id;
    (void)edge_indices;
    (void)edge_count;
    throw std::runtime_error("fillet requires the OCCT backend");
#endif
}

ShapeId chamfer(
    core::Session& session,
    ShapeId id,
    double distance,
    const std::size_t* edge_indices,
    std::size_t edge_count) {
    if (!(std::isfinite(distance) && distance > 0.0)) {
        throw std::invalid_argument("chamfer distance must be finite and positive");
    }
#ifdef CADFLOW_WITH_OCCT
    const Shape& source = core::get_shape(session, id);
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(source.native, TopAbs_EDGE, edges);
    const std::vector<std::size_t> selected =
        selected_indices(edge_indices, edge_count, edges.Extent(), true);
    BRepFilletAPI_MakeChamfer builder(source.native);
    for (std::size_t index : selected) {
        builder.Add(distance, TopoDS::Edge(edges(static_cast<int>(index + 1))));
    }
    builder.Build();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT chamfer failed");
    }
    Shape output {Shape::Kind::Chamfer, distance, 0, 0, id, 0};
    output.native = builder.Shape();
    return core::store(session, std::move(output));
#else
    (void)session;
    (void)id;
    (void)edge_indices;
    (void)edge_count;
    throw std::runtime_error("chamfer requires the OCCT backend");
#endif
}

ShapeId shell(
    core::Session& session,
    ShapeId id,
    double thickness,
    const std::size_t* face_indices,
    std::size_t face_count,
    double tolerance) {
    if (!(std::isfinite(thickness) && thickness > 0.0)) {
        throw std::invalid_argument("shell thickness must be finite and positive");
    }
    if (!(std::isfinite(tolerance) && tolerance > 0.0)) {
        throw std::invalid_argument("shell tolerance must be finite and positive");
    }
#ifdef CADFLOW_WITH_OCCT
    const Shape& source = core::get_shape(session, id);
    TopTools_IndexedMapOfShape faces;
    TopExp::MapShapes(source.native, TopAbs_FACE, faces);
    const std::vector<std::size_t> selected =
        selected_indices(face_indices, face_count, faces.Extent(), false);
    TopTools_ListOfShape closing_faces;
    for (std::size_t index : selected) {
        closing_faces.Append(faces(static_cast<int>(index + 1)));
    }
    BRepOffsetAPI_MakeThickSolid builder;
    builder.MakeThickSolidByJoin(
        source.native,
        closing_faces,
        -std::abs(thickness),
        tolerance,
        BRepOffset_Skin,
        false,
        false,
        GeomAbs_Arc,
        false);
    builder.Build();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT shell failed");
    }
    Shape output {Shape::Kind::Shell, thickness, tolerance, 0, id, 0};
    output.native = builder.Shape();
    return core::store(session, std::move(output));
#else
    (void)session;
    (void)id;
    (void)face_indices;
    (void)face_count;
    throw std::runtime_error("shell requires the OCCT backend");
#endif
}

}  // namespace cadflow::kernel
