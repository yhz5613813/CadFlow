"""Build and render a detailed parametric weeping willow with CadFlow."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import cadflow as cad


Vec3 = tuple[float, float, float]

OUTPUT_DIR = Path("examples/out/cadflow_weeping_willow")
STEP_PATH = OUTPUT_DIR / "weeping_willow.step"
PNG_PATH = OUTPUT_DIR / "weeping_willow.png"
METRICS_PATH = OUTPUT_DIR / "weeping_willow_metrics.json"
RANDOM_SEED = 240519


def _add(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] + b[0], a[1] + b[1], a[2] + b[2])


def _sub(a: Vec3, b: Vec3) -> Vec3:
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _mul(vector: Vec3, scale: float) -> Vec3:
    return (vector[0] * scale, vector[1] * scale, vector[2] * scale)


def _length(vector: Vec3) -> float:
    return math.sqrt(sum(component * component for component in vector))


def _unit(vector: Vec3) -> Vec3:
    length = _length(vector)
    if length <= 1.0e-9:
        raise ValueError("cannot normalize a zero-length vector")
    return _mul(vector, 1.0 / length)


def _cross(a: Vec3, b: Vec3) -> Vec3:
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _lerp(a: Vec3, b: Vec3, amount: float) -> Vec3:
    return _add(a, _mul(_sub(b, a), amount))


def _point_on_polyline(points: list[Vec3], amount: float) -> Vec3:
    amount = max(0.0, min(1.0, amount))
    lengths = [_length(_sub(end, start)) for start, end in zip(points, points[1:])]
    target = amount * sum(lengths)
    for index, segment_length in enumerate(lengths):
        if target <= segment_length or index == len(lengths) - 1:
            return _lerp(points[index], points[index + 1], target / segment_length)
        target -= segment_length
    return points[-1]


@dataclass
class WillowScene:
    solids: list[Any] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def add(self, solid: Any, group: str) -> None:
        cad.apply_tag(solid, group)
        self.solids.append(solid)
        self.counts[group] = self.counts.get(group, 0) + 1


def _tapered_segment(
    start: Vec3,
    end: Vec3,
    start_radius: float,
    end_radius: float,
) -> Any:
    vector = _sub(end, start)
    return cad.make_cone_rsolid(
        bottom_radius=start_radius,
        top_radius=max(end_radius, 0.06),
        height=_length(vector),
        bottom_face_center=start,
        axis=vector,
    )


def _add_tapered_path(
    scene: WillowScene,
    points: list[Vec3],
    start_radius: float,
    end_radius: float,
    group: str,
) -> None:
    segment_count = len(points) - 1
    for index, (start, end) in enumerate(zip(points, points[1:])):
        radius_a = start_radius + (end_radius - start_radius) * index / segment_count
        radius_b = start_radius + (end_radius - start_radius) * (index + 1) / segment_count
        scene.add(_tapered_segment(start, end, radius_a, radius_b), group)


def _make_leaf(
    center: Vec3,
    direction: Vec3,
    length: float,
    width: float,
    roll: float,
) -> Any:
    axis = _unit(direction)
    reference = (0.0, 0.0, 1.0) if abs(axis[2]) < 0.88 else (0.0, 1.0, 0.0)
    base_side = _unit(_cross(reference, axis))
    base_normal = _unit(_cross(axis, base_side))
    side = _unit(
        _add(_mul(base_side, math.cos(roll)), _mul(base_normal, math.sin(roll)))
    )
    normal = _unit(_cross(axis, side))
    half_length = length * 0.5
    points = [
        _add(center, _mul(axis, half_length)),
        _add(_add(center, _mul(axis, length * 0.10)), _mul(side, width * 0.50)),
        _add(_add(center, _mul(axis, -length * 0.28)), _mul(side, width * 0.32)),
        _add(center, _mul(axis, -half_length)),
        _add(_add(center, _mul(axis, -length * 0.28)), _mul(side, -width * 0.32)),
        _add(_add(center, _mul(axis, length * 0.10)), _mul(side, -width * 0.50)),
    ]
    outline = cad.make_polyline_rwire(points, closed=True)
    face = cad.make_face_from_wire_rface(outline, normal=normal)
    return cad.extrude_rsolid(face, normal, 0.16)


def _trunk_center_at(height: float, trunk_points: list[Vec3]) -> Vec3:
    for start, end in zip(trunk_points, trunk_points[1:]):
        if start[2] <= height <= end[2]:
            return _lerp(start, end, (height - start[2]) / (end[2] - start[2]))
    return trunk_points[-1]


def _build_ground_and_roots(scene: WillowScene, rng: random.Random) -> None:
    ground = cad.make_cylinder_rsolid(
        radius=164.0,
        height=3.0,
        bottom_face_center=(0.0, 0.0, -4.0),
    )
    scene.add(ground, "willow.ground")

    for index in range(13):
        angle = 2.0 * math.pi * index / 13.0 + rng.uniform(-0.10, 0.10)
        radial = (math.cos(angle), math.sin(angle), 0.0)
        tangent = (-radial[1], radial[0], 0.0)
        reach = rng.uniform(43.0, 76.0)
        points = [
            _add(_mul(radial, rng.uniform(5.0, 9.0)), (0.0, 0.0, 5.0)),
            _add(_add(_mul(radial, reach * 0.34), _mul(tangent, rng.uniform(-4.0, 4.0))), (0.0, 0.0, 1.8)),
            _add(_add(_mul(radial, reach * 0.70), _mul(tangent, rng.uniform(-7.0, 7.0))), (0.0, 0.0, -0.2)),
            _add(_add(_mul(radial, reach), _mul(tangent, rng.uniform(-5.0, 5.0))), (0.0, 0.0, -1.3)),
        ]
        _add_tapered_path(
            scene,
            points,
            start_radius=rng.uniform(4.0, 6.4),
            end_radius=0.65,
            group="willow.bark",
        )


def _build_trunk(scene: WillowScene, rng: random.Random) -> list[Vec3]:
    trunk_points: list[Vec3] = [
        (0.0, 0.0, 0.0),
        (2.0, -1.0, 25.0),
        (-1.8, 1.8, 51.0),
        (3.2, 3.0, 78.0),
        (0.4, 5.5, 105.0),
        (-3.0, 4.0, 132.0),
        (1.5, 7.5, 158.0),
        (4.0, 5.0, 183.0),
        (1.0, 8.5, 207.0),
        (-2.0, 10.0, 228.0),
    ]
    radii = (18.0, 17.0, 15.8, 14.4, 12.8, 11.2, 9.5, 7.8, 6.0, 3.6)
    for start, end, radius_a, radius_b in zip(
        trunk_points, trunk_points[1:], radii, radii[1:]
    ):
        scene.add(_tapered_segment(start, end, radius_a, radius_b), "willow.bark")

    # Raised, irregular vertical strips give the lower trunk a fissured bark silhouette.
    for index in range(22):
        angle = 2.0 * math.pi * index / 22.0 + rng.uniform(-0.08, 0.08)
        radius = 18.05
        start_z = rng.uniform(2.0, 25.0)
        strip_length = rng.uniform(28.0, 60.0)
        start = (radius * math.cos(angle), radius * math.sin(angle), start_z)
        end = (
            (radius - 4.2) * math.cos(angle + rng.uniform(-0.05, 0.05)),
            (radius - 4.2) * math.sin(angle + rng.uniform(-0.05, 0.05)),
            min(91.0, start_z + strip_length),
        )
        scene.add(
            _tapered_segment(start, end, rng.uniform(0.65, 1.05), 0.24),
            "willow.bark_shadow",
        )
    return trunk_points


def _build_scaffold_branches(
    scene: WillowScene,
    trunk_points: list[Vec3],
    rng: random.Random,
) -> list[list[Vec3]]:
    branches: list[list[Vec3]] = []
    levels = (
        88.0,
        98.0,
        109.0,
        120.0,
        131.0,
        142.0,
        152.0,
        162.0,
        172.0,
        181.0,
        190.0,
        199.0,
        207.0,
        214.0,
        221.0,
    )
    for index, height in enumerate(levels):
        angle = math.radians(index * 137.5 + rng.uniform(-13.0, 13.0))
        radial = (math.cos(angle), math.sin(angle), 0.0)
        tangent = (-radial[1], radial[0], 0.0)
        start = _trunk_center_at(height, trunk_points)
        reach = rng.uniform(78.0, 112.0) * (1.04 - 0.014 * index)
        lift = rng.uniform(22.0, 37.0)
        branch = [
            start,
            _add(_add(start, _mul(radial, reach * 0.30)), (0.0, 0.0, lift * 0.55)),
            _add(
                _add(_add(start, _mul(radial, reach * 0.66)), _mul(tangent, rng.uniform(-11.0, 11.0))),
                (0.0, 0.0, lift),
            ),
            _add(
                _add(_add(start, _mul(radial, reach)), _mul(tangent, rng.uniform(-15.0, 15.0))),
                (0.0, 0.0, lift * rng.uniform(0.35, 0.65)),
            ),
        ]
        start_radius = max(2.8, 6.8 - index * 0.25)
        _add_tapered_path(scene, branch, start_radius, 1.15, "willow.bark")
        branches.append(branch)

        # Each main limb splits once, producing the broad, layered willow crown.
        fork_start = _point_on_polyline(branch, rng.uniform(0.48, 0.66))
        fork_angle = angle + rng.choice((-1.0, 1.0)) * rng.uniform(0.35, 0.62)
        fork_radial = (math.cos(fork_angle), math.sin(fork_angle), 0.0)
        fork_length = reach * rng.uniform(0.42, 0.58)
        fork = [
            fork_start,
            _add(_add(fork_start, _mul(fork_radial, fork_length * 0.55)), (0.0, 0.0, rng.uniform(6.0, 14.0))),
            _add(_add(fork_start, _mul(fork_radial, fork_length)), (0.0, 0.0, rng.uniform(-2.0, 8.0))),
        ]
        _add_tapered_path(scene, fork, start_radius * 0.46, 0.72, "willow.bark")
        branches.append(fork)

    # Three thinner leaders prevent the crown from ending in a blunt central tip.
    crown = trunk_points[-1]
    for index in range(3):
        angle = math.radians(35.0 + index * 120.0)
        leader = [
            crown,
            _add(crown, (24.0 * math.cos(angle), 24.0 * math.sin(angle), 18.0 + index * 3.0)),
            _add(crown, (49.0 * math.cos(angle), 49.0 * math.sin(angle), 22.0 - index * 4.0)),
        ]
        _add_tapered_path(scene, leader, 3.1, 0.68, "willow.bark")
        branches.append(leader)
    return branches


def _leaf_group(rng: random.Random, height: float) -> str:
    if height > 190.0 and rng.random() < 0.30:
        return "willow.leaf_young"
    value = rng.random()
    if value < 0.30:
        return "willow.leaf_dark"
    if value < 0.78:
        return "willow.leaf_mid"
    return "willow.leaf_light"


def _build_hanging_sprays(
    scene: WillowScene,
    branches: list[list[Vec3]],
    rng: random.Random,
) -> None:
    for branch_index, branch in enumerate(branches):
        branch_count = 4 if branch_index >= 30 else (6 + branch_index % 3)
        for spray_index in range(branch_count):
            amount = (spray_index + 1.0) / (branch_count + 0.35)
            amount += rng.uniform(-0.035, 0.035)
            attachment = _point_on_polyline(branch, amount)
            outward = _unit((attachment[0], attachment[1], 0.0))
            tangent = (-outward[1], outward[0], 0.0)
            target_drop = rng.uniform(92.0, 154.0)
            target_drop = min(target_drop, max(45.0, attachment[2] - rng.uniform(11.0, 24.0)))
            sway = rng.uniform(-13.0, 13.0)
            spray: list[Vec3] = []
            point_count = 8
            for point_index in range(point_count):
                t = point_index / (point_count - 1)
                point = _add(
                    attachment,
                    _add(
                        _mul(outward, 11.0 * math.sin(math.pi * t) + 5.0 * t),
                        _add(
                            _mul(tangent, sway * math.sin(math.pi * t) + 2.8 * math.sin(3.0 * math.pi * t + branch_index)),
                            (0.0, 0.0, -target_drop * (0.14 * t + 0.86 * t * t)),
                        ),
                    ),
                )
                spray.append(point)
            _add_tapered_path(
                scene,
                spray,
                start_radius=rng.uniform(0.72, 1.05),
                end_radius=0.16,
                group="willow.twig",
            )

            # Alternate leaves spiral down the flexible shoot on short petioles.
            for leaf_index in range(1, point_count):
                branch_point = _lerp(spray[leaf_index - 1], spray[leaf_index], rng.uniform(0.38, 0.78))
                tangent_direction = _unit(_sub(spray[leaf_index], spray[leaf_index - 1]))
                side_sign = -1.0 if (leaf_index + branch_index + spray_index) % 2 else 1.0
                azimuth_jitter = rng.uniform(-0.42, 0.42)
                leaf_side = _unit(
                    _add(
                        _mul(tangent, side_sign * math.cos(azimuth_jitter)),
                        _mul(outward, side_sign * math.sin(azimuth_jitter)),
                    )
                )
                petiole_end = _add(
                    branch_point,
                    _add(_mul(leaf_side, rng.uniform(2.0, 3.2)), (0.0, 0.0, rng.uniform(-0.7, 0.8))),
                )
                scene.add(
                    _tapered_segment(branch_point, petiole_end, 0.16, 0.09),
                    "willow.twig",
                )
                leaf_direction = _unit(
                    _add(
                        _mul(leaf_side, 0.88),
                        _add(_mul(tangent_direction, rng.uniform(-0.18, 0.22)), (0.0, 0.0, rng.uniform(-0.18, 0.10))),
                    )
                )
                leaf_length = rng.uniform(8.5, 12.5)
                leaf_center = _add(petiole_end, _mul(leaf_direction, leaf_length * 0.40))
                leaf = _make_leaf(
                    leaf_center,
                    leaf_direction,
                    leaf_length,
                    rng.uniform(1.65, 2.75),
                    rng.uniform(-1.25, 1.25),
                )
                scene.add(leaf, _leaf_group(rng, branch_point[2]))

                # Sparse paired leaves break the regular alternating rhythm.
                if leaf_index in (3, 6) and (branch_index + spray_index) % 3 == 0:
                    opposite = _mul(leaf_side, -1.0)
                    second_length = leaf_length * rng.uniform(0.78, 0.92)
                    second_center = _add(branch_point, _mul(opposite, second_length * 0.58))
                    scene.add(
                        _make_leaf(
                            second_center,
                            opposite,
                            second_length,
                            rng.uniform(1.45, 2.25),
                            rng.uniform(-1.25, 1.25),
                        ),
                        _leaf_group(rng, branch_point[2]),
                    )


def build_willow() -> WillowScene:
    rng = random.Random(RANDOM_SEED)
    scene = WillowScene()
    _build_ground_and_roots(scene, rng)
    trunk_points = _build_trunk(scene, rng)
    branches = _build_scaffold_branches(scene, trunk_points, rng)
    _build_hanging_sprays(scene, branches, rng)
    return scene


def _all_bounds(solids: Iterable[Any]) -> tuple[float, float, float, float, float, float]:
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    box = Bnd_Box()
    for solid in solids:
        BRepBndLib.Add_s(solid.wrapped, box)
    return tuple(float(value) for value in box.Get())


def render_and_export(scene: WillowScene) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    bounds = _all_bounds(scene.solids)
    metrics: dict[str, Any] = {
        "units": "centimeters",
        "seed": RANDOM_SEED,
        "solid_count": len(scene.solids),
        "groups": dict(sorted(scene.counts.items())),
        "bounding_box": bounds,
    }
    if len(scene.solids) < 700:
        raise RuntimeError("willow detail budget was not reached")
    if bounds[2] > -3.9 or bounds[5] < 245.0:
        raise RuntimeError(f"unexpected willow height: {bounds}")

    cad.export_step(scene.solids, str(STEP_PATH))
    cad.render_screenshot_rpath(
        scene.solids,
        str(PNG_PATH),
        highlight_tags=(
            "willow.ground",
            "willow.bark",
            "willow.bark_shadow",
            "willow.twig",
            "willow.leaf_dark",
            "willow.leaf_mid",
            "willow.leaf_light",
            "willow.leaf_young",
        ),
        image_size=(1800, 1800),
        view=(12.0, -52.0),
        show_axes=False,
        show_legend=False,
        show_callouts=False,
        zoom=4.35,
        tag_colors={
            "willow.ground": (0.36, 0.46, 0.23),
            "willow.bark": (0.34, 0.22, 0.11),
            "willow.bark_shadow": (0.19, 0.12, 0.07),
            "willow.twig": (0.42, 0.35, 0.12),
            "willow.leaf_dark": (0.12, 0.33, 0.12),
            "willow.leaf_mid": (0.25, 0.52, 0.16),
            "willow.leaf_light": (0.48, 0.68, 0.23),
            "willow.leaf_young": (0.67, 0.78, 0.29),
        },
        background_color=(1.0, 1.0, 1.0),
        show_edges=False,
    )
    metrics["outputs"] = {
        "step": str(STEP_PATH.resolve()),
        "png": str(PNG_PATH.resolve()),
    }
    METRICS_PATH.write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    return metrics


def main() -> None:
    scene = build_willow()
    metrics = render_and_export(scene)
    for path in (STEP_PATH, PNG_PATH, METRICS_PATH):
        if not path.is_file() or path.stat().st_size == 0:
            raise RuntimeError(f"missing or empty output: {path}")
    print(json.dumps(metrics, indent=2, sort_keys=True))
    print("png", PNG_PATH.resolve(), PNG_PATH.stat().st_size)


if __name__ == "__main__":
    main()
