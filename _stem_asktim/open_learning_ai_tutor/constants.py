from enum import Enum


class Intent(Enum):
    # Problematizing category
    P_LIMITS = 1
    P_GENERALIZATION = 2
    P_HYPOTHESIS = 3
    P_ARTICULATION = 4
    P_REFLECTION = 5
    P_CONNECTION = 6

    # Structuring category
    S_SELFCORRECTION = 11
    S_CORRECTION = 12
    S_STRATEGY = 13
    S_STATE = 14
    S_SIMPLIFY = 15
    S_CALCULATION = 16
    S_HINT = 17

    # Affective category
    A_CHALLENGE = 21
    A_CONFIDENCE = 22
    A_CONTROL = 23
    A_CURIOSITY = 24

    # Generic category
    G_GREETINGS = 31
    G_OTHER = 32
    G_REFUSE = 33


class Assessment(Enum):
    WRONG = "a"
    ALGEBRAIC_ERROR = "b"
    NUMERICAL_ERROR = "c"
    INCOMPLETE_SOLUTION = "d"
    AMBIGUOUS_ANSWER = "e"
    PARTIAL_CORRECT_ANSWER = "f"
    ASKING_FOR_SOLUTION = "g"
    ASKING_FOR_DEFINITION = "h"
    ASKING_FOR_CALCULATION = "i"
    COMPLETE_SOLUTION = "j"
    IRRELEVANT_MESSAGE = "k"
    ASKING_FOR_CONCEPTS = "l"
