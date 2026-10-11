"""Addition Agent: standalone A2A server on :8001.

Run: python -m agents.add_agent
"""

from agents.base import run_math_agent


def add(a: float, b: float) -> float:
    """Add two numbers and return a + b.

    Args:
        a: The first number.
        b: The second number.
    """
    return a + b


if __name__ == "__main__":
    run_math_agent(
        key="add",
        name="Addition Agent",
        symbol="+",
        tool=add,
        description="Adds two numbers (a + b). Handles sum / plus / addition requests.",
        tags=["math", "arithmetic", "add", "addition", "sum", "plus"],
        examples=["5 + 42", "add 3 and 4", "what is the sum of 10 and 2"],
    )
