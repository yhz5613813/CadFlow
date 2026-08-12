#include "kernel/operations.h"

#include <stdexcept>
#include <utility>

#ifdef CADFLOW_WITH_OCCT
#include <BRepAlgoAPI_Common.hxx>
#include <BRepAlgoAPI_Cut.hxx>
#include <BRepAlgoAPI_Fuse.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <gp_Ax1.hxx>
#include <gp_Ax2.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#endif

namespace cadflow::kernel {

using core::Shape;
using core::ShapeId;

ShapeId boolean_operation(
    core::Session& session, Shape::Kind kind, ShapeId left, ShapeId right) {
    const Shape& left_shape = core::get_shape(session, left);
    const Shape& right_shape = core::get_shape(session, right);
#ifndef CADFLOW_WITH_OCCT
    (void)left_shape;
    (void)right_shape;
#endif
    Shape output {kind, 0, 0, 0, left, right};
#ifdef CADFLOW_WITH_OCCT
    if (kind == Shape::Kind::Cut) {
        BRepAlgoAPI_Cut builder(left_shape.native, right_shape.native);
        builder.Build();
        if (!builder.IsDone()) {
            throw std::runtime_error("OCCT cut failed");
        }
        output.native = builder.Shape();
    } else if (kind == Shape::Kind::Union) {
        BRepAlgoAPI_Fuse builder(left_shape.native, right_shape.native);
        builder.Build();
        if (!builder.IsDone()) {
            throw std::runtime_error("OCCT union failed");
        }
        output.native = builder.Shape();
    } else if (kind == Shape::Kind::Intersect) {
        BRepAlgoAPI_Common builder(left_shape.native, right_shape.native);
        builder.Build();
        if (!builder.IsDone()) {
            throw std::runtime_error("OCCT intersection failed");
        }
        output.native = builder.Shape();
    } else {
        throw std::invalid_argument("unsupported boolean operation kind");
    }
#endif
    return core::store(session, std::move(output));
}

ShapeId translate(
    core::Session& session, ShapeId id, double x, double y, double z) {
    const Shape& source = core::get_shape(session, id);
#ifndef CADFLOW_WITH_OCCT
    (void)source;
#endif
    Shape output {Shape::Kind::Translate, 0, 0, 0, id, 0};
    output.offset[0] = x;
    output.offset[1] = y;
    output.offset[2] = z;
#ifdef CADFLOW_WITH_OCCT
    gp_Trsf transform;
    transform.SetTranslation(gp_Vec(x, y, z));
    BRepBuilderAPI_Transform builder(source.native, transform, true);
    builder.Build();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT transform failed");
    }
    output.native = builder.Shape();
#endif
    return core::store(session, std::move(output));
}

ShapeId rotate(
    core::Session& session,
    ShapeId id,
    double ox,
    double oy,
    double oz,
    double ax,
    double ay,
    double az,
    double degrees) {
    const Shape& source = core::get_shape(session, id);
    if (ax == 0.0 && ay == 0.0 && az == 0.0) {
        throw std::invalid_argument("rotation axis must be non-zero");
    }
    Shape output {Shape::Kind::Rotate, degrees, 0, 0, id, 0};
#ifdef CADFLOW_WITH_OCCT
    gp_Trsf transform;
    transform.SetRotation(
        gp_Ax1(gp_Pnt(ox, oy, oz), gp_Dir(ax, ay, az)),
        degrees * core::kPi / 180.0);
    BRepBuilderAPI_Transform builder(source.native, transform, true);
    builder.Build();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT rotation failed");
    }
    output.native = builder.Shape();
#else
    (void)source;
    (void)ox;
    (void)oy;
    (void)oz;
#endif
    return core::store(session, std::move(output));
}

ShapeId mirror(
    core::Session& session,
    ShapeId id,
    double ox,
    double oy,
    double oz,
    double nx,
    double ny,
    double nz) {
    const Shape& source = core::get_shape(session, id);
    if (nx == 0.0 && ny == 0.0 && nz == 0.0) {
        throw std::invalid_argument("mirror plane normal must be non-zero");
    }
    Shape output {Shape::Kind::Mirror, 0, 0, 0, id, 0};
#ifdef CADFLOW_WITH_OCCT
    gp_Trsf transform;
    transform.SetMirror(gp_Ax2(gp_Pnt(ox, oy, oz), gp_Dir(nx, ny, nz)));
    BRepBuilderAPI_Transform builder(source.native, transform, true);
    builder.Build();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT mirror failed");
    }
    output.native = builder.Shape();
#else
    (void)source;
    (void)ox;
    (void)oy;
    (void)oz;
#endif
    return core::store(session, std::move(output));
}

ShapeId scale(
    core::Session& session,
    ShapeId id,
    double cx,
    double cy,
    double cz,
    double factor) {
    const Shape& source = core::get_shape(session, id);
    if (!(factor > 0.0)) {
        throw std::invalid_argument("scale factor must be positive");
    }
    Shape output {Shape::Kind::Scale, factor, 0, 0, id, 0};
#ifdef CADFLOW_WITH_OCCT
    gp_Trsf transform;
    transform.SetScale(gp_Pnt(cx, cy, cz), factor);
    BRepBuilderAPI_Transform builder(source.native, transform, true);
    builder.Build();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT scale failed");
    }
    output.native = builder.Shape();
#else
    (void)source;
    (void)cx;
    (void)cy;
    (void)cz;
#endif
    return core::store(session, std::move(output));
}

}  // namespace cadflow::kernel
