#include "kernel/features.h"

#include <stdexcept>
#include <utility>

#ifdef CADFLOW_WITH_OCCT
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepOffsetAPI_MakePipeShell.hxx>
#include <BRepOffsetAPI_ThruSections.hxx>
#include <BRepPrimAPI_MakePrism.hxx>
#include <BRepPrimAPI_MakeRevol.hxx>
#include <TopoDS.hxx>
#include <gp_Ax1.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>
#endif

namespace cadflow::kernel {

using core::Shape;
using core::ShapeId;

ShapeId extrude(
    core::Session& session, ShapeId profile_id, double x, double y, double z) {
    const Shape& profile = core::get_shape(session, profile_id);
    if (profile.kind != Shape::Kind::Wire && profile.kind != Shape::Kind::Face) {
        throw std::invalid_argument("extrude input must be a wire or face");
    }
    if (x == 0.0 && y == 0.0 && z == 0.0) {
        throw std::invalid_argument("extrude vector must be non-zero");
    }
    Shape output {Shape::Kind::Extrude, 0, 0, 0, profile_id, 0};
    output.offset[0] = x;
    output.offset[1] = y;
    output.offset[2] = z;
    output.points = profile.points;
#ifdef CADFLOW_WITH_OCCT
    TopoDS_Shape base = profile.native;
    if (profile.kind == Shape::Kind::Wire) {
        BRepBuilderAPI_MakeFace face_builder(TopoDS::Wire(profile.native), true);
        if (!face_builder.IsDone()) {
            throw std::runtime_error("OCCT extrude profile is not planar");
        }
        base = face_builder.Face();
    }
    BRepPrimAPI_MakePrism builder(base, gp_Vec(x, y, z), true, true);
    builder.Build();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT extrusion failed");
    }
    output.native = builder.Shape();
#endif
    return core::store(session, std::move(output));
}

ShapeId revolve(
    core::Session& session,
    ShapeId profile_id,
    double ox,
    double oy,
    double oz,
    double ax,
    double ay,
    double az,
    double degrees) {
    const Shape& profile = core::get_shape(session, profile_id);
    if (profile.kind != Shape::Kind::Wire && profile.kind != Shape::Kind::Face) {
        throw std::invalid_argument("revolve input must be a wire or face");
    }
    if (ax == 0.0 && ay == 0.0 && az == 0.0) {
        throw std::invalid_argument("revolve axis must be non-zero");
    }
    if (!(degrees > 0.0 && degrees <= 360.0)) {
        throw std::invalid_argument("revolve angle must be in (0, 360]");
    }
    Shape output {Shape::Kind::Revolve, degrees, 0, 0, profile_id, 0};
    output.points = profile.points;
#ifdef CADFLOW_WITH_OCCT
    TopoDS_Shape base = profile.native;
    if (profile.kind == Shape::Kind::Wire) {
        BRepBuilderAPI_MakeFace face_builder(TopoDS::Wire(profile.native), true);
        if (!face_builder.IsDone()) {
            throw std::runtime_error("OCCT revolve profile is not planar");
        }
        base = face_builder.Face();
    }
    BRepPrimAPI_MakeRevol builder(
        base,
        gp_Ax1(gp_Pnt(ox, oy, oz), gp_Dir(ax, ay, az)),
        degrees * core::kPi / 180.0,
        true);
    builder.Build();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT revolution failed");
    }
    output.native = builder.Shape();
#else
    (void)ox;
    (void)oy;
    (void)oz;
#endif
    return core::store(session, std::move(output));
}

ShapeId loft(
    core::Session& session,
    const ShapeId* profile_ids,
    std::size_t profile_count,
    bool solid,
    bool ruled) {
    if (!profile_ids || profile_count < 2) {
        throw std::invalid_argument("loft requires at least two profiles");
    }
    Shape output {Shape::Kind::Loft};
    output.inputs.assign(profile_ids, profile_ids + profile_count);
#ifdef CADFLOW_WITH_OCCT
    BRepOffsetAPI_ThruSections builder(solid, ruled);
    for (std::size_t index = 0; index < profile_count; ++index) {
        const Shape& profile = core::get_shape(session, profile_ids[index]);
        if (profile.kind != Shape::Kind::Wire) {
            throw std::invalid_argument("loft profiles must be wires");
        }
        builder.AddWire(TopoDS::Wire(profile.native));
    }
    builder.Build();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT loft failed");
    }
    output.native = builder.Shape();
#else
    for (ShapeId id : output.inputs) {
        if (core::get_shape(session, id).kind != Shape::Kind::Wire) {
            throw std::invalid_argument("loft profiles must be wires");
        }
    }
    (void)solid;
    (void)ruled;
#endif
    return core::store(session, std::move(output));
}

ShapeId sweep(
    core::Session& session,
    ShapeId profile_id,
    ShapeId path_id,
    bool solid,
    bool frenet) {
    const Shape& profile = core::get_shape(session, profile_id);
    const Shape& path = core::get_shape(session, path_id);
    if (profile.kind != Shape::Kind::Wire || path.kind != Shape::Kind::Wire) {
        throw std::invalid_argument("sweep profile and path must be wires");
    }
    Shape output {Shape::Kind::Sweep, 0, 0, 0, profile_id, path_id};
#ifdef CADFLOW_WITH_OCCT
    BRepOffsetAPI_MakePipeShell builder(TopoDS::Wire(path.native));
    builder.SetMode(frenet);
    builder.Add(TopoDS::Wire(profile.native));
    builder.Build();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT sweep failed");
    }
    if (solid && !builder.MakeSolid()) {
        throw std::runtime_error("OCCT could not close the sweep into a solid");
    }
    output.native = builder.Shape();
#else
    (void)solid;
    (void)frenet;
#endif
    return core::store(session, std::move(output));
}

}  // namespace cadflow::kernel
