#include "physics/connections.h"

#include <algorithm>
#include <array>
#include <cmath>
#include <stdexcept>
#include <string>

namespace cadflow::physics {
namespace {

using Vec3 = std::array<double, 3>;

Vec3 load(const double value[3]) {
    return {value[0], value[1], value[2]};
}

double dot(const Vec3& left, const Vec3& right) {
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2];
}

double norm(const Vec3& value) {
    return std::sqrt(dot(value, value));
}

Vec3 add(const Vec3& left, const Vec3& right) {
    return {left[0] + right[0], left[1] + right[1], left[2] + right[2]};
}

Vec3 subtract(const Vec3& left, const Vec3& right) {
    return {left[0] - right[0], left[1] - right[1], left[2] - right[2]};
}

Vec3 multiply(const Vec3& value, double scale) {
    return {value[0] * scale, value[1] * scale, value[2] * scale};
}

Vec3 normalize(const Vec3& value) {
    const double length = norm(value);
    if (!std::isfinite(length) || length <= 1e-12) {
        throw std::invalid_argument("physical connection axis must be finite and non-zero");
    }
    return multiply(value, 1.0 / length);
}

void require_finite(double value, const char* name) {
    if (!std::isfinite(value)) {
        throw std::invalid_argument(std::string(name) + " must be finite");
    }
}

void require_non_negative(double value, const char* name) {
    require_finite(value, name);
    if (value < 0.0) {
        throw std::invalid_argument(std::string(name) + " must be non-negative");
    }
}

void validate_parameters(const cad_physical_connection_params_t& parameters) {
    if (parameters.response_mode < CADFLOW_CONNECTION_BONDED ||
        parameters.response_mode > CADFLOW_CONNECTION_COMPLIANT) {
        throw std::invalid_argument("unknown physical connection response mode");
    }
    normalize(load(parameters.axis));
    require_non_negative(parameters.normal_stiffness, "normal_stiffness");
    require_non_negative(parameters.tangential_stiffness, "tangential_stiffness");
    require_non_negative(parameters.rotational_stiffness, "rotational_stiffness");
    require_non_negative(parameters.normal_damping, "normal_damping");
    require_non_negative(parameters.tangential_damping, "tangential_damping");
    require_non_negative(parameters.rotational_damping, "rotational_damping");
    require_non_negative(parameters.friction_coefficient, "friction_coefficient");
    require_non_negative(parameters.preload, "preload");
    require_non_negative(parameters.clearance, "clearance");
    require_non_negative(parameters.interference, "interference");
    require_non_negative(parameters.tensile_limit, "tensile_limit");
    require_non_negative(parameters.shear_limit, "shear_limit");
    require_non_negative(parameters.torque_limit, "torque_limit");
    if (parameters.clearance > 0.0 && parameters.interference > 0.0) {
        throw std::invalid_argument(
            "physical connection clearance and interference cannot both be positive");
    }
}

void validate_state(const cad_physical_connection_state_t& state) {
    for (double value : state.relative_translation) {
        require_finite(value, "relative_translation");
    }
    for (double value : state.relative_rotation) {
        require_finite(value, "relative_rotation");
    }
    for (double value : state.relative_linear_velocity) {
        require_finite(value, "relative_linear_velocity");
    }
    for (double value : state.relative_angular_velocity) {
        require_finite(value, "relative_angular_velocity");
    }
}

double utilization(double load_value, double limit) {
    return limit > 0.0 ? load_value / limit : 0.0;
}

void require_finite_response(const cad_physical_connection_response_t& response) {
    for (double value : response.force) {
        require_finite(value, "physical connection force response");
    }
    for (double value : response.torque) {
        require_finite(value, "physical connection torque response");
    }
    require_finite(response.normal_force, "physical connection normal force");
    require_finite(response.shear_force, "physical connection shear force");
    require_finite(response.tensile_utilization, "physical connection tensile utilization");
    require_finite(response.shear_utilization, "physical connection shear utilization");
    require_finite(response.torque_utilization, "physical connection torque utilization");
}

cad_physical_connection_response_t evaluate_one(
    const cad_physical_connection_params_t& parameters,
    const cad_physical_connection_state_t& state) {
    validate_parameters(parameters);
    validate_state(state);

    const Vec3 axis = normalize(load(parameters.axis));
    const Vec3 translation = load(state.relative_translation);
    const Vec3 rotation = load(state.relative_rotation);
    const Vec3 linear_velocity = load(state.relative_linear_velocity);
    const Vec3 angular_velocity = load(state.relative_angular_velocity);

    const double normal_displacement = dot(translation, axis);
    const double normal_velocity = dot(linear_velocity, axis);
    const Vec3 tangential_displacement = subtract(
        translation, multiply(axis, normal_displacement));
    const Vec3 tangential_velocity = subtract(
        linear_velocity, multiply(axis, normal_velocity));

    Vec3 force = add(
        multiply(tangential_displacement, -parameters.tangential_stiffness),
        multiply(tangential_velocity, -parameters.tangential_damping));
    double normal_force = 0.0;
    int active = 1;

    const bool unilateral =
        parameters.response_mode == CADFLOW_CONNECTION_FRICTIONAL_CONTACT ||
        parameters.response_mode == CADFLOW_CONNECTION_INTERFERENCE;
    if (unilateral) {
        const double gap = normal_displacement + parameters.clearance -
            parameters.interference;
        const double penetration = std::max(0.0, -gap);
        const double reaction = std::max(
            0.0,
            parameters.normal_stiffness * penetration -
                parameters.normal_damping * normal_velocity);
        const double friction_capacity = parameters.friction_coefficient *
            (reaction + parameters.preload);
        const double trial_shear = norm(force);
        if (trial_shear > friction_capacity && trial_shear > 0.0) {
            force = multiply(force, friction_capacity / trial_shear);
        }
        normal_force = reaction - parameters.preload;
        force = add(force, multiply(axis, normal_force));
        active = (reaction > 0.0 || parameters.preload > 0.0) ? 1 : 0;
    } else {
        normal_force = -(
            parameters.normal_stiffness * normal_displacement +
            parameters.normal_damping * normal_velocity);
        if (parameters.response_mode == CADFLOW_CONNECTION_FASTENER) {
            normal_force -= parameters.preload;
        }
        force = add(force, multiply(axis, normal_force));
    }

    const Vec3 torque = add(
        multiply(rotation, -parameters.rotational_stiffness),
        multiply(angular_velocity, -parameters.rotational_damping));
    const Vec3 shear = subtract(force, multiply(axis, dot(force, axis)));
    const double shear_force = norm(shear);
    const double torque_magnitude = norm(torque);
    const double tensile_force = std::max(0.0, -normal_force);

    cad_physical_connection_response_t response {};
    for (std::size_t axis_index = 0; axis_index < 3; ++axis_index) {
        response.force[axis_index] = force[axis_index];
        response.torque[axis_index] = torque[axis_index];
    }
    response.normal_force = normal_force;
    response.shear_force = shear_force;
    response.tensile_utilization = utilization(
        tensile_force, parameters.tensile_limit);
    response.shear_utilization = utilization(
        shear_force, parameters.shear_limit);
    response.torque_utilization = utilization(
        torque_magnitude, parameters.torque_limit);
    response.active = active;
    response.failed = (
        response.tensile_utilization > 1.0 ||
        response.shear_utilization > 1.0 ||
        response.torque_utilization > 1.0) ? 1 : 0;
    require_finite_response(response);
    return response;
}

}  // namespace

void evaluate_connection_responses(
    const cad_physical_connection_params_t* parameters,
    const cad_physical_connection_state_t* states,
    std::size_t connection_count,
    cad_physical_connection_response_t* responses) {
    if (connection_count == 0) {
        return;
    }
    if (!parameters || !states || !responses) {
        throw std::invalid_argument(
            "physical connection parameters, states, and responses are required");
    }
    for (std::size_t index = 0; index < connection_count; ++index) {
        responses[index] = evaluate_one(parameters[index], states[index]);
    }
}

}  // namespace cadflow::physics
