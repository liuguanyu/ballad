"""
LoadSkill tool — mirrors Go: ~/devspace/deepx-code/tools/skill.go

Registers LoadSkillTool into the global ToolRegistry.
"""
from __future__ import annotations

from typing import Any

from deepx.tools.base import Tool

from deepx.skill.tool_registry import get_skill_loader


class LoadSkillTool(Tool):
    """Load a named skill's full content into the LLM context."""

    name: str = "load_skill"
    description: str = (
        "Load a skill's full markdown content by name. "
        "Call this when the user wants to apply a specific skill (e.g. brainstorming, "
        "verification-before-completion). "
        "The skill name must be chosen from the Available Skills list in the system prompt."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "The skill name, e.g. 'brainstorming' or 'verification-before-completion'.",
            },
        },
        "required": ["name"],
    }

    async def execute(self, name: str = "", **kwargs) -> str:
        loader = get_skill_loader()
        if loader is None:
            return "skill 系统未启用 (loader 未初始化)"

        name = (name or "").strip()
        if not name:
            return "name 不能为空，请从 system prompt 的 Available Skills 列表里挑一个"

        skill = loader.load(name)
        if skill is None:
            return f"未找到 skill {name!r}"

        lines = [
            f"# Skill: {skill.name} ({skill.scope})",
        ]
        if skill.description:
            lines.insert(1, f"_{skill.description}_\n")
        lines.append("---")
        lines.append("")
        lines.append(skill.body.strip())
        return "\n".join(lines)