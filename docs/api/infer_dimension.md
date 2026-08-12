# infer_dimension

## API Definition

```python
def infer_dimension(value: 'ScalarLike') -> Dimension | None
```

*Source: units.py*

## Import Surface

- top-level: `from cadflow import infer_dimension`

## Description

Infer and validate an expression's result dimension.

``None`` means the expression uses only legacy variables without unit
declarations. Expressions that contain explicit units are validated
strictly and cannot mix in legacy variables.
