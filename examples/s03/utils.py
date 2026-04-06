"""
utils.py — General-purpose utility functions.
"""

from typing import Any, Generator


# ── String helpers ────────────────────────────────────────────────────────────

def reverse_string(s: str) -> str:
    """Return the reverse of string *s*.

    Args:
        s: The input string.

    Returns:
        The reversed string.

    Examples:
        >>> reverse_string("hello")
        'olleh'
        >>> reverse_string("")
        ''
    """
    if not isinstance(s, str):
        raise TypeError(f"Expected str, got {type(s).__name__!r}")
    return s[::-1]


def is_palindrome(s: str, *, case_sensitive: bool = False) -> bool:
    """Return *True* if *s* reads the same forwards and backwards.

    Args:
        s: The input string.
        case_sensitive: When *False* (default) the check ignores case.

    Returns:
        Boolean indicating whether *s* is a palindrome.

    Examples:
        >>> is_palindrome("racecar")
        True
        >>> is_palindrome("Racecar")
        True
        >>> is_palindrome("Racecar", case_sensitive=True)
        False
        >>> is_palindrome("hello")
        False
    """
    if not isinstance(s, str):
        raise TypeError(f"Expected str, got {type(s).__name__!r}")
    normalized = s if case_sensitive else s.lower()
    return normalized == normalized[::-1]


# ── List helpers ──────────────────────────────────────────────────────────────

def unique(items: list[Any]) -> list[Any]:
    """Return a new list with duplicates removed, preserving original order.

    Args:
        items: The input list.

    Returns:
        A list containing each element of *items* exactly once.

    Examples:
        >>> unique([1, 2, 2, 3, 1])
        [1, 2, 3]
        >>> unique([])
        []
    """
    if not isinstance(items, list):
        raise TypeError(f"Expected list, got {type(items).__name__!r}")
    seen: set = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def chunk_list(items: list[Any], size: int) -> list[list[Any]]:
    """Split *items* into consecutive chunks of length *size*.

    The final chunk may be shorter than *size* if the list length is not
    evenly divisible.

    Args:
        items: The input list.
        size: Maximum length of each chunk. Must be a positive integer.

    Returns:
        A list of sub-lists.

    Raises:
        TypeError: If *items* is not a list or *size* is not an int.
        ValueError: If *size* is less than 1.

    Examples:
        >>> chunk_list([1, 2, 3, 4, 5], 2)
        [[1, 2], [3, 4], [5]]
        >>> chunk_list([], 3)
        []
    """
    if not isinstance(items, list):
        raise TypeError(f"Expected list, got {type(items).__name__!r}")
    if not isinstance(size, int):
        raise TypeError(f"size must be an int, got {type(size).__name__!r}")
    if size < 1:
        raise ValueError(f"size must be >= 1, got {size!r}")
    return [items[i : i + size] for i in range(0, len(items), size)]


def flatten(nested: list[Any]) -> list[Any]:
    """Recursively flatten an arbitrarily nested list.

    Args:
        nested: A list that may contain other lists as elements.

    Returns:
        A single flat list of all non-list elements.

    Examples:
        >>> flatten([1, [2, [3, 4]], 5])
        [1, 2, 3, 4, 5]
        >>> flatten([])
        []
    """
    if not isinstance(nested, list):
        raise TypeError(f"Expected list, got {type(nested).__name__!r}")

    def _iter(items: list[Any]) -> Generator[Any, None, None]:
        for item in items:
            if isinstance(item, list):
                yield from _iter(item)
            else:
                yield item

    return list(_iter(nested))
