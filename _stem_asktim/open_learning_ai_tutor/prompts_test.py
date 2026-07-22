import os
from unittest.mock import Mock
import pytest
from open_learning_ai_tutor.constants import Intent
from open_learning_ai_tutor.prompts import (
    ASSESSMENT_PROMPT_TEMPLATE,
    TUTOR_PROMPT_MAPPING,
    get_intent_prompt,
    get_system_prompt,
    intent_mapping,
    get_assessment_prompt,
    get_assessment_initial_prompt,
    get_tutor_prompt,
    langsmith_prompt_template,
    prompt_env_key,
)
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.prompts import ChatPromptTemplate
from langsmith.utils import LangSmithNotFoundError


class NonDjangoCache:
    """Mock cache class to simulate non-django cache behavior."""

    def __init__(self):
        self.cache = {}

    def get(self, key):
        return self.cache.get(key)

    def set(self, key, value):
        self.cache[key] = value


class DjangoCache(NonDjangoCache):
    """Mock cache class to simulate django cache behavior."""

    def set(self, key, value, timeout):  #
        self.cache[key] = f"{value} (cached for {timeout} seconds)"
        os.environ["CACHED_TEST_PROMPT"] = value


def fake_cache_function():
    """Cache function returning an empty dict"""
    return {}


def real_cache_function_with_set():
    """Cache function returning a dict with the prompt"""
    return DjangoCache()


def real_cache_function_without_set():
    """Cache function returning a dict with the prompt"""
    return Mock(
        get=Mock(return_value="My cached prompt"),
    )


@pytest.fixture
def mock_langsmith_environment(mocker):
    """Fixture to set up the environment for testing."""
    os.environ["MITOL_ENVIRONMENT"] = "rc"
    os.environ["LANGSMITH_API_KEY"] = "test_api_key"


@pytest.mark.parametrize(
    ("intents", "message"),
    [
        ([Intent.P_LIMITS], intent_mapping[Intent.P_LIMITS]),
        (
            [Intent.P_GENERALIZATION, Intent.P_HYPOTHESIS, Intent.P_ARTICULATION],
            f"{intent_mapping[Intent.P_GENERALIZATION]}{intent_mapping[Intent.P_HYPOTHESIS]}{intent_mapping[Intent.P_ARTICULATION]}",
        ),
        (
            [Intent.S_STATE, Intent.S_CORRECTION],
            f"{intent_mapping[Intent.S_STATE]}{intent_mapping[Intent.S_CORRECTION]}",
        ),
        (
            [Intent.G_REFUSE, Intent.P_ARTICULATION],
            "The student is asking something irrelevant to the problem. Explain politely that you can't help them on topics other than the problem. DO NOT ANSWER THEIR REQUEST\n",
        ),
        (
            [Intent.G_REFUSE],
            "The student is asking something irrelevant to the problem. Explain politely that you can't help them on topics other than the problem. DO NOT ANSWER THEIR REQUEST\n",
        ),
    ],
)
def test_intent_prompt(intents, message):
    """Test get_intent"""
    assert get_intent_prompt(intents) == message


