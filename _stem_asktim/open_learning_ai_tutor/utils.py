import json

from uuid import uuid4
from open_learning_ai_tutor.constants import Intent
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
    FunctionMessage,
    ChatMessage,
)


def tutor_output_to_json(
    chat_history, intent_history, assessment_history, metadata=None
):
    metadata = metadata or {}
    json_output = {
        "chat_history": messages_to_json(chat_history),
        "intent_history": intent_list_to_json(intent_history),
        "assessment_history": messages_to_json(assessment_history),
        "metadata": metadata,
    }
    json_output = json.dumps(json_output)
    return json_output


def json_to_intent_list(json_str):
    """Convert a JSON string to a list of Intent enums."""
    intent_lists = json.loads(json_str)
    return [
        [Intent[name] for name in intent_list_members if name in Intent.__members__]
        for intent_list_members in intent_lists
    ]


def intent_list_to_json(intent_lists):
    """Convert a list of Intent enums to a JSON string."""
    intent_names = [
        [intent.name for intent in intent_list] for intent_list in intent_lists
    ]
    return json.dumps(intent_names)


def messages_to_json(messages):
    """
    Convert a list of LangChain message objects to JSON format.

    Args:
        messages: List of LangChain message objects (AIMessage, HumanMessage, ToolMessage, etc.)

    Returns:
        list: List of dictionaries containing message data
    """
    json_messages = []

    for message in messages:
        message_dict = {"type": message.__class__.__name__, "content": message.content}

        # Add additional fields if they exist
        if hasattr(message, "additional_kwargs"):
            message_dict.update(message.additional_kwargs)

        if hasattr(message, "name") and message.name:
            message_dict["name"] = message.name

        # Add special fields for specific message types
        if hasattr(message, "tool_call_id"):
            message_dict["tool_call_id"] = message.tool_call_id

        if hasattr(message, "role"):
            message_dict["role"] = message.role

        if hasattr(message, "id"):
            message_dict["id"] = message.id
        else:
            message_dict["id"] = str(uuid4())

        json_messages.append(message_dict)

    return json_messages


def json_to_messages(json_messages):
    """
    Convert JSON format back to LangChain message objects.

    Args:
        json_messages: List of dictionaries containing message data

    Returns:
        list: List of LangChain message objects
    """

    message_type_map = {
        "AIMessage": AIMessage,
        "HumanMessage": HumanMessage,
        "SystemMessage": SystemMessage,
        "ToolMessage": ToolMessage,
        "FunctionMessage": FunctionMessage,
        "ChatMessage": ChatMessage,
    }

    messages = []

    for msg in json_messages:
        msg_type = msg["type"]
        msg_content = msg["content"]

        # Get the message class from the type
        message_class = message_type_map.get(msg_type)
        if not message_class:
            raise ValueError(f"Unknown message type: {msg_type}")

        # Extract special fields
        tool_call_id = msg.get("tool_call_id")
        name = msg.get("name")
        role = msg.get("role")
        message_id = msg.get("id")

        # Extract additional kwargs, excluding special fields
        additional_kwargs = {
            k: v
            for k, v in msg.items()
            if k not in ["type", "content", "name", "tool_call_id", "role", "id"]
        }

        # Create kwargs dict with only existing values
        kwargs = {"content": msg_content}
        if additional_kwargs:
            kwargs["additional_kwargs"] = additional_kwargs
        if name:
            kwargs["name"] = name
        if tool_call_id:
            kwargs["tool_call_id"] = tool_call_id
        if role:
            kwargs["role"] = role
        if message_id:
            kwargs["id"] = message_id
        else:
            kwargs["id"] = str(uuid4())

        # Create the message object
        message = message_class(**kwargs)
        messages.append(message)

    return messages


def filter_out_system_messages(messages):
    return [msg for msg in messages if not isinstance(msg, SystemMessage)]
