"""A simple greetings module providing greeting and farewell functions."""

__all__ = ["greet", "farewell"]


def greet(name):
    """Return a greeting message for the given name."""
    return f"Hello, {name}!"


def farewell(name):
    """Return a farewell message for the given name."""
    return f"Goodbye, {name}!"
