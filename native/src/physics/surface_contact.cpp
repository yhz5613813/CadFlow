#include "physics/surface_contact.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <limits>
#include <stdexcept>
#include <string>

#ifdef CADFLOW_WITH_OCCT
#include <BRepAdaptor_Surface.hxx>
#include <BRepBndLib.hxx>
#include <BRepBuilderAPI_Transform.hxx>
#include <BRepCheck_Analyzer.hxx>
#include <BRepExtrema_DistShapeShape.hxx>
#include <BRepGProp.hxx>
#include <BRepTools.hxx>
#include <BRep_Builder.hxx>
#include <Bnd_Box.hxx>
#include <GProp_GProps.hxx>
#include <GeomAbs_SurfaceType.hxx>
#include <TopAbs.hxx>
#include <TopoDS.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Dir.hxx>
#include <gp_Pnt.hxx>
#include <gp_Trsf.hxx>
#include <gp_Vec.hxx>
#endif

namespace cadflow::physics {
namespace {

#ifndef CADFLOW_WITH_OCCT
[[noreturn]] void require_occt() {
    throw std::runtime_error(
        "surface contact metrics require the OCCT native backend");
}
#endif

#ifdef CADFLOW_WITH_OCCT

TopoDS_Face require_face(const TopoDS_Shape& shape) {
    if (shape.IsNull() || shape.ShapeType() != TopAbs_FACE) {
        throw std::invalid_argument("surface contact input must be one BREP face");
    }
    return TopoDS::Face(shape);
}

int surface_geometry(const BRepAdaptor_Surface& surface) {
    switch (surface.GetType()) {
    case GeomAbs_Plane: return CADFLOW_SURFACE_PLANE;
    case GeomAbs_Cylinder: return CADFLOW_SURFACE_CYLINDER;
    case GeomAbs_Cone: return CADFLOW_SURFACE_CONE;
    case GeomAbs_Sphere: return CADFLOW_SURFACE_SPHERE;
    case GeomAbs_Torus: return CADFLOW_SURFACE_TORUS;
    case GeomAbs_BSplineSurface: return CADFLOW_SURFACE_BSPLINE;
    case GeomAbs_BezierSurface: return CADFLOW_SURFACE_BEZIER;
    default: return CADFLOW_SURFACE_OTHER;
    }
}

void point_values(const gp_Pnt& point, double output[3]) {
    output[0] = point.X();
    output[1] = point.Y();
    output[2] = point.Z();
}

void closest_surface_parameters(
    const BRepAdaptor_Surface& surface, const gp_Pnt& reference,
    double& output_u, double& output_v) {
    const double u_min = surface.FirstUParameter();
    const double u_max = surface.LastUParameter();
    const double v_min = surface.FirstVParameter();
    const double v_max = surface.LastVParameter();
    if (!std::isfinite(u_min) || !std::isfinite(u_max)
        || !std::isfinite(v_min) || !std::isfinite(v_max)) {
        throw std::runtime_error("surface face has unbounded parameters");
    }

    double best_squared = std::numeric_limits<double>::infinity();
    constexpr int samples = 8;
    for (int u_index = 0; u_index <= samples; ++u_index) {
        const double u = u_min + (u_max - u_min) * u_index / samples;
        for (int v_index = 0; v_index <= samples; ++v_index) {
            const double v = v_min + (v_max - v_min) * v_index / samples;
            const double squared = surface.Value(u, v).SquareDistance(reference);
            if (squared < best_squared) {
                best_squared = squared;
                output_u = u;
                output_v = v;
            }
        }
    }

    for (int iteration = 0; iteration < 16; ++iteration) {
        gp_Pnt point;
        gp_Vec du;
        gp_Vec dv;
        gp_Vec duu;
        gp_Vec dvv;
        gp_Vec duv;
        surface.D2(output_u, output_v, point, du, dv, duu, dvv, duv);
        const gp_Vec residual(reference, point);
        const double gradient_u = residual.Dot(du);
        const double gradient_v = residual.Dot(dv);
        const double hessian_uu = du.Dot(du) + residual.Dot(duu);
        const double hessian_uv = du.Dot(dv) + residual.Dot(duv);
        const double hessian_vv = dv.Dot(dv) + residual.Dot(dvv);
        const double determinant = hessian_uu * hessian_vv
            - hessian_uv * hessian_uv;
        if (std::abs(determinant) <= 1.0e-20) {
            break;
        }
        const double step_u = (-gradient_u * hessian_vv
            + gradient_v * hessian_uv) / determinant;
        const double step_v = (-gradient_v * hessian_uu
            + gradient_u * hessian_uv) / determinant;
        output_u = std::clamp(output_u + step_u, u_min, u_max);
        output_v = std::clamp(output_v + step_v, v_min, v_max);
        if (step_u * step_u + step_v * step_v <= 1.0e-24) {
            break;
        }
    }
}

void normal_and_curvature(
    const TopoDS_Face& face,
    const gp_Pnt& reference,
    cad_surface_face_metrics_t& output) {
    BRepAdaptor_Surface surface(face, true);
    double u = 0.0;
    double v = 0.0;
    closest_surface_parameters(surface, reference, u, v);
    gp_Pnt point;
    gp_Vec du;
    gp_Vec dv;
    gp_Vec duu;
    gp_Vec dvv;
    gp_Vec duv;
    surface.D2(u, v, point, du, dv, duu, dvv, duv);
    gp_Vec cross = du.Crossed(dv);
    if (cross.SquareMagnitude() <= 1.0e-18) {
        throw std::runtime_error("surface face normal is undefined");
    }
    gp_Dir normal(cross);
    if (face.Orientation() == TopAbs_REVERSED) {
        normal.Reverse();
    }
    output.normal[0] = normal.X();
    output.normal[1] = normal.Y();
    output.normal[2] = normal.Z();

    const double e1 = du.Dot(du);
    const double f1 = du.Dot(dv);
    const double g1 = dv.Dot(dv);
    const double denominator = e1 * g1 - f1 * f1;
    if (denominator <= 1.0e-18) {
        throw std::runtime_error("surface face curvature is undefined");
    }
    const gp_Vec normal_vector(normal);
    const double e2 = normal_vector.Dot(duu);
    const double f2 = normal_vector.Dot(duv);
    const double g2 = normal_vector.Dot(dvv);
    const double mean =
        (e2 * g1 - 2.0 * f2 * f1 + g2 * e1) / (2.0 * denominator);
    const double gaussian = (e2 * g2 - f2 * f2) / denominator;
    const double delta = std::sqrt(std::max(0.0, mean * mean - gaussian));
    output.mean_curvature = mean;
    output.gaussian_curvature = gaussian;
    output.principal_curvature_min = mean - delta;
    output.principal_curvature_max = mean + delta;
    output.surface_geometry = surface_geometry(surface);
}

gp_Trsf rigid_transform(const double values[12]) {
    if (!values) {
        throw std::invalid_argument("surface BREP transform is null");
    }
    for (int index = 0; index < 12; ++index) {
        if (!std::isfinite(values[index])) {
            throw std::invalid_argument("surface BREP transform must be finite");
        }
    }
    gp_Trsf transform;
    transform.SetValues(
        values[0], values[1], values[2], values[3],
        values[4], values[5], values[6], values[7],
        values[8], values[9], values[10], values[11]);
    if (transform.Form() == gp_Other) {
        throw std::invalid_argument("surface BREP transform must be rigid");
    }
    return transform;
}

#endif

}  // namespace

#ifdef CADFLOW_WITH_OCCT

cad_surface_face_metrics_t measure_surface_face(const TopoDS_Shape& shape) {
    const TopoDS_Face face = require_face(shape);
    cad_surface_face_metrics_t output {};

    GProp_GProps properties;
    BRepGProp::SurfaceProperties(face, properties);
    output.area = properties.Mass();
    if (!std::isfinite(output.area) || output.area <= 0.0) {
        throw std::runtime_error("surface face has non-positive area");
    }
    const gp_Pnt centroid = properties.CentreOfMass();
    point_values(centroid, output.centroid);
    normal_and_curvature(face, centroid, output);

    Bnd_Box box;
    BRepBndLib::Add(face, box, true);
    box.Get(
        output.bbox[0], output.bbox[1], output.bbox[2],
        output.bbox[3], output.bbox[4], output.bbox[5]);
    output.valid = BRepCheck_Analyzer(face, true).IsValid() ? 1 : 0;
    return output;
}

cad_surface_pair_metrics_t measure_surface_pair(
    const TopoDS_Shape& shape_a, const TopoDS_Shape& shape_b) {
    const TopoDS_Face face_a = require_face(shape_a);
    const TopoDS_Face face_b = require_face(shape_b);
    cad_surface_pair_metrics_t output {};
    output.face_a = measure_surface_face(face_a);
    output.face_b = measure_surface_face(face_b);

    BRepExtrema_DistShapeShape distance(face_a, face_b);
    distance.Perform();
    if (!distance.IsDone() || distance.NbSolution() < 1) {
        throw std::runtime_error("OCCT surface pair distance calculation failed");
    }
    output.minimum_distance = distance.Value();
    const gp_Pnt closest_a = distance.PointOnShape1(1);
    const gp_Pnt closest_b = distance.PointOnShape2(1);
    point_values(closest_a, output.closest_a);
    point_values(closest_b, output.closest_b);
    normal_and_curvature(face_a, closest_a, output.face_a);
    normal_and_curvature(face_b, closest_b, output.face_b);

    output.normal_dot = 0.0;
    for (int axis = 0; axis < 3; ++axis) {
        output.normal_dot += output.face_a.normal[axis] * output.face_b.normal[axis];
    }
    double separation[3];
    output.signed_normal_gap = 0.0;
    for (int axis = 0; axis < 3; ++axis) {
        separation[axis] = output.closest_b[axis] - output.closest_a[axis];
        output.signed_normal_gap += separation[axis] * output.face_a.normal[axis];
    }
    double tangential_squared = 0.0;
    for (int axis = 0; axis < 3; ++axis) {
        const double tangential = separation[axis]
            - output.signed_normal_gap * output.face_a.normal[axis];
        tangential_squared += tangential * tangential;
    }
    output.tangential_offset = std::sqrt(tangential_squared);
    return output;
}

TopoDS_Shape read_transformed_brep_face(
    const char* data, std::size_t size, const double transform_values[12]) {
    if (!data || size == 0) {
        throw std::invalid_argument("surface BREP buffer is empty");
    }
    BRep_Builder builder;
    TopoDS_Shape shape;
    const std::filesystem::path path =
        std::filesystem::temp_directory_path()
        / ("cadflow-surface-" +
           std::to_string(reinterpret_cast<std::uintptr_t>(data)) + ".brep");
    {
        std::ofstream file(path, std::ios::binary);
        if (!file) {
            throw std::runtime_error("surface BREP temporary file could not be opened");
        }
        file.write(data, static_cast<std::streamsize>(size));
        if (!file) {
            std::error_code ignored;
            std::filesystem::remove(path, ignored);
            throw std::runtime_error("surface BREP temporary file could not be written");
        }
    }
    const Standard_Boolean read_ok =
        BRepTools::Read(shape, path.string().c_str(), builder);
    std::error_code ignored;
    std::filesystem::remove(path, ignored);
    if (!read_ok) {
        throw std::runtime_error("surface BREP buffer could not be read");
    }
    const TopoDS_Face face = require_face(shape);
    return BRepBuilderAPI_Transform(
        face, rigid_transform(transform_values), true).Shape();
}

#endif

cad_surface_face_metrics_t measure_session_face(
    const core::Session& session, core::ShapeId face) {
#ifdef CADFLOW_WITH_OCCT
    return measure_surface_face(core::get_shape(session, face).native);
#else
    (void)session;
    (void)face;
    require_occt();
#endif
}

cad_surface_pair_metrics_t measure_session_pair(
    const core::Session& session, core::ShapeId face_a, core::ShapeId face_b) {
#ifdef CADFLOW_WITH_OCCT
    return measure_surface_pair(
        core::get_shape(session, face_a).native,
        core::get_shape(session, face_b).native);
#else
    (void)session;
    (void)face_a;
    (void)face_b;
    require_occt();
#endif
}

}  // namespace cadflow::physics
