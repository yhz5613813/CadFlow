#pragma once

#include "cadflow_core.h"

#include <mutex>
#include <stdexcept>
#include <string>
#include <type_traits>
#include <unordered_map>
#include <utility>
#include <vector>

#ifdef CADFLOW_WITH_OCCT
#include <Standard_Failure.hxx>
#include <TopoDS_Shape.hxx>
#endif

namespace cadflow::core {

using ShapeId = unsigned long long;

constexpr double kPi = 3.141592653589793238462643383279502884;

struct Box3 {
    double min[3] {0.0, 0.0, 0.0};
    double max[3] {0.0, 0.0, 0.0};
};

struct Shape {
    enum class Kind {
        Box,
        Cylinder,
        Sphere,
        Cone,
        Wire,
        Face,
        Surface,
        BSpline,
        Extrude,
        Revolve,
        Loft,
        Sweep,
        TwistedSweep,
        RuledSurface,
        FillingSurface,
        GordonSurface,
        Fillet,
        Chamfer,
        Shell,
        Sewing,
        Solid,
        Cut,
        Union,
        Intersect,
        Translate,
        Rotate,
        Mirror,
        Scale,
        Imported,
    };

    Shape(
        Kind kind_value,
        double a_value = 0.0,
        double b_value = 0.0,
        double c_value = 0.0,
        ShapeId left_value = 0,
        ShapeId right_value = 0)
        : kind(kind_value),
          a(a_value),
          b(b_value),
          c(c_value),
          left(left_value),
          right(right_value) {}

    Kind kind;
    double a {0.0};
    double b {0.0};
    double c {0.0};
    ShapeId left {0};
    ShapeId right {0};
    double offset[3] {0.0, 0.0, 0.0};
    bool closed {false};
    std::vector<double> points;
    std::vector<ShapeId> inputs;
#ifdef CADFLOW_WITH_OCCT
    TopoDS_Shape native;
#endif
};

struct Session {
    std::mutex mutex;
    ShapeId next_id {1};
    std::unordered_map<ShapeId, Shape> shapes;
};

extern thread_local std::string last_error;

Session& as_session(cad_session_t handle);
Shape& get_shape(Session& session, ShapeId id);
const Shape& get_shape(const Session& session, ShapeId id);
ShapeId store(Session& session, Shape shape);
char* copy_string(const std::string& value);

template <typename Function>
auto guarded(Function&& function) -> decltype(function()) {
    using Return = decltype(function());
    try {
        last_error.clear();
        if constexpr (std::is_void_v<Return>) {
            function();
            return;
        } else {
            return function();
        }
#ifdef CADFLOW_WITH_OCCT
    } catch (const Standard_Failure& error) {
        last_error = error.GetMessageString() ? error.GetMessageString() : "OCCT failure";
#endif
    } catch (const std::exception& error) {
        last_error = error.what();
    } catch (...) {
        last_error = "unknown cadflow native error";
    }
    if constexpr (!std::is_void_v<Return>) {
        return Return {};
    }
}

}  // namespace cadflow::core
