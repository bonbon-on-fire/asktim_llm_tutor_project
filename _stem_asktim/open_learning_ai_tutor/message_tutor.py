from open_learning_ai_tutor.tutor import Tutor
from open_learning_ai_tutor.prompts import get_assessment_prompt, get_tutor_prompt
from open_learning_ai_tutor.utils import filter_out_system_messages
from open_learning_ai_tutor.intent_selector import get_intent
from open_learning_ai_tutor.constants import Intent


def message_tutor(
    problem: str,
    problem_set: str,
    client: object,
    new_messages: list,
    chat_history: list,
    assessment_history: list,
    intent_history: list,
    tools,
    variant: str = "edx",
):
    """
    Function to handle the message flow between the tutor and the student.
    It first assesses the student's message and then generates a response
    based on the assessment.
    Args:
        problem (str): The problem to be solved.
        problem_set (str): The set of problems.
        client (object): The client object for the tutor.
        new_messages (list): The new messages from the student.
        chat_history (list): All messages between the tutor and student.
        assessment_history (list): All assessments for the student messages in the chat history.
        intent_history (list):  All intents assigned based on the student messages in the chat history.
        tools: Tools available to the tutor.
    Returns
        tuple: A tuple containing a generator that streams the response ,
            and the new intent history and assessment history
    """
    tutor = Tutor(
        client,
        tools=tools,
    )
    assessment_prompt = get_assessment_prompt(
        problem, problem_set, new_messages, variant
    )
    assessment_response = tutor.get_response(assessment_prompt)
    new_assessment_history = assessment_history + assessment_response["messages"][1:]
    if len(new_assessment_history) <= 1:
        raise ValueError("Something went wrong. The assessment history is empty.")

    previous_intent = intent_history[-1] if intent_history else [Intent.S_STRATEGY]
    new_intent = get_intent(new_assessment_history[-1].content, previous_intent)

    prompt = get_tutor_prompt(problem, problem_set, chat_history, new_intent, variant)

    new_intent_history = intent_history + [new_intent]

    return (
        tutor.get_streaming_response(prompt),
        new_intent_history,
        new_assessment_history,
    )
