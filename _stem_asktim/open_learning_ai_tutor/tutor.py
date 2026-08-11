import json
from typing import Literal

from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode


class Tutor:
    def __init__(self, client, tools=None) -> None:
        """Bind the tools to the client and build the LangGraph agent/tools workflow."""
        if tools is None:
            # LOCAL PATCH (diverges from upstream): this import was at module
            # scope, which made `langchain_experimental` a hard dependency even
            # for callers passing tools=[]. Deferred so our comparison runner —
            # which disables the PythonREPL tools — doesn't need it installed.
            from open_learning_ai_tutor.tools import execute_python, python_calculator

            tools = [execute_python, python_calculator]

        client = client.bind_tools(tools)
        tool_node = ToolNode(tools)
        self.client = client

        def should_continue(state: MessagesState) -> Literal["tools", END]:
            """Route to the tools node if the last message has tool calls, otherwise end."""
            messages = state["messages"]
            last_message = messages[-1]
            # If the LLM makes a tool call, then we route to the "tools" node
            if last_message.tool_calls:
                return "tools"
            # Otherwise, we stop (reply to the user)
            return END

        def call_model(state: MessagesState):
            """Invoke the client on the current messages and return the response to append to the state."""
            messages = state["messages"]
            response = self.client.invoke(messages)
            # We return a list, because this will get added to the existing list
            return {"messages": [response]}

        workflow = StateGraph(MessagesState)

        workflow.add_node("agent", call_model)
        workflow.add_node("tools", tool_node)

        workflow.add_edge(START, "agent")

        workflow.add_conditional_edges(
            "agent",
            should_continue,
        )

        workflow.add_edge("tools", "agent")

        app = workflow.compile()
        self.app = app

    def get_response(self, prompt):
        """Run the workflow on the prompt and return the final state."""
        return self.app.invoke({"messages": prompt})

    def get_streaming_response(self, prompt):
        """Run the workflow on the prompt and return an async stream of messages and values."""
        return self.app.astream(
            {"messages": prompt}, stream_mode=["messages", "values"]
        )
