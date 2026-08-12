#include "kernel/surfaces.h"

#include <stdexcept>
#include <utility>

#ifdef CADFLOW_WITH_OCCT
#include <BRepBuilderAPI_MakeFace.hxx>
#include <GeomAPI_PointsToBSplineSurface.hxx>
#include <GeomAbs_Shape.hxx>
#include <Geom_BezierSurface.hxx>
#include <Geom_BSplineSurface.hxx>
#include <Precision.hxx>
#include <TColStd_Array2OfReal.hxx>
#include <TColgp_Array2OfPnt.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Pnt.hxx>
#endif

namespace cadflow::kernel {
namespace {

using core::Shape;
using core::ShapeId;

void validate_grid(const double* xyz, std::size_t rows, std::size_t columns) {
    if (!xyz) {
        throw std::invalid_argument("surface point grid is null");
    }
    if (rows < 2 || columns < 2) {
        throw std::invalid_argument("surface point grid must be at least 2 by 2");
    }
}

#ifdef CADFLOW_WITH_OCCT
TColgp_Array2OfPnt point_grid(
    const double* xyz, std::size_t rows, std::size_t columns) {
    TColgp_Array2OfPnt output(1, rows, 1, columns);
    for (std::size_t row = 0; row < rows; ++row) {
        for (std::size_t column = 0; column < columns; ++column) {
            const std::size_t offset = (row * columns + column) * 3;
            output.SetValue(
                static_cast<int>(row + 1),
                static_cast<int>(column + 1),
                gp_Pnt(xyz[offset], xyz[offset + 1], xyz[offset + 2]));
        }
    }
    return output;
}

ShapeId store_surface(
    core::Session& session,
    const double* xyz,
    std::size_t rows,
    std::size_t columns,
    const Handle(Geom_Surface)& surface) {
    BRepBuilderAPI_MakeFace builder(surface, Precision::Confusion());
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT could not create a face from the surface");
    }
    Shape output {
        Shape::Kind::Surface,
        static_cast<double>(rows),
        static_cast<double>(columns),
    };
    output.points.assign(xyz, xyz + rows * columns * 3);
    output.native = builder.Face();
    return core::store(session, std::move(output));
}
#endif

}  // namespace

core::ShapeId make_bezier_surface(
    core::Session& session,
    const double* xyz,
    std::size_t rows,
    std::size_t columns,
    const double* weights) {
    validate_grid(xyz, rows, columns);
    if (weights) {
        for (std::size_t index = 0; index < rows * columns; ++index) {
            if (!(weights[index] > 0.0)) {
                throw std::invalid_argument("Bezier surface weights must be positive");
            }
        }
    }
#ifdef CADFLOW_WITH_OCCT
    const TColgp_Array2OfPnt points = point_grid(xyz, rows, columns);
    Handle(Geom_Surface) surface;
    if (weights) {
        TColStd_Array2OfReal weight_grid(1, rows, 1, columns);
        for (std::size_t row = 0; row < rows; ++row) {
            for (std::size_t column = 0; column < columns; ++column) {
                weight_grid.SetValue(
                    static_cast<int>(row + 1),
                    static_cast<int>(column + 1),
                    weights[row * columns + column]);
            }
        }
        surface = new Geom_BezierSurface(points, weight_grid);
    } else {
        surface = new Geom_BezierSurface(points);
    }
    return store_surface(session, xyz, rows, columns, surface);
#else
    Shape output {
        Shape::Kind::Surface,
        static_cast<double>(rows),
        static_cast<double>(columns),
    };
    output.points.assign(xyz, xyz + rows * columns * 3);
    return core::store(session, std::move(output));
#endif
}

core::ShapeId fit_point_grid_surface(
    core::Session& session,
    const double* xyz,
    std::size_t rows,
    std::size_t columns,
    double tolerance,
    int degree_min,
    int degree_max) {
    validate_grid(xyz, rows, columns);
    if (!(tolerance > 0.0)) {
        throw std::invalid_argument("surface fitting tolerance must be positive");
    }
    if (degree_min < 1 || degree_max < degree_min) {
        throw std::invalid_argument("surface fitting degree range is invalid");
    }
#ifdef CADFLOW_WITH_OCCT
    const TColgp_Array2OfPnt points = point_grid(xyz, rows, columns);
    GeomAPI_PointsToBSplineSurface builder(
        points, degree_min, degree_max, GeomAbs_C2, tolerance);
    if (!builder.IsDone()) {
        throw std::runtime_error("OCCT point-grid surface fitting failed");
    }
    return store_surface(session, xyz, rows, columns, builder.Surface());
#else
    Shape output {
        Shape::Kind::Surface,
        static_cast<double>(rows),
        static_cast<double>(columns),
    };
    output.points.assign(xyz, xyz + rows * columns * 3);
    return core::store(session, std::move(output));
#endif
}

}  // namespace cadflow::kernel
