"""Division Agent: standalone A2A server on :8004.

Run: python -m agents.div_agent
"""

from agents.base import run_math_agent


def divide(a: float, b: float) -> float:
    """Divide a by b and return a / b.

    Args:
        a: The dividend (number to be divided).
        b: The divisor (number to divide by).
    """
    if b == 0:
        raise ZeroDivisionError("division by zero is undefined")
    return a / b


if __name__ == "__main__":
    run_math_agent(
        key="div",
        name="Division Agent",
        symbol="/",
        tool=divide,
        description="Divides one number by another (a / b). Handles divide / quotient / division requests.",
        tags=["math", "arithmetic", "divide", "division", "quotient", "over"],
        examples=["6 / 2", "divide 10 by 4", "what is 9 divided by 3"],
    )
