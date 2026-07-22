import pytest
from open_learning_ai_tutor.tutor import Tutor


async def test_tutor_graph(mocker):
    """Test that the Tutor class creates a graph with the correct nodes and edges."""
    mock_client = mocker.MagicMock()
    tutor = Tutor(mock_client, [])
    app = tutor.app
    for node in ("agent", "tools"):
        assert node in app.nodes
    graph = app.get_graph()

    edges = graph.edges
    assert len(edges) == 4
    tool_agent_edge = edges[3]
    for test_condition in (
        tool_agent_edge.source == "tools",
        tool_agent_edge.target == "agent",
        not tool_agent_edge.conditional,
    ):
        assert test_condition
    agent_tool_edge = edges[2]
    for test_condition in (
        agent_tool_edge.source == "agent",
        agent_tool_edge.target == "tools",
        agent_tool_edge.conditional,
    ):
        assert test_condition
    agent_end_edge = edges[1]
    for test_condition in (
        agent_end_edge.source == "agent",
        agent_end_edge.target == "__end__",
        agent_end_edge.conditional,
    ):
        assert test_condition
