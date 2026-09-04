#pragma once

#include "cadflow_core.h"
#include "core/session.h"

#include <cstddef>

#ifdef CADFLOW_WITH_OCCT
#include <TopoDS_Shape.hxx>
#endif

namespace cadflow::physics {

#ifdef CADFLOW_WITH_OCCT
cad_surface_face_metrics_t measure_surface_face(const TopoDS_Shape& shape);
cad_surface_pair_metrics_t measure_surface_pair(
    const TopoDS_Shape& face_a, const TopoDS_Shape& face_b);
TopoDS_Shape read_transformed_brep_face(
    const char* data, std::size_t size, const double transform[12]);
#endif

cad_surface_face_metrics_t measure_session_face(
    const core::Session& session, core::ShapeId face);
cad_surface_pair_metrics_t measure_session_pair(
    const core::Session& session, core::ShapeId face_a, core::ShapeId face_b);

}  // namespace cadflow::physics
