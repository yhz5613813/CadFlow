#include "kernel/construction.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>
#include <utility>

#ifdef CADFLOW_WITH_OCCT
#include <BRepBuilderAPI_MakeEdge.hxx>
#include <BRepBuilderAPI_MakeFace.hxx>
#include <BRepBuilderAPI_MakePolygon.hxx>
#include <BRepBuilderAPI_MakeWire.hxx>
#include <BRepPrimAPI_MakeBox.hxx>
#include <BRepPrimAPI_MakeCone.hxx>
#include <BRepPrimAPI_MakeCylinder.hxx>
#include <BRepPrimAPI_MakeSphere.hxx>
#include <GC_MakeArcOfCircle.hxx>
#include <GeomAPI_Interpolate.hxx>
#include <TColgp_HArray1OfPnt.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Edge.hxx>
#include <gp_Ax2.hxx>
#include <gp_Circ.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#endif

namespace cadflow::kernel {

using core::Shape;
using core::ShapeId;

ShapeId make_box(core::Session& session, double width, double depth, double height) {
    if (!(width > 0.0 && depth > 0.0 && height > 0.0)) {
        throw std::invalid_argument("box dimensions must be positive");
    }
    Shape output {Shape::Kind::Box, width, depth, height};
#ifdef CADFLOW_WITH_OCCT
    output.native = BRepPrimAPI_MakeBox(width, depth, height).Shape();
#endif
    return core::store(session, std::move(output));
}

ShapeId make_cylinder(core::Session& session, double radius, double height) {
    if (!(radius > 0.0 && height > 0.0)) {
        throw std::invalid_argument("cylinder radius and height must be positive");
    }
    Shape output {Shape::Kind::Cylinder, radius, height};
#ifdef CADFLOW_WITH_OCCT
    output.native = BRepPrimAPI_MakeCylinder(radius, height).Shape();
#endif
    return core::store(session, std::move(output));
}

ShapeId make_sphere(core::Session& session, double radius) {
    if (!(radius > 0.0)) {
        throw std::invalid_argument("sphere radius must be positive");
    }
    Shape output {Shape::Kind::Sphere, radius};
#ifdef CADFLOW_WITH_OCCT
    output.native = BRepPrimAPI_MakeSphere(radius).Shape();
#endif
    return core::store(session, std::move(output));
}

ShapeId make_cone(
    core::Session& session, double radius1, double radius2, double height) {
    if (radius1 < 0.0 || radius2 < 0.0 || !(height > 0.0)
        || (radius1 == 0.0 && radius2 == 0.0)) {
        throw std::invalid_argument(
            "cone radii must be non-negative, one radius must be positive, "
            "and height must be positive");
    }
    Shape output {Shape::Kind::Cone, radius1, radius2, height};
#ifdef CADFLOW_WITH_OCCT
    output.native = BRepPrimAPI_MakeCone(radius1, radius2, height).Shape();
#endif
    return core::store(session, std::move(output));
}

ShapeId make_polyline(
    core::Session& session, const double* xyz, std::size_t point_count, bool closed) {
    const std::size_t minimum = closed ? 3 : 2;
    if (!xyz || point_count < minimum) {
        throw std::invalid_argument(
            closed ? "closed polyline requires at least three points"
                   : "polyline requires at least two points");
    }
    Shape output {Shape::Kind::Wire};
    output.closed = closed;
    output.points.assign(xyz, xyz + point_count * 3);
#ifdef CADFLOW_WITH_OCCT
    BRepBuilderAPI_MakePolygon builder;
    for (std::size_t index = 0; index < point_count; ++index) {
        builder.Add(gp_Pnt(xyz[index * 3], xyz[index * 3 + 1], xyz[index * 3 + 2]));
    }
    if (closed) {
        builder.Close();
    }
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT polyline construction failed");
    }
    output.native = builder.Wire();
#endif
    return core::store(session, std::move(output));
}

ShapeId make_circle_profile(
    core::Session& session,
    double cx,
    double cy,
    double cz,
    double nx,
    double ny,
    double nz,
    double radius) {
    if (!(radius > 0.0)) {
        throw std::invalid_argument("circle radius must be positive");
    }
    const double normal_length = std::sqrt(nx * nx + ny * ny + nz * nz);
    if (!(normal_length > 0.0)) {
        throw std::invalid_argument("circle normal must be non-zero");
    }
    Shape output {Shape::Kind::Wire};
    output.a = radius;
    output.closed = true;
#ifdef CADFLOW_WITH_OCCT
    const gp_Circ circle(gp_Ax2(gp_Pnt(cx, cy, cz), gp_Dir(nx, ny, nz)), radius);
    const TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(circle).Edge();
    output.native = BRepBuilderAPI_MakeWire(edge).Wire();
#else
    nx /= normal_length;
    ny /= normal_length;
    nz /= normal_length;
    double ux = std::abs(nx) < 0.9 ? 1.0 : 0.0;
    double uy = std::abs(nx) < 0.9 ? 0.0 : 1.0;
    double uz = 0.0;
    const double projection = ux * nx + uy * ny + uz * nz;
    ux -= projection * nx;
    uy -= projection * ny;
    uz -= projection * nz;
    const double u_length = std::sqrt(ux * ux + uy * uy + uz * uz);
    ux /= u_length;
    uy /= u_length;
    uz /= u_length;
    const double vx = ny * uz - nz * uy;
    const double vy = nz * ux - nx * uz;
    const double vz = nx * uy - ny * ux;
    for (int index = 0; index < 64; ++index) {
        const double angle = 2.0 * core::kPi * static_cast<double>(index) / 64.0;
        output.points.insert(output.points.end(), {
            cx + radius * (std::cos(angle) * ux + std::sin(angle) * vx),
            cy + radius * (std::cos(angle) * uy + std::sin(angle) * vy),
            cz + radius * (std::cos(angle) * uz + std::sin(angle) * vz),
        });
    }
#endif
    return core::store(session, std::move(output));
}

