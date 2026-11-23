#pragma once

/* Exact first- and second-order surface geometry shared by kernel builders
   and surface analysis. Header-only so both layers evaluate identically. */

#ifdef CADFLOW_WITH_OCCT

#include <BRepAdaptor_Surface.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>

#include <algorithm>
#include <cmath>
#include <limits>

namespace cadflow::kernel::differential {

constexpr double kNaN = std::numeric_limits<double>::quiet_NaN();

/* Value, derivatives, and oriented unit normal of a face at (u, v). */
struct LocalGeometry {
    gp_Pnt point;
    gp_Vec du;
    gp_Vec dv;
    gp_Vec duu;
    gp_Vec duv;
    gp_Vec dvv;
    gp_Vec normal;
    bool regular {false};
};

inline LocalGeometry evaluate(
    const BRepAdaptor_Surface& surface, bool reversed, double u, double v) {
    LocalGeometry output;
    surface.D2(
        u, v, output.point, output.du, output.dv,
        output.duu, output.dvv, output.duv);
    const gp_Vec cross = output.du.Crossed(output.dv);
    /* Compare against the squared derivative scale, not |Su||Sv|: at a pole
       one derivative collapses and the product would hide the degeneracy. */
    const double scale = output.du.SquareMagnitude() + output.dv.SquareMagnitude();
    const double magnitude = cross.Magnitude();
    output.regular = magnitude > 1.0e-10 * scale && magnitude > 1.0e-300;
    if (output.regular) {
        output.normal = cross / magnitude;
        if (reversed) {
            output.normal.Reverse();
        }
    }
    return output;
}

/* Parameter-space image (a, b) of a 3D tangent vector: a Su + b Sv = w. */
inline bool parameter_direction(
    const LocalGeometry& geometry, const gp_Vec& direction, double& a, double& b) {
    const double e1 = geometry.du.Dot(geometry.du);
    const double f1 = geometry.du.Dot(geometry.dv);
    const double g1 = geometry.dv.Dot(geometry.dv);
    const double determinant = e1 * g1 - f1 * f1;
    if (!(determinant > 0.0)) {
        return false;
    }
    const double r1 = geometry.du.Dot(direction);
    const double r2 = geometry.dv.Dot(direction);
    a = (g1 * r1 - f1 * r2) / determinant;
    b = (e1 * r2 - f1 * r1) / determinant;
    return true;
}

/* Normal curvature in the 3D tangent direction `direction`, signed against
   the oriented normal: (II(w, w) / I(w, w)) with w the parameter-space image. */
inline double normal_curvature(
    const LocalGeometry& geometry, const gp_Vec& direction, double normal_sign = 1.0) {
    double a = 0.0;
    double b = 0.0;
    if (!parameter_direction(geometry, direction, a, b)) {
        return kNaN;
    }
    const gp_Vec normal = geometry.normal * normal_sign;
    const double e2 = normal.Dot(geometry.duu);
    const double f2 = normal.Dot(geometry.duv);
    const double g2 = normal.Dot(geometry.dvv);
    const double first = geometry.du.Dot(geometry.du) * a * a
        + 2.0 * geometry.du.Dot(geometry.dv) * a * b
        + geometry.dv.Dot(geometry.dv) * b * b;
    if (!(first > 0.0)) {
        return kNaN;
    }
    return (e2 * a * a + 2.0 * f2 * a * b + g2 * b * b) / first;
}

struct PrincipalCurvature {
    double k_min {kNaN};
    double k_max {kNaN};
    double mean {kNaN};
    double gaussian {kNaN};
    gp_Vec direction_min;
    gp_Vec direction_max;
};

inline gp_Vec principal_direction(
    const LocalGeometry& geometry, double k,
    double e1, double f1, double g1, double e2, double f2, double g2) {
    /* Rows of (II - k I) annihilate the principal direction in (u, v). */
    const double first_a = f2 - k * f1;
    const double first_b = -(e2 - k * e1);
    const double second_a = g2 - k * g1;
    const double second_b = -(f2 - k * f1);
    const bool use_first = first_a * first_a + first_b * first_b
        >= second_a * second_a + second_b * second_b;
    const double a = use_first ? first_a : second_a;
    const double b = use_first ? first_b : second_b;
    gp_Vec direction = geometry.du * a + geometry.dv * b;
    const double magnitude = direction.Magnitude();
    if (magnitude <= 1.0e-12 * (geometry.du.Magnitude() + geometry.dv.Magnitude())) {
        /* Umbilic point: every tangent direction is principal. */
        direction = geometry.du;
        return direction / direction.Magnitude();
    }
    return direction / magnitude;
}

inline PrincipalCurvature principal_curvature(const LocalGeometry& geometry) {
    PrincipalCurvature output;
    if (!geometry.regular) {
        return output;
    }
    const double e1 = geometry.du.Dot(geometry.du);
    const double f1 = geometry.du.Dot(geometry.dv);
    const double g1 = geometry.dv.Dot(geometry.dv);
    const double determinant = e1 * g1 - f1 * f1;
    if (!(determinant > 0.0)) {
        return output;
    }
    const double e2 = geometry.normal.Dot(geometry.duu);
    const double f2 = geometry.normal.Dot(geometry.duv);
    const double g2 = geometry.normal.Dot(geometry.dvv);
    output.mean = (e2 * g1 - 2.0 * f2 * f1 + g2 * e1) / (2.0 * determinant);
    output.gaussian = (e2 * g2 - f2 * f2) / determinant;
    const double delta = std::sqrt(
        std::max(0.0, output.mean * output.mean - output.gaussian));
    output.k_min = output.mean - delta;
    output.k_max = output.mean + delta;
    output.direction_min = principal_direction(
        geometry, output.k_min, e1, f1, g1, e2, f2, g2);
    output.direction_max = geometry.normal.Crossed(output.direction_min);
    return output;
}

}  // namespace cadflow::kernel::differential

#endif
