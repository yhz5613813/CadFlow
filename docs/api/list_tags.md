# list_tags

## API Definition

```python
def list_tags(shape: AnyShape, scope: str | TagScope = TagScope.EFFECTIVE) -> List[str]
```

*Source: operations.py*

## Import Surface

- top-level: `from cadflow import list_tags`

## Description

Return shape tags in deterministic sorted order for one scope.
