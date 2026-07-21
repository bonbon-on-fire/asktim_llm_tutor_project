from langchain_core.tools import tool
from langchain_experimental.utilities import PythonREPL

python_repl = PythonREPL()


@tool
def execute_python(program: str):
    """A Python shell. Use SymPy to solve complex equations. Use this to execute python commands. Input should be a valid python program. You must print the result using `print(...)`.
        Example input:```
    import sympy as sp

    # Define the symbol for the variable
    x = sp.Symbol('x')

    # Define the equation
    equation = sp.Eq(x**2 + 2*x + 1, 0)

    # Solve the equation
    solutions = sp.solve(equation, x)

    # Display the solutions
    print("Solutions:", solutions)```"""
    try:
        if "print" not in program:
            return (
                "No output printed: you forgot to print the result using `print(...)`"
            )
        res = python_repl.run(program.strip("`"))
        if res is None or res == "":
            return (
                "No output printed: you forgot to print the result using `print(...)`"
            )
        return res
    except Exception as e:
        return str(e)


@tool
def python_calculator(program: str):
    """A calculator. Use it to perform all complex computations at once. Input should be a valid python program with printed results. You must print the results using `print(...)`.
    example program input:
    ```
    result1 = 232+33/12
    print("result1 = ", result1)

    result2 = 167**0.5
    print("result2 = ", result2)
    ```"""
    try:
        if "print" not in program:
            if "\n" not in program:
                program = f"print({program})"
            else:
                return "No output printed: you forgot to print the result using `print(...)`"
        res = python_repl.run(program.strip("`"))
        if res is None or res == "":
            return (
                "No output printed: you forgot to print the result using `print(...)`"
            )
        return res
    except Exception as e:
        return str(e)


tutor_tools = [python_calculator, execute_python]
