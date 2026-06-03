"""Todo tool — visible task checklist."""
from __future__ import annotations

from deepx.tools.base import Tool


class Todo(Tool):
    """Manage a visible task checklist for multi-step tasks."""

    name = "Todo"
    description = "Create and manage a visible todo list for complex multi-step tasks. Use this to track progress through a sequence of steps. Each item can be marked as done or in_progress."
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["add", "done", "remove", "list"],
                "description": "Action to perform on the todo list.",
            },
            "item": {
                "type": "string",
                "description": "The task item text (for add/done/remove actions).",
            },
        },
        "required": ["action"],
    }

    async def execute(self, action: str, item: str = "", **kwargs) -> str:
        # TODO: implement with session state
        return f"[Todo stub] action={action}, item={item}"