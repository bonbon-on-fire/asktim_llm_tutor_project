import pytest
from open_learning_ai_tutor.message_tutor import message_tutor
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from open_learning_ai_tutor.constants import Intent


def test_message_tutor(mocker):
    """Test message_tutor function"""

    assessment_response = {
        "messages": [
            SystemMessage(content="problem prompt"),
            HumanMessage(content='Student: "what should i try first"'),
            AIMessage(content='{"justification": "test", "selection": "g"}'),
        ]
    }

    tutor_response = "a generator with tutor response"

    # Mock the Tutor class
    mock_tutor = mocker.patch("open_learning_ai_tutor.message_tutor.Tutor")
    mock_tutor_instance = mock_tutor.return_value

    # Configure the async mock response
    mock_get_response = mocker.Mock()
    mock_get_response.return_value = assessment_response

    mock_streaming_response = mocker.Mock()
    mock_streaming_response.return_value = tutor_response

    mock_tutor_instance.get_response = mock_get_response
    mock_tutor_instance.get_streaming_response = mock_streaming_response

    problem = "problem"
    problem_set = "problem_set"
    client = mocker.Mock()
    client.model_name = "test_model"
    new_messages = [HumanMessage(content="what should i try first")]
    chat_history = [HumanMessage(content="what should i try first")]
    assessment_history = [
        HumanMessage(content='Student: "i am confused"'),
        AIMessage(content='{"justification": "test", "selection": "c"}'),
    ]
    intent_history = []
    tools = []

    response = message_tutor(
        problem,
        problem_set,
        client,
        new_messages,
        chat_history,
        assessment_history,
        intent_history,
        tools=tools,
    )

    # Assertions
    assert response == (
        tutor_response,
        [
            [Intent.P_HYPOTHESIS],
        ],
        [
            HumanMessage(
                content='Student: "i am confused"',
                additional_kwargs={},
                response_metadata={},
            ),
            AIMessage(
                content='{"justification": "test", "selection": "c"}',
                additional_kwargs={},
                response_metadata={},
            ),
            HumanMessage(
                content='Student: "what should i try first"',
                additional_kwargs={},
                response_metadata={},
            ),
            AIMessage(
                content='{"justification": "test", "selection": "g"}',
                additional_kwargs={},
                response_metadata={},
            ),
        ],
    )
    assert mock_get_response.call_count == 1
    assert mock_streaming_response.call_count == 1
