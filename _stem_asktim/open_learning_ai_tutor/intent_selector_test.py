import pytest
import json
from open_learning_ai_tutor.constants import Intent, Assessment
from open_learning_ai_tutor.intent_selector import get_intent


@pytest.mark.parametrize(
    ("assessment_selections", "previous_intent", "intents"),
    [
        ([Assessment.IRRELEVANT_MESSAGE.value], [], [Intent.G_REFUSE]),
        (
            [Assessment.ASKING_FOR_CONCEPTS.value],
            [],
            [Intent.S_STATE, Intent.A_CURIOSITY],
        ),
        ([Assessment.ASKING_FOR_CALCULATION.value], [], [Intent.S_CALCULATION]),
        ([Assessment.ASKING_FOR_DEFINITION.value], [], [Intent.S_STATE]),
        ([Assessment.AMBIGUOUS_ANSWER.value], [], [Intent.P_ARTICULATION]),
        (
            [Assessment.AMBIGUOUS_ANSWER.value, Assessment.ASKING_FOR_SOLUTION.value],
            [],
            [Intent.P_HYPOTHESIS],
        ),
        (
            [
                Assessment.PARTIAL_CORRECT_ANSWER.value,
                Assessment.ASKING_FOR_CALCULATION.value,
            ],
            [],
            [Intent.S_CALCULATION],
        ),
        (
            [
                Assessment.PARTIAL_CORRECT_ANSWER.value,
                Assessment.ASKING_FOR_CALCULATION.value,
            ],
            [Intent.S_SELFCORRECTION],
            [Intent.S_CALCULATION, Intent.S_STRATEGY],
        ),
        ([Assessment.WRONG.value], [], [Intent.S_SELFCORRECTION]),
        (
            [Assessment.WRONG.value],
            [Intent.S_SELFCORRECTION],
            [Intent.S_CORRECTION, Intent.S_SELFCORRECTION],
        ),
        ([Assessment.ALGEBRAIC_ERROR.value], [], [Intent.S_SELFCORRECTION]),
        (
            [Assessment.ALGEBRAIC_ERROR.value],
            [Intent.S_SELFCORRECTION],
            [Intent.S_CORRECTION, Intent.S_SELFCORRECTION],
        ),
        ([Assessment.NUMERICAL_ERROR.value], [], [Intent.S_SELFCORRECTION]),
        (
            [Assessment.NUMERICAL_ERROR.value],
            [Intent.S_SELFCORRECTION],
            [Intent.S_CALCULATION],
        ),
        (
            [Assessment.ASKING_FOR_SOLUTION.value],
            [Intent.P_HYPOTHESIS],
            [Intent.S_HINT],
        ),
        ([Assessment.ASKING_FOR_SOLUTION.value], [], [Intent.P_HYPOTHESIS]),
        (
            [
                Assessment.ASKING_FOR_SOLUTION.value,
                Assessment.INCOMPLETE_SOLUTION.value,
            ],
            [],
            [Intent.S_STRATEGY, Intent.S_HINT],
        ),
        ([Assessment.WRONG.value], [], [Intent.S_SELFCORRECTION]),
        (
            [Assessment.WRONG.value, Assessment.ASKING_FOR_CALCULATION.value],
            [],
            [Intent.S_CALCULATION],
        ),
        (
            [Assessment.INCOMPLETE_SOLUTION.value],
            [],
            [Intent.S_STRATEGY, Intent.S_HINT],
        ),
        ([Assessment.PARTIAL_CORRECT_ANSWER.value], [], [Intent.S_STRATEGY]),
        ([Assessment.COMPLETE_SOLUTION.value], [], [Intent.G_GREETINGS]),
    ],
)
def test_intent_selector(assessment_selections, previous_intent, intents):
    """Test get_intent"""
    assessments = json.dumps({"selection": "".join(assessment_selections)})
    assert set(get_intent(assessments, previous_intent)) == set(intents)
