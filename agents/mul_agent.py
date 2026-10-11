"""Multiplication Agent: standalone A2A server on :8003.

Run: python -m agents.mul_agent
"""

from agents.base import run_math_agent


def multiply(a: float, b: float) -> float:
    """Multiply two numbers and return a * b.

    Args:
        a: The first number.
        b: The second number.
    """
    return a * b


if __name__ == "__main__":
    run_math_agent(
        key="mul",
        name="Multiplication Agent",
        symbol="*",
        tool=multiply,
        description="Multiplies two numbers (a * b). Handles times / product / multiplication requests.",
        tags=["math", "arithmetic", "multiply", "multiplication", "times", "product"],
        examples=["7 * 6", "multiply 3 by 4", "what is 5 times 8"],
    )
