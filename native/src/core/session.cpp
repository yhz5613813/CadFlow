#include "core/session.h"

#include <cstdlib>
#include <cstring>

namespace cadflow::core {

thread_local std::string last_error;

Session& as_session(cad_session_t handle) {
    if (!handle) {
        throw std::invalid_argument("cadflow session is null");
    }
    return *static_cast<Session*>(handle);
}

Shape& get_shape(Session& session, ShapeId id) {
    const auto found = session.shapes.find(id);
    if (found == session.shapes.end()) {
        throw std::out_of_range("unknown shape handle " + std::to_string(id));
    }
    return found->second;
}

const Shape& get_shape(const Session& session, ShapeId id) {
    const auto found = session.shapes.find(id);
    if (found == session.shapes.end()) {
        throw std::out_of_range("unknown shape handle " + std::to_string(id));
    }
    return found->second;
}

ShapeId store(Session& session, Shape shape) {
    const ShapeId id = session.next_id++;
    session.shapes.emplace(id, std::move(shape));
    return id;
}

char* copy_string(const std::string& value) {
    char* result = static_cast<char*>(std::malloc(value.size() + 1));
    if (!result) {
        throw std::bad_alloc();
    }
    std::memcpy(result, value.c_str(), value.size() + 1);
    return result;
}

}  // namespace cadflow::core
