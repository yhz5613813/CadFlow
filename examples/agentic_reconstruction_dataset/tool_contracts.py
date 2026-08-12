"""OpenAI-style tool contracts for the agentic reconstruction example."""

from __future__ import annotations

from typing import Any


def _object_schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "reconstruction_read_sample",
            "description": (
                "Read one Fusion 360 Gallery Reconstruction JSON file and return "
                "its ordered Sketch/Extrude feature plan."
            ),
            "parameters": _object_schema(
                {"source_json": {"type": "string"}}, ["source_json"]
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "brep_inspect_step",
            "description": (
                "Inspect the target STEP with CadFlow's public B-Rep inspection API."
            ),
            "parameters": _object_schema(
                {"step_path": {"type": "string"}}, ["step_path"]
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cad_create_profile",
            "description": (
                "Convert one Fusion profile UUID into a CadFlow Face using public "
                "edge, wire, and face construction calls."
            ),
            "parameters": _object_schema(
                {
                    "sketch_id": {"type": "string"},
                    "profile_id": {"type": "string"},
                },
                ["sketch_id", "profile_id"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cad_extrude_profile",
            "description": (
                "Extrude a profile with CadFlow. Fusion symmetric extents are lowered "
                "to extrude_rsolid plus translate_shape."
            ),
            "parameters": _object_schema(
                {
                    "profile_handle": {"type": "string"},
                    "solid_handle": {"type": "string"},
                    "distance_cm": {"type": "number"},
                    "extent_type": {
                        "type": "string",
                        "enum": [
                            "OneSideFeatureExtentType",
                            "SymmetricFeatureExtentType",
                        ],
                    },
                },
                ["profile_handle", "solid_handle", "distance_cm", "extent_type"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cad_apply_feature",
            "description": (
                "Apply Fusion NewBody, Join, or Cut semantics using the current body, "
                "union_rsolid, and cut_rsolid."
            ),
            "parameters": _object_schema(
                {
                    "feature_handle": {
                        "oneOf": [
                            {"type": "string"},
                            {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                            },
                        ]
                    },
                    "operation": {
                        "type": "string",
                        "enum": [
                            "NewBodyFeatureOperation",
                            "JoinFeatureOperation",
                            "CutFeatureOperation",
                        ],
                    },
                },
                ["feature_handle", "operation"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cad_inspect_model",
            "description": (
                "Ground the current CAD state with volume and QL topology counts."
            ),
            "parameters": _object_schema({}, []),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cad_export_artifacts",
            "description": (
                "Export the reconstructed body as STEP and the replayable operation "
                "graph as model JSON, then verify graph replay."
            ),
            "parameters": _object_schema(
                {
                    "step_path": {"type": "string"},
                    "model_json_path": {"type": "string"},
                },
                ["step_path", "model_json_path"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cad_heal_same_domain",
            "description": (
                "Use the compatibility adapter to merge nearly coplanar faces "
                "when source float precision leaves splitter edges that the public "
                "CadFlow cleanup API cannot parameterize."
            ),
            "parameters": _object_schema(
                {
                    "input_step": {"type": "string"},
                    "output_step": {"type": "string"},
                    "linear_tolerance_mm": {
                        "type": "number",
                        "exclusiveMinimum": 0,
                    },
                },
                ["input_step", "output_step", "linear_tolerance_mm"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "brep_evaluate_reconstruction",
            "description": (
                "Compare target and candidate STEP files with CadFlow reconstruction "
                "evaluation and strict B-Rep diagnostics."
            ),
            "parameters": _object_schema(
                {
                    "target_step": {"type": "string"},
                    "candidate_step": {"type": "string"},
                },
                ["target_step", "candidate_step"],
            ),
        },
    },
]
