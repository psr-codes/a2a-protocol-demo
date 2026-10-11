"""Subtraction Agent: standalone A2A server on :8002.

Run: python -m agents.sub_agent
"""

from agents.base import run_math_agent


def subtract(a: float, b: float) -> float:
    """Subtract b from a and return a - b.

    Args:
        a: The number to subtract from (minuend).
        b: The number to subtract (subtrahend).
    """
    return a - b


if __name__ == "__main__":
    run_math_agent(
        key="sub",
        name="Subtraction Agent",
        symbol="-",
        tool=subtract,
        description="Subtracts one number from another (a - b). Handles minus / difference / subtraction requests.",
        tags=["math", "arithmetic", "subtract", "subtraction", "minus", "difference"],
        examples=["10 - 4", "subtract 3 from 9", "what is 7 minus 2"],
    )