@pytest.mark.parametrize("variant", ["canvas", "edx"])
def test_get_assessment_prompt(mocker, variant):
    """Test that the Assessor create_prompt method returns the correct prompt."""
    new_messages = [HumanMessage(content="what if i took the mean?")]

    problem = "problem"
    problem_set = "problem_set"

    prompt = get_assessment_prompt(problem, problem_set, new_messages, variant)
    if variant == "edx":
        initial_message = 'A student and their tutor are working on a problem set:\n\n\n*Problem Statement*:\nproblem\n\nThis problem is in xml format and includes a solution. The problem is part of a problem set.\n\n*Problem Set*:\n\nproblem_set\n\nSome information required to solve the problem may be in other parts of the problem set.\n\n\n\nThe tutor\'s utterances are preceded by "Tutor:" and the student\'s utterances are preceded by "Student:".\n\nAnalyze the last student\'s utterance.\nselect all the feedbacks that apply from "a,b,c,d,e,f,g,h,i,j,k,l".:\n\na:The student provided an incorrect answer to the problem\nb:The student made an error in the algebraic manipulation\nc:The student made a numerical error\nd:The student provided an intuitive or incomplete solution\ne:The student\'s answer is not clear or ambiguous\nf:The student correctly answered the tutor\'s previous question\ng:The student is explicitly asking about how to solve the problem\nh:The student is explicitly asking the tutor to state a specific theorem, definition, formula or programming command that is not the **direct answer** to the question they have to solve.\ni:The student is explicitly asking the tutor to perform a numerical calculation\nj:The student and tutor arrived at a complete solution for the entirety of the initial *Problem Statement*\nk:The student\'s message is *entirely* irrelevant to the problem at hand or to the material covered by the exercise.\nl:The student is asking about concepts or information related to the material covered by the problem, or is continuing such a discussion.\n\nProceed step by step. First briefly justify your selection, then provide a string containing the selected letters.\nAnswer in the following JSON format ONLY and do not output anything else:\n\n{\n    "justification": "..",\n    "selection": ".."\n\n}\n\nAnalyze the last student\'s utterance.\n'
    else:
        initial_message = 'A student and their tutor are working on a problem set:\n\n\n*Problem Statement*:\n\nThis is a problem set and solution. Both the problem set and solution set may consist of multiple files.\nThe following JSON object contains the problem set and solution files and their contents.\n\nproblem_set\n\nThe problem set contains multiple individual problems. The student may be asking for help with any of them.\n\n\nThe tutor\'s utterances are preceded by "Tutor:" and the student\'s utterances are preceded by "Student:".\n\nAnalyze the last student\'s utterance.\nselect all the feedbacks that apply from "a,b,c,d,e,f,g,h,i,j,k,l".:\n\na:The student provided an incorrect answer to the problem\nb:The student made an error in the algebraic manipulation\nc:The student made a numerical error\nd:The student provided an intuitive or incomplete solution\ne:The student\'s answer is not clear or ambiguous\nf:The student correctly answered the tutor\'s previous question\ng:The student is explicitly asking about how to solve the problem\nh:The student is explicitly asking the tutor to state a specific theorem, definition, formula or programming command that is not the **direct answer** to the question they have to solve.\ni:The student is explicitly asking the tutor to perform a numerical calculation\nj:The student and tutor arrived at a complete solution for the entirety of the initial *Problem Statement*\nk:The student\'s message is *entirely* irrelevant to the problem at hand or to the material covered by the exercise.\nl:The student is asking about concepts or information related to the material covered by the problem, or is continuing such a discussion.\n\nProceed step by step. First briefly justify your selection, then provide a string containing the selected letters.\nAnswer in the following JSON format ONLY and do not output anything else:\n\n{\n    "justification": "..",\n    "selection": ".."\n\n}\n\nAnalyze the last student\'s utterance.\n'
    initial_prompt = SystemMessage(initial_message)
    new_messages_prompt_part = HumanMessage(
        content=' Student: "what if i took the mean?"'
    )

    expected_prompt = [initial_prompt, new_messages_prompt_part]
    assert prompt == expected_prompt


