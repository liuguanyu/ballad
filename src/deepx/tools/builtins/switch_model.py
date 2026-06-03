"""SwitchModel tool — upgrade model when task complexity is detected."""
from __future__ import annotations

from deepx.tools.base import Tool


class SwitchModel(Tool):
    """Switch from flash to pro model when task complexity requires it."""

    name = "SwitchModel"
    description = "Request a switch from flash (fast/cheap) to pro (powerful) model. Use this when the task is detected to be too complex for the flash model, or when the flash model itself requests an upgrade."
    parameters = {
        "type": "object",
        "properties": {
            "reason": {
                "type": "string",
                "description": "Reason for switching models.",
            },
        },
        "required": ["reason"],
    }

    async def execute(self, reason: str = "", **kwargs) -> str:
        # TODO: emit a signal that will be handled by the graph to switch model
        return f"[SwitchModel stub] reason={reason}"