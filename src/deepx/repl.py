"""Interactive REPL using prompt_toolkit."""
import asyncio
from rich.console import Console
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style

from deepx.llm.client import LLMClient, Message
from deepx.config.settings import get_settings
from deepx.graph.workflow import build_workflow, get_initial_state
from deepx.mcp.manager import Manager

console = Console()

async def run_repl():
    console.print("[bold blue]DeepX REPL[/bold blue] (prompt_toolkit mode - perfect IME support)")
    console.print("Type 'exit' or 'quit' to quit.")
    
    # Initialize MCP
    manager = Manager()
    await manager.connect_all()
    await manager.refresh_tools()
    
    session_id = "repl-session"
    workflow = build_workflow(session_id)
    app_state = get_initial_state(session_id)
    app_state["_mode"] = "review"
    
    session = PromptSession()
    
    while True:
        try:
            user_input = await session.prompt_async("\n> ")
        except (KeyboardInterrupt, EOFError):
            break
            
        user_input = user_input.strip()
        if not user_input:
            continue
        if user_input.lower() in ("exit", "quit"):
            break
            
        app_state["messages"].append({"role": "user", "content": user_input})
        
        console.print("[dim]Thinking...[/dim]")
        
        # We run the workflow
        async for chunk in workflow.astream(
            input=app_state,
            config={"configurable": {"thread_id": session_id}},
            stream_mode="custom",
        ):
            # Process custom events
            if chunk.get("type") == "custom":
                data = chunk.get("data", {})
                ct = data.get("type", "")
                
                if ct == "token":
                    console.print(data.get("content", ""), end="")
                elif ct == "tool_call":
                    console.print(f"\n[dim cyan]Calling: {data.get('tool_name')}[/dim cyan]")
                elif ct == "tool_result":
                    console.print(f"[dim cyan]Result: {str(data.get('result'))[:100]}...[/dim cyan]")
                elif ct == "error":
                    console.print(f"\n[bold red]Error: {data.get('message')}[/bold red]")
                    
        # Update state from the final snapshot
        async for state in workflow.astream(
            input=app_state,
            config={"configurable": {"thread_id": session_id}},
            stream_mode="values",
        ):
            if state.get("next_node") == "end":
                app_state = state
        
        console.print()