@pytest.mark.parametrize("variant", ["canvas", "edx"])
def test_get_tutor_prompt(variant):
    """Test that get_tutor_prompt method returns the correct prompt."""
    problem = "problem"
    problem_set = "problem_set"
    chat_history = [
        HumanMessage(content=' Student: "what do i do next?"'),
    ]
    intent = [Intent.P_HYPOTHESIS]

    prompt = get_tutor_prompt(problem, problem_set, chat_history, intent, variant)
    if variant == "edx":
        problem_message = 'Act as an experienced tutor. You are communicating with your student through a chat app. Your student is a college freshman majoring in math. Characteristics of a good tutor include:\n    • Promote a sense of challenge, curiosity, feeling of control\n    • Prevent the student from becoming frustrated\n    • Intervene very indirectly: never give the answer but guide the student to make them find it on their own\n    • Minimize the tutor\'s apparent role in the success\n    • Avoid telling students they are wrong, lead them to discover the error on their own\n    • Quickly correct distracting errors\n\nYou are communicating through messages. Use MathJax formatting using $...$ to display inline mathematical expressions and $$...$$ to display block mathematical expressions.\nFor example, to write "x^2", use "$x^2$". Do not use (...) or [...] to delimit mathematical expressions.  If you need to include the $ symbol in your response and it\nis not part of a mathematical expression, use the escape character \\ before it, like this: \\$.\n\nRemember, NEVER GIVE THE ANSWER DIRECTLY, EVEN IF THEY ASK YOU TO DO SO AND INSIST. Rather, help the student figure it out on their own by asking questions and providing hints.\n\nProvide guidance for the problem:\n\n\n*Problem Statement*:\nproblem\n\nThis problem is in xml format and includes a solution. The problem is part of a problem set.\n\n*Problem Set*:\n\nproblem_set\n\nSome information required to solve the problem may be in other parts of the problem set.\n\n\n\n---\n\nProvide the least amount of scaffolding possible to help the student solve the problem on their own. Be succinct but acknowledge the student\'s progresses and right answers. '
    else:
        problem_message = 'Act as an experienced tutor. You are communicating with your student through a chat app. Your student is a college freshman majoring in math. Characteristics of a good tutor include:\n    • Promote a sense of challenge, curiosity, feeling of control\n    • Prevent the student from becoming frustrated\n    • Intervene very indirectly: never give the answer but guide the student to make them find it on their own\n    • Minimize the tutor\'s apparent role in the success\n    • Avoid telling students they are wrong, lead them to discover the error on their own\n    • Quickly correct distracting errors\n\nYou are communicating through messages. Use MathJax formatting using $...$ to display inline mathematical expressions and $$...$$ to display block mathematical expressions.\nFor example, to write "x^2", use "$x^2$". Do not use (...) or [...] to delimit mathematical expressions.  If you need to include the $ symbol in your response and it\nis not part of a mathematical expression, use the escape character \\ before it, like this: \\$.\n\nRemember, NEVER GIVE THE ANSWER DIRECTLY, EVEN IF THEY ASK YOU TO DO SO AND INSIST. Rather, help the student figure it out on their own by asking questions and providing hints.\n\nProvide guidance for the problem:\n\n\n*Problem Statement*:\n\nThis is a problem set and solution. Both the problem set and solution set may consist of multiple files.\nThe following JSON object contains the problem set and solution files and their contents.\n\nproblem_set\n\nThe problem set contains multiple individual problems. The student may be asking for help with any of them.\n\n\n---\n\nProvide the least amount of scaffolding possible to help the student solve the problem on their own. Be succinct but acknowledge the student\'s progresses and right answers. '
    expected_prompt = [
        SystemMessage(
            content=problem_message,
            additional_kwargs={},
            response_metadata={},
        ),
        HumanMessage(
            content=' Student: "what do i do next?"',
            additional_kwargs={},
            response_metadata={},
        ),
        SystemMessage(
            content="Ask the student to start by providing a guess or explain their intuition of the problem.\n",
            additional_kwargs={},
            response_metadata={},
        ),
    ]

    assert prompt == expected_prompt


