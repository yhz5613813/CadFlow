#pragma once

#include "core/session.h"

#include <cstddef>

#ifdef CADFLOW_WITH_OCCT
#include <Geom_BSplineSurface.hxx>
#include <TopoDS_Edge.hxx>
#include <TopoDS_Face.hxx>
#include <gp_Pnt.hxx>
#include <gp_Vec.hxx>

#include <functional>
#include <utility>
#include <vector>
#endif

namespace cadflow::kernel {

struct BlendSide {
    core::ShapeId face {0};
    core::ShapeId edge {0};
    /* 0 = G0 (position), 1 = G1 (tangent), 2 = G2 (curvature). */
    int continuity {2};
    /* Handle-length factor; 0 picks the single factor that minimizes
       curvature variation over the whole blend. */
    double tension {0.0};
};

struct BlendOptions {
    /* Maximum boundary deviation from the support edges; the number of
       sections doubles until midpoint samples meet it. */
    double tolerance {1.0e-6};
    /* Initial number of sections; 0 selects 16. */
    std::size_t sections {0};
    /* -1 = choose the edge coupling with the shorter rulings, 0 = keep, 1 = flip. */
    int reverse_b {-1};
};

/* Bridge two boundary edges of two faces with a surface whose cross sections
   are quintic Hermite curves matching each support face to the requested
   order. Returns a session face. */
core::ShapeId blend_surface(
    core::Session& session,
    const BlendSide& side_a,
    const BlendSide& side_b,
    const BlendOptions& options);

#ifdef CADFLOW_WITH_OCCT
struct BlendGeometry {
    Handle(Geom_BSplineSurface) surface;
    std::size_t sections {0};
    double deviation {0.0};
};

/* Boundary frame of a support face where a blend section leaves it. */
struct BlendFrame {
    gp_Pnt point;
    gp_Vec normal;
    /* Unit tangent-plane direction the section leaves the support along. */
    gp_Vec out;
    /* Normal curvature of the support along `out`, signed against `normal`. */
    double curvature {0.0};
};

/* Frames on side A and side B of the section at one blend parameter. */
using BlendFrames = std::pair<BlendFrame, BlendFrame>;
using BlendFrameSource = std::function<BlendFrames(double)>;

/* Handle factor minimizing the curvature-variation energy summed over the
   probe sections; one factor serves every section it is applied to. */
double blend_tension(
    const std::vector<BlendFrames>& probes, int continuity_a, int continuity_b);

/* Blend whose v parameter is the source parameter on [first, last]. Sections
   double until both boundaries deviate less than options.tolerance from the
   frame points. Tensions must already be resolved (positive). */
BlendGeometry blend_along(
    const BlendFrameSource& frames, double first, double last,
    int continuity_a, double tension_a, int continuity_b, double tension_b,
    const BlendOptions& options);

/* Geometry-only core of blend_surface for kernel features that rebuild
   topology around the bridge. u runs across (0 on side A), v along. */
BlendGeometry blend_geometry(
    const TopoDS_Face& face_a, const TopoDS_Edge& edge_a, int continuity_a, double tension_a,
    const TopoDS_Face& face_b, const TopoDS_Edge& edge_b, int continuity_b, double tension_b,
    const BlendOptions& options);
#endif

}  // namespace cadflow::kernel