ShapeId make_arc(core::Session& session, const double points_xyz[9]) {
    if (!points_xyz) {
        throw std::invalid_argument("arc points are null");
    }
    Shape output {Shape::Kind::Wire};
    output.points.assign(points_xyz, points_xyz + 9);
#ifdef CADFLOW_WITH_OCCT
    GC_MakeArcOfCircle builder(
        gp_Pnt(points_xyz[0], points_xyz[1], points_xyz[2]),
        gp_Pnt(points_xyz[3], points_xyz[4], points_xyz[5]),
        gp_Pnt(points_xyz[6], points_xyz[7], points_xyz[8]));
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT three-point arc construction failed");
    }
    const TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(builder.Value()).Edge();
    output.native = BRepBuilderAPI_MakeWire(edge).Wire();
#endif
    return core::store(session, std::move(output));
}

ShapeId make_interpolated_curve(
    core::Session& session,
    const double* xyz,
    std::size_t point_count,
    bool periodic,
    double tolerance) {
    const std::size_t minimum = periodic ? 3 : 2;
    if (!xyz || point_count < minimum) {
        throw std::invalid_argument(
            periodic ? "periodic interpolation requires at least three points"
                     : "interpolation requires at least two points");
    }
    if (!(tolerance > 0.0)) {
        throw std::invalid_argument("interpolation tolerance must be positive");
    }
    Shape output {Shape::Kind::Wire};
    output.closed = periodic;
    output.points.assign(xyz, xyz + point_count * 3);
#ifdef CADFLOW_WITH_OCCT
    Handle(TColgp_HArray1OfPnt) points = new TColgp_HArray1OfPnt(1, point_count);
    for (std::size_t index = 0; index < point_count; ++index) {
        points->SetValue(
            static_cast<int>(index + 1),
            gp_Pnt(xyz[index * 3], xyz[index * 3 + 1], xyz[index * 3 + 2]));
    }
    GeomAPI_Interpolate builder(points, periodic, tolerance);
    builder.Perform();
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT curve interpolation failed");
    }
    const TopoDS_Edge edge = BRepBuilderAPI_MakeEdge(builder.Curve()).Edge();
    output.native = BRepBuilderAPI_MakeWire(edge).Wire();
#endif
    return core::store(session, std::move(output));
}

ShapeId make_helix(
    core::Session& session,
    double pitch,
    double height,
    double radius,
    double cx,
    double cy,
    double cz,
    double dx,
    double dy,
    double dz) {
    if (!(pitch > 0.0 && height > 0.0 && radius > 0.0)) {
        throw std::invalid_argument("helix pitch, height, and radius must be positive");
    }
    const double direction_length = std::sqrt(dx * dx + dy * dy + dz * dz);
    if (!(direction_length > 0.0)) {
        throw std::invalid_argument("helix direction must be non-zero");
    }
    dx /= direction_length;
    dy /= direction_length;
    dz /= direction_length;

    double ux = std::abs(dx) < 0.9 ? 1.0 : 0.0;
    double uy = std::abs(dx) < 0.9 ? 0.0 : 1.0;
    double uz = 0.0;
    const double projection = ux * dx + uy * dy + uz * dz;
    ux -= projection * dx;
    uy -= projection * dy;
    uz -= projection * dz;
    const double u_length = std::sqrt(ux * ux + uy * uy + uz * uz);
    ux /= u_length;
    uy /= u_length;
    uz /= u_length;
    const double vx = dy * uz - dz * uy;
    const double vy = dz * ux - dx * uz;
    const double vz = dx * uy - dy * ux;

    const double turns = height / pitch;
    const std::size_t segments = std::max<std::size_t>(
        16, static_cast<std::size_t>(std::ceil(turns * 32.0)));
    std::vector<double> points;
    points.reserve((segments + 1) * 3);
    for (std::size_t index = 0; index <= segments; ++index) {
        const double fraction = static_cast<double>(index) / static_cast<double>(segments);
        const double angle = 2.0 * core::kPi * turns * fraction;
        const double axial = height * fraction;
        points.insert(points.end(), {
            cx + radius * (std::cos(angle) * ux + std::sin(angle) * vx) + axial * dx,
            cy + radius * (std::cos(angle) * uy + std::sin(angle) * vy) + axial * dy,
            cz + radius * (std::cos(angle) * uz + std::sin(angle) * vz) + axial * dz,
        });
    }
    return make_interpolated_curve(
        session, points.data(), points.size() / 3, false, 1e-7);
}

ShapeId make_face(core::Session& session, ShapeId wire_id) {
    const Shape& wire = core::get_shape(session, wire_id);
    if (wire.kind != Shape::Kind::Wire) {
        throw std::invalid_argument("face input must be a wire");
    }
    Shape output {Shape::Kind::Face, 0, 0, 0, wire_id, 0};
    output.points = wire.points;
#ifdef CADFLOW_WITH_OCCT
    BRepBuilderAPI_MakeFace builder(TopoDS::Wire(wire.native), true);
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT face construction failed");
    }
    output.native = builder.Face();
#endif
    return core::store(session, std::move(output));
}

}  // namespace cadflow::kernel