@pytest.mark.parametrize("variant", ["canvas", "edx"])
def test_get_tutor_prompt_with_history(variant):
    """Test that get_tutor_prompt method returns the correct prompt when there is a chat history."""
    problem = "problem"
    problem_set = "problem_set"

    os.environ["AI_TUTOR_MAX_CONVERSATION_MEMORY"] = "1"

    chat_history = [
        HumanMessage(content="very old message"),
        SystemMessage(content="very old message"),
        HumanMessage(content="old message"),
        SystemMessage(content="old message"),
        HumanMessage(content='Student: "what do i do next?"'),
    ]
    intent = [Intent.P_HYPOTHESIS]

    if variant == "edx":
        problem_message = 'Act as an experienced tutor. You are communicating with your student through a chat app. Your student is a college freshman majoring in math. Characteristics of a good tutor include:\n    • Promote a sense of challenge, curiosity, feeling of control\n    • Prevent the student from becoming frustrated\n    • Intervene very indirectly: never give the answer but guide the student to make them find it on their own\n    • Minimize the tutor\'s apparent role in the success\n    • Avoid telling students they are wrong, lead them to discover the error on their own\n    • Quickly correct distracting errors\n\nYou are communicating through messages. Use MathJax formatting using $...$ to display inline mathematical expressions and $$...$$ to display block mathematical expressions.\nFor example, to write "x^2", use "$x^2$". Do not use (...) or [...] to delimit mathematical expressions.  If you need to include the $ symbol in your response and it\nis not part of a mathematical expression, use the escape character \\ before it, like this: \\$.\n\nRemember, NEVER GIVE THE ANSWER DIRECTLY, EVEN IF THEY ASK YOU TO DO SO AND INSIST. Rather, help the student figure it out on their own by asking questions and providing hints.\n\nProvide guidance for the problem:\n\n\n*Problem Statement*:\nproblem\n\nThis problem is in xml format and includes a solution. The problem is part of a problem set.\n\n*Problem Set*:\n\nproblem_set\n\nSome information required to solve the problem may be in other parts of the problem set.\n\n\n\n---\n\nProvide the least amount of scaffolding possible to help the student solve the problem on their own. Be succinct but acknowledge the student\'s progresses and right answers. '
    else:
        problem_message = 'Act as an experienced tutor. You are communicating with your student through a chat app. Your student is a college freshman majoring in math. Characteristics of a good tutor include:\n    • Promote a sense of challenge, curiosity, feeling of control\n    • Prevent the student from becoming frustrated\n    • Intervene very indirectly: never give the answer but guide the student to make them find it on their own\n    • Minimize the tutor\'s apparent role in the success\n    • Avoid telling students they are wrong, lead them to discover the error on their own\n    • Quickly correct distracting errors\n\nYou are communicating through messages. Use MathJax formatting using $...$ to display inline mathematical expressions and $$...$$ to display block mathematical expressions.\nFor example, to write "x^2", use "$x^2$". Do not use (...) or [...] to delimit mathematical expressions.  If you need to include the $ symbol in your response and it\nis not part of a mathematical expression, use the escape character \\ before it, like this: \\$.\n\nRemember, NEVER GIVE THE ANSWER DIRECTLY, EVEN IF THEY ASK YOU TO DO SO AND INSIST. Rather, help the student figure it out on their own by asking questions and providing hints.\n\nProvide guidance for the problem:\n\n\n*Problem Statement*:\n\nThis is a problem set and solution. Both the problem set and solution set may consist of multiple files.\nThe following JSON object contains the problem set and solution files and their contents.\n\nproblem_set\n\nThe problem set contains multiple individual problems. The student may be asking for help with any of them.\n\n\n---\n\nProvide the least amount of scaffolding possible to help the student solve the problem on their own. Be succinct but acknowledge the student\'s progresses and right answers. '

    prompt = get_tutor_prompt(problem, problem_set, chat_history, intent, variant)
    expected_prompt = [
        SystemMessage(
            content=problem_message,
            additional_kwargs={},
            response_metadata={},
        ),
        HumanMessage(
            content="old message",
            additional_kwargs={},
            response_metadata={},
        ),
        SystemMessage(
            content="old message",
            additional_kwargs={},
            response_metadata={},
        ),
        HumanMessage(
            content='Student: "what do i do next?"',
            additional_kwargs={},
            response_metadata={},
        ),
        SystemMessage(
            content="Ask the student to start by providing a guess or explain their intuition of the problem.\n",
            additional_kwargs={},
            response_metadata={},
        ),
    ]

    assert prompt == expected_prompt


@pytest.mark.parametrize("environment", ["dev", "rc", "prod"])
@pytest.mark.parametrize(
    ("prompt_name", "expected_prompt_name"),
    (
        ("tutor_my+Prompt", "tutor_myprompt"),
        ("my.Prompt.NAME", "mypromptname"),
        ("my-promPT_Name", "my-prompt_name"),
    ),
)
def test_prompt_env_key(environment, prompt_name, expected_prompt_name):
    """Test that the prompt_env_key function returns the correct key."""
    os.environ["MITOL_ENVIRONMENT"] = environment
    assert prompt_env_key(prompt_name) == f"{expected_prompt_name}_{environment}"


def test_langsmith_prompt_template_get(mocker, mock_langsmith_environment):
    """Test that the langsmith prompt template is retrieved correctly."""
    mock_prompt = "This is a test prompt"
    mock_key = "tutor_my+Prompt"
    mock_pull = mocker.patch(
        "open_learning_ai_tutor.prompts.LangsmithClient.pull_prompt",
        return_value=ChatPromptTemplate([("system", mock_prompt)]),
    )
    assert (
        langsmith_prompt_template(mock_key, {}).messages[0].prompt.template
        == mock_prompt
    )
    mock_pull.assert_called_once_with("tutor_myprompt_rc")


