#include "kernel/queries.h"

#include <algorithm>
#include <cmath>
#include <stdexcept>

#ifdef CADFLOW_WITH_OCCT
#include <BRepBndLib.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRep_Tool.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <TopAbs.hxx>
#include <TopExp.hxx>
#include <TopTools_IndexedMapOfShape.hxx>
#include <TopoDS.hxx>
#include <gp_Pnt.hxx>
#endif

namespace cadflow::kernel {

using core::Box3;
using core::Shape;
using core::ShapeId;

#ifndef CADFLOW_WITH_OCCT
namespace {

double polygon_area(const std::vector<double>& points) {
    const std::size_t count = points.size() / 3;
    if (count < 3) {
        return 0.0;
    }
    double normal[3] {0.0, 0.0, 0.0};
    for (std::size_t index = 0; index < count; ++index) {
        const std::size_t next = (index + 1) % count;
        const double* first = &points[index * 3];
        const double* second = &points[next * 3];
        normal[0] += (first[1] - second[1]) * (first[2] + second[2]);
        normal[1] += (first[2] - second[2]) * (first[0] + second[0]);
        normal[2] += (first[0] - second[0]) * (first[1] + second[1]);
    }
    return 0.5 * std::sqrt(
        normal[0] * normal[0] + normal[1] * normal[1] + normal[2] * normal[2]);
}

double triangle_area(const double* first, const double* second, const double* third) {
    const double ab[3] = {
        second[0] - first[0],
        second[1] - first[1],
        second[2] - first[2],
    };
    const double ac[3] = {
        third[0] - first[0],
        third[1] - first[1],
        third[2] - first[2],
    };
    const double cross[3] = {
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    };
    return 0.5 * std::sqrt(
        cross[0] * cross[0] + cross[1] * cross[1] + cross[2] * cross[2]);
}

double point_grid_area(const Shape& shape) {
    const std::size_t rows = static_cast<std::size_t>(shape.a);
    const std::size_t columns = static_cast<std::size_t>(shape.b);
    double result = 0.0;
    for (std::size_t row = 0; row + 1 < rows; ++row) {
        for (std::size_t column = 0; column + 1 < columns; ++column) {
            const double* p00 = &shape.points[(row * columns + column) * 3];
            const double* p01 = &shape.points[(row * columns + column + 1) * 3];
            const double* p10 = &shape.points[((row + 1) * columns + column) * 3];
            const double* p11 = &shape.points[((row + 1) * columns + column + 1) * 3];
            result += triangle_area(p00, p01, p11) + triangle_area(p00, p11, p10);
        }
    }
    return result;
}

Box3 points_box(const std::vector<double>& points) {
    if (points.empty()) {
        throw std::invalid_argument("profile contains no points");
    }
    Box3 output {
        {points[0], points[1], points[2]},
        {points[0], points[1], points[2]},
    };
    for (std::size_t index = 3; index < points.size(); index += 3) {
        for (int axis = 0; axis < 3; ++axis) {
            output.min[axis] = std::min(output.min[axis], points[index + axis]);
            output.max[axis] = std::max(output.max[axis], points[index + axis]);
        }
    }
    return output;
}

}  // namespace
#endif

double volume(const core::Session& session, ShapeId id) {
    const Shape& shape = core::get_shape(session, id);
#ifdef CADFLOW_WITH_OCCT
    GProp_GProps properties;
    BRepGProp::VolumeProperties(shape.native, properties);
    return properties.Mass();
#else
    switch (shape.kind) {
    case Shape::Kind::Box:
        return shape.a * shape.b * shape.c;
    case Shape::Kind::Cylinder:
        return core::kPi * shape.a * shape.a * shape.b;
    case Shape::Kind::Sphere:
        return 4.0 * core::kPi * shape.a * shape.a * shape.a / 3.0;
    case Shape::Kind::Cone:
        return core::kPi * shape.c
            * (shape.a * shape.a + shape.a * shape.b + shape.b * shape.b) / 3.0;
    case Shape::Kind::Wire:
    case Shape::Kind::BSpline:
    case Shape::Kind::Face:
    case Shape::Kind::Surface:
    case Shape::Kind::Revolve:
    case Shape::Kind::Loft:
    case Shape::Kind::Sweep:
    case Shape::Kind::TwistedSweep:
    case Shape::Kind::RuledSurface:
    case Shape::Kind::FillingSurface:
    case Shape::Kind::GordonSurface:
    case Shape::Kind::Fillet:
    case Shape::Kind::Chamfer:
    case Shape::Kind::Shell:
    case Shape::Kind::Sewing:
    case Shape::Kind::Solid:
    case Shape::Kind::Imported:
        return 0.0;
    case Shape::Kind::Extrude: {
        const double length = std::sqrt(
            shape.offset[0] * shape.offset[0] + shape.offset[1] * shape.offset[1]
            + shape.offset[2] * shape.offset[2]);
        return polygon_area(core::get_shape(session, shape.left).points) * length;
    }
    case Shape::Kind::Cut:
        return std::max(0.0, volume(session, shape.left) - volume(session, shape.right));
    case Shape::Kind::Union:
        return volume(session, shape.left) + volume(session, shape.right);
    case Shape::Kind::Intersect:
        return std::min(volume(session, shape.left), volume(session, shape.right));
    case Shape::Kind::Translate:
    case Shape::Kind::Rotate:
    case Shape::Kind::Mirror:
        return volume(session, shape.left);
    case Shape::Kind::Scale:
        return volume(session, shape.left) * shape.a * shape.a * shape.a;
    }
    return 0.0;
#endif
}

double area(const core::Session& session, ShapeId id) {
    const Shape& shape = core::get_shape(session, id);
#ifdef CADFLOW_WITH_OCCT
    GProp_GProps properties;
    BRepGProp::SurfaceProperties(shape.native, properties);
    return properties.Mass();
#else
    switch (shape.kind) {
    case Shape::Kind::Box:
        return 2.0 * (shape.a * shape.b + shape.a * shape.c + shape.b * shape.c);
    case Shape::Kind::Cylinder:
        return 2.0 * core::kPi * shape.a * (shape.a + shape.b);
    case Shape::Kind::Sphere:
        return 4.0 * core::kPi * shape.a * shape.a;
    case Shape::Kind::Cone: {
        const double slant = std::hypot(shape.a - shape.b, shape.c);
        return core::kPi
            * (shape.a * shape.a + shape.b * shape.b + (shape.a + shape.b) * slant);
    }
    case Shape::Kind::Wire:
    case Shape::Kind::BSpline:
    case Shape::Kind::Extrude:
    case Shape::Kind::Revolve:
    case Shape::Kind::Loft:
    case Shape::Kind::Sweep:
    case Shape::Kind::TwistedSweep:
    case Shape::Kind::RuledSurface:
    case Shape::Kind::FillingSurface:
    case Shape::Kind::GordonSurface:
    case Shape::Kind::Imported:
    case Shape::Kind::Sewing:
    case Shape::Kind::Solid:
        return 0.0;
    case Shape::Kind::Fillet:
    case Shape::Kind::Chamfer:
    case Shape::Kind::Shell:
        return area(session, shape.left);
    case Shape::Kind::Face:
        return polygon_area(core::get_shape(session, shape.left).points);
    case Shape::Kind::Surface:
        return point_grid_area(shape);
    case Shape::Kind::Cut:
        return std::max(0.0, area(session, shape.left) + area(session, shape.right));
    case Shape::Kind::Union:
        return area(session, shape.left) + area(session, shape.right);
    case Shape::Kind::Intersect:
        return std::min(area(session, shape.left), area(session, shape.right));
    case Shape::Kind::Translate:
    case Shape::Kind::Rotate:
    case Shape::Kind::Mirror:
        return area(session, shape.left);
    case Shape::Kind::Scale:
        return area(session, shape.left) * shape.a * shape.a;
    }
    return 0.0;
#endif
}

double length(const core::Session& session, ShapeId id) {
    const Shape& shape = core::get_shape(session, id);
#ifdef CADFLOW_WITH_OCCT
    TopTools_IndexedMapOfShape edges;
    TopExp::MapShapes(shape.native, TopAbs_EDGE, edges);
    double result = 0.0;
    for (int index = 1; index <= edges.Extent(); ++index) {
        GProp_GProps properties;
        BRepGProp::LinearProperties(edges(index), properties);
        result += properties.Mass();
    }
    return result;
#else
    if (shape.kind == Shape::Kind::Box) {
        return 4.0 * (shape.a + shape.b + shape.c);
    }
    if (shape.kind == Shape::Kind::Cylinder) {
        return 4.0 * core::kPi * shape.a + shape.b;
    }
    if (shape.kind == Shape::Kind::Sphere) {
        return 0.0;
    }
    if (shape.kind == Shape::Kind::Cone) {
        const double slant = std::hypot(shape.a - shape.b, shape.c);
        return 2.0 * core::kPi * (shape.a + shape.b) + slant;
    }
    if (shape.kind == Shape::Kind::Wire) {
        double result = 0.0;
        for (std::size_t index = 3; index < shape.points.size(); index += 3) {
            const double dx = shape.points[index] - shape.points[index - 3];
            const double dy = shape.points[index + 1] - shape.points[index - 2];
            const double dz = shape.points[index + 2] - shape.points[index - 1];
            result += std::sqrt(dx * dx + dy * dy + dz * dz);
        }
        if (shape.closed && shape.points.size() >= 6) {
            const std::size_t last = shape.points.size() - 3;
            const double dx = shape.points[0] - shape.points[last];
            const double dy = shape.points[1] - shape.points[last + 1];
            const double dz = shape.points[2] - shape.points[last + 2];
            result += std::sqrt(dx * dx + dy * dy + dz * dz);
        }
        return result;
    }
    if (shape.kind == Shape::Kind::Translate || shape.kind == Shape::Kind::Rotate
        || shape.kind == Shape::Kind::Mirror) {
        return length(session, shape.left);
    }
    if (shape.kind == Shape::Kind::Face) {
        return length(session, shape.left);
    }
    if (shape.kind == Shape::Kind::Surface) {
        return 0.0;
    }
    if (shape.kind == Shape::Kind::Fillet || shape.kind == Shape::Kind::Chamfer
        || shape.kind == Shape::Kind::Shell) {
        return length(session, shape.left);
    }
    if (shape.kind == Shape::Kind::Extrude) {
        const Shape& profile = core::get_shape(session, shape.left);
        const double height = std::sqrt(
            shape.offset[0] * shape.offset[0] + shape.offset[1] * shape.offset[1]
            + shape.offset[2] * shape.offset[2]);
        return 2.0 * length(session, shape.left)
            + static_cast<double>(profile.points.size() / 3) * height;
    }
    if (shape.kind == Shape::Kind::Scale) {
        return length(session, shape.left) * shape.a;
    }
    if (shape.kind == Shape::Kind::Imported) {
        return 0.0;
    }
    return 0.0;
#endif
}

double distance(const core::Session& session, ShapeId left_id, ShapeId right_id) {
#ifdef CADFLOW_WITH_OCCT
    BRepExtrema_DistShapeShape operation(
        core::get_shape(session, left_id).native,
        core::get_shape(session, right_id).native);
    operation.Perform();
    if (!operation.IsDone()) {
        throw std::runtime_error("OCCT distance calculation failed");
    }
    return operation.Value();
#else
    const Box3 left = bounding_box(session, left_id);
    const Box3 right = bounding_box(session, right_id);
    double squared = 0.0;
    for (int axis = 0; axis < 3; ++axis) {
        const double separation = std::max(
            {0.0, right.min[axis] - left.max[axis], left.min[axis] - right.max[axis]});
        squared += separation * separation;
    }
    return std::sqrt(squared);
#endif
}

Box3 bounding_box(const core::Session& session, ShapeId id) {
    const Shape& shape = core::get_shape(session, id);
#ifdef CADFLOW_WITH_OCCT
    Bnd_Box native_box;
    BRepBndLib::Add(shape.native, native_box, true);
    Box3 output;
    native_box.Get(
        output.min[0],
        output.min[1],
        output.min[2],
        output.max[0],
        output.max[1],
        output.max[2]);
    return output;
#else
    switch (shape.kind) {
    case Shape::Kind::Box:
        return Box3 {{0.0, 0.0, 0.0}, {shape.a, shape.b, shape.c}};
    case Shape::Kind::Cylinder:
        return Box3 {{-shape.a, -shape.a, 0.0}, {shape.a, shape.a, shape.b}};
    case Shape::Kind::Sphere:
        return Box3 {{-shape.a, -shape.a, -shape.a}, {shape.a, shape.a, shape.a}};
    case Shape::Kind::Cone: {
        const double radius = std::max(shape.a, shape.b);
        return Box3 {{-radius, -radius, 0.0}, {radius, radius, shape.c}};
    }
    case Shape::Kind::Wire:
    case Shape::Kind::BSpline:
        return points_box(shape.points);
    case Shape::Kind::Surface:
    case Shape::Kind::RuledSurface:
    case Shape::Kind::FillingSurface:
    case Shape::Kind::GordonSurface:
        return points_box(shape.points);
    case Shape::Kind::Face:
    case Shape::Kind::Revolve:
        return bounding_box(session, shape.left);
    case Shape::Kind::Extrude: {
        const Box3 source = bounding_box(session, shape.left);
        Box3 output = source;
        for (int axis = 0; axis < 3; ++axis) {
            output.min[axis] = std::min(source.min[axis], source.min[axis] + shape.offset[axis]);
            output.max[axis] = std::max(source.max[axis], source.max[axis] + shape.offset[axis]);
        }
        return output;
    }
    case Shape::Kind::Loft: {
        if (shape.inputs.empty()) {
            throw std::invalid_argument("loft contains no profiles");
        }
        Box3 output = bounding_box(session, shape.inputs.front());
        for (std::size_t index = 1; index < shape.inputs.size(); ++index) {
            const Box3 profile = bounding_box(session, shape.inputs[index]);
            for (int axis = 0; axis < 3; ++axis) {
                output.min[axis] = std::min(output.min[axis], profile.min[axis]);
                output.max[axis] = std::max(output.max[axis], profile.max[axis]);
            }
        }
        return output;
    }
    case Shape::Kind::Sweep:
    case Shape::Kind::TwistedSweep: {
        Box3 output = bounding_box(session, shape.left);
        const Box3 path = bounding_box(session, shape.right);
        const double radius[3] = {
            (output.max[0] - output.min[0]) / 2.0,
            (output.max[1] - output.min[1]) / 2.0,
            (output.max[2] - output.min[2]) / 2.0,
        };
        for (int axis = 0; axis < 3; ++axis) {
            output.min[axis] = path.min[axis] - radius[axis];
            output.max[axis] = path.max[axis] + radius[axis];
        }
        return output;
    }
    case Shape::Kind::Cut:
        return bounding_box(session, shape.left);
    case Shape::Kind::Union: {
        const Box3 left = bounding_box(session, shape.left);
        const Box3 right = bounding_box(session, shape.right);
        Box3 output;
        for (int axis = 0; axis < 3; ++axis) {
            output.min[axis] = std::min(left.min[axis], right.min[axis]);
            output.max[axis] = std::max(left.max[axis], right.max[axis]);
        }
        return output;
    }
    case Shape::Kind::Intersect: {
        const Box3 left = bounding_box(session, shape.left);
        const Box3 right = bounding_box(session, shape.right);
        Box3 output;
        for (int axis = 0; axis < 3; ++axis) {
            output.min[axis] = std::max(left.min[axis], right.min[axis]);
            output.max[axis] = std::min(left.max[axis], right.max[axis]);
        }
        return output;
    }
    case Shape::Kind::Translate: {
        Box3 output = bounding_box(session, shape.left);
        for (int axis = 0; axis < 3; ++axis) {
            output.min[axis] += shape.offset[axis];
            output.max[axis] += shape.offset[axis];
        }
        return output;
    }
    case Shape::Kind::Rotate:
    case Shape::Kind::Mirror:
    case Shape::Kind::Scale:
    case Shape::Kind::Fillet:
    case Shape::Kind::Chamfer:
    case Shape::Kind::Shell:
    case Shape::Kind::Sewing:
    case Shape::Kind::Solid:
        return bounding_box(session, shape.left);
    case Shape::Kind::Imported:
        throw std::runtime_error("STEP import requires the OCCT backend");
    }
    return {};
#endif
}

void center_of_mass(const core::Session& session, ShapeId id, double output[3]) {
    if (!output) {
        throw std::invalid_argument("center-of-mass output is null");
    }
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Shape& shape = core::get_shape(session, id).native;
    const TopAbs_ShapeEnum shape_type = shape.ShapeType();
    if (shape_type == TopAbs_VERTEX) {
        const gp_Pnt point = BRep_Tool::Pnt(TopoDS::Vertex(shape));
        output[0] = point.X();
        output[1] = point.Y();
        output[2] = point.Z();
        return;
    }

    GProp_GProps properties;
    if (shape_type == TopAbs_SOLID || shape_type == TopAbs_COMPSOLID
        || shape_type == TopAbs_COMPOUND) {
        BRepGProp::VolumeProperties(shape, properties);
        if (std::abs(properties.Mass()) <= 1e-12 && shape_type == TopAbs_COMPOUND) {
            BRepGProp::SurfaceProperties(shape, properties);
        }
        if (std::abs(properties.Mass()) <= 1e-12 && shape_type == TopAbs_COMPOUND) {
            BRepGProp::LinearProperties(shape, properties);
        }
    } else if (shape_type == TopAbs_FACE || shape_type == TopAbs_SHELL) {
        BRepGProp::SurfaceProperties(shape, properties);
    } else if (shape_type == TopAbs_WIRE || shape_type == TopAbs_EDGE) {
        BRepGProp::LinearProperties(shape, properties);
    }
    if (std::abs(properties.Mass()) > 1e-12) {
        const gp_Pnt point = properties.CentreOfMass();
        output[0] = point.X();
        output[1] = point.Y();
        output[2] = point.Z();
        return;
    }
#endif
    const Box3 box = bounding_box(session, id);
    for (int axis = 0; axis < 3; ++axis) {
        output[axis] = (box.min[axis] + box.max[axis]) / 2.0;
    }
}

const char* kind(const Shape& shape) {
    switch (shape.kind) {
    case Shape::Kind::Box: return "box";
    case Shape::Kind::Cylinder: return "cylinder";
    case Shape::Kind::Sphere: return "sphere";
    case Shape::Kind::Cone: return "cone";
    case Shape::Kind::Wire: return "wire";
    case Shape::Kind::Face: return "face";
    case Shape::Kind::Surface: return "surface";
    case Shape::Kind::BSpline: return "bspline";
    case Shape::Kind::Extrude: return "extrude";
    case Shape::Kind::Revolve: return "revolve";
    case Shape::Kind::Loft: return "loft";
    case Shape::Kind::Sweep: return "sweep";
    case Shape::Kind::TwistedSweep: return "twisted_sweep";
    case Shape::Kind::RuledSurface: return "ruled_surface";
    case Shape::Kind::FillingSurface: return "filling_surface";
    case Shape::Kind::GordonSurface: return "gordon_surface";
    case Shape::Kind::Fillet: return "fillet";
    case Shape::Kind::Chamfer: return "chamfer";
    case Shape::Kind::Shell: return "shell";
    case Shape::Kind::Sewing: return "sewing";
    case Shape::Kind::Solid: return "solid";
    case Shape::Kind::Cut: return "cut";
    case Shape::Kind::Union: return "union";
    case Shape::Kind::Intersect: return "intersect";
    case Shape::Kind::Translate: return "translate";
    case Shape::Kind::Rotate: return "rotate";
    case Shape::Kind::Mirror: return "mirror";
    case Shape::Kind::Scale: return "scale";
    case Shape::Kind::Imported: return "imported";
    }
    return "unknown";
}

void topology_counts(
    const core::Session& session, ShapeId id, unsigned long long output[4]) {
    if (!output) {
        throw std::invalid_argument("topology count output is null");
    }
#ifdef CADFLOW_WITH_OCCT
    const TopoDS_Shape& shape = core::get_shape(session, id).native;
    const TopAbs_ShapeEnum kinds[4] = {
        TopAbs_VERTEX,
        TopAbs_EDGE,
        TopAbs_FACE,
        TopAbs_SOLID,
    };
    for (int index = 0; index < 4; ++index) {
        TopTools_IndexedMapOfShape items;
        TopExp::MapShapes(shape, kinds[index], items);
        output[index] = static_cast<unsigned long long>(items.Extent());
    }
#else
    (void)core::get_shape(session, id);
    output[0] = output[1] = output[2] = output[3] = 0;
#endif
}

}  // namespace cadflow::kernel
