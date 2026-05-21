from typing import Annotated, Any

from pydantic import BeforeValidator


def coerce_empty_to_none(v: Any) -> Any:
    if isinstance(v, dict) and not v:
        return None
    return v


OptStr = Annotated[str | None, BeforeValidator(coerce_empty_to_none)]