def test_langsmith_prompt_template_set_get(mocker, mock_langsmith_environment):
    """Test that the langsmith prompt template is set and retrieved correctly."""
    mock_prompt = "This is another test prompt"
    mock_key = "tutor_my-Prompt"
    mapping = {
        mock_key: mock_prompt,
    }
    mock_pull = mocker.patch(
        "open_learning_ai_tutor.prompts.LangsmithClient.pull_prompt",
        side_effect=LangSmithNotFoundError,
    )
    mock_push = mocker.patch(
        "open_learning_ai_tutor.prompts.LangsmithClient.push_prompt"
    )
    system_prompt = langsmith_prompt_template(mock_key, mapping)
    mock_pull.assert_called_once_with("tutor_my-prompt_rc")
    mock_push.assert_called_once_with(
        "tutor_my-prompt_rc", object=ChatPromptTemplate([("system", mapping[mock_key])])
    )
    assert system_prompt.messages[0].prompt.template == mock_prompt


def test_get_system_prompt_no_langsmith(mocker) -> str:
    """
    get_system_prompt should return default prompt if no langsmith API key is set.
    """
    os.environ["LANGSMITH_API_KEY"] = ""
    assert (
        get_system_prompt(
            "tutor_initial_assessment", TUTOR_PROMPT_MAPPING, fake_cache_function
        )
        == ASSESSMENT_PROMPT_TEMPLATE
    )


def test_get_system_prompt_with_langsmith_no_cache(
    mocker, mock_langsmith_environment
) -> str:
    """
    get_system_prompt should return langsmith prompt if langsmith API key is set.
    """
    mock_prompt = "This is the langsmith assessment prompt"
    mocker.patch(
        "open_learning_ai_tutor.prompts.LangsmithClient.pull_prompt",
        return_value=ChatPromptTemplate([("system", mock_prompt)]),
    )
    assert (
        get_system_prompt(
            "tutor_initial_assessment", TUTOR_PROMPT_MAPPING, fake_cache_function
        )
        == mock_prompt
    )


def test_get_system_prompt_with_langsmith_with_cache(
    mocker, mock_langsmith_environment
) -> str:
    """
    get_system_prompt should return cached_prompt if set.
    """
    assert (
        get_system_prompt(
            "tutor_initial_assessment",
            TUTOR_PROMPT_MAPPING,
            real_cache_function_without_set,
        )
        == "My cached prompt"
    )


def test_get_system_prompt_with_langsmith_set_cache(
    mocker, mock_langsmith_environment
) -> str:
    """
    get_system_prompt should cache a langsmith prompt.
    """
    langsmith_prompt = "My langsmith prompt"
    mocker.patch(
        "open_learning_ai_tutor.prompts.langsmith_prompt_template",
        return_value=ChatPromptTemplate([("system", langsmith_prompt)]),
    )
    assert (
        get_system_prompt(
            "tutor_initial_assessment",
            TUTOR_PROMPT_MAPPING,
            real_cache_function_with_set,
        )
        == langsmith_prompt
    )
    assert os.environ.get("CACHED_TEST_PROMPT") == langsmith_prompt


def test_get_system_prompt_with_langsmith_set_cache_error(
    mocker, mock_langsmith_environment
) -> str:
    """
    System prompt should return langsmith promot if cache raises an error.
    """

    def get_my_cache():
        return NonDjangoCache()

    mock_log = mocker.patch("open_learning_ai_tutor.prompts.logger.exception")
    langsmith_prompt = "My original prompt"
    mocker.patch(
        "open_learning_ai_tutor.prompts.langsmith_prompt_template",
        return_value=ChatPromptTemplate([("system", langsmith_prompt)]),
    )
    assert (
        get_system_prompt(
            "tutor_initial_assessment", TUTOR_PROMPT_MAPPING, get_my_cache
        )
        == langsmith_prompt
    )
    mock_log.assert_called_once_with(
        "Prompt cache could not be set for cache of class %s", NonDjangoCache.__name__
    )
