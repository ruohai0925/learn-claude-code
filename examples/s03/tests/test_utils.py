"""
tests/test_utils.py — Unit tests for utils.py
Run with:  python -m pytest tests/
"""

import pytest

from utils import chunk_list, flatten, is_palindrome, reverse_string, unique


# ── reverse_string ─────────────────────────────────────────────────────────────

class TestReverseString:
    def test_basic(self):
        assert reverse_string("hello") == "olleh"

    def test_single_char(self):
        assert reverse_string("a") == "a"

    def test_empty_string(self):
        assert reverse_string("") == ""

    def test_palindrome_unchanged(self):
        assert reverse_string("racecar") == "racecar"

    def test_spaces_preserved(self):
        assert reverse_string("hello world") == "dlrow olleh"

    def test_type_error(self):
        with pytest.raises(TypeError):
            reverse_string(123)  # type: ignore[arg-type]


# ── is_palindrome ──────────────────────────────────────────────────────────────

class TestIsPalindrome:
    def test_true_lowercase(self):
        assert is_palindrome("racecar") is True

    def test_true_mixed_case_insensitive(self):
        assert is_palindrome("Racecar") is True

    def test_false(self):
        assert is_palindrome("hello") is False

    def test_case_sensitive_true(self):
        assert is_palindrome("Racecar", case_sensitive=True) is False

    def test_case_sensitive_exact_match(self):
        assert is_palindrome("racecar", case_sensitive=True) is True

    def test_empty_string(self):
        assert is_palindrome("") is True

    def test_single_char(self):
        assert is_palindrome("x") is True

    def test_type_error(self):
        with pytest.raises(TypeError):
            is_palindrome(42)  # type: ignore[arg-type]


# ── unique ─────────────────────────────────────────────────────────────────────

class TestUnique:
    def test_removes_duplicates(self):
        assert unique([1, 2, 2, 3, 1]) == [1, 2, 3]

    def test_preserves_order(self):
        assert unique([3, 1, 2, 1, 3]) == [3, 1, 2]

    def test_no_duplicates(self):
        assert unique([1, 2, 3]) == [1, 2, 3]

    def test_empty_list(self):
        assert unique([]) == []

    def test_all_duplicates(self):
        assert unique([7, 7, 7]) == [7]

    def test_mixed_types(self):
        assert unique([1, "a", 1, "a"]) == [1, "a"]

    def test_type_error(self):
        with pytest.raises(TypeError):
            unique("not a list")  # type: ignore[arg-type]


# ── chunk_list ─────────────────────────────────────────────────────────────────

class TestChunkList:
    def test_even_split(self):
        assert chunk_list([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

    def test_uneven_split(self):
        assert chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

    def test_size_larger_than_list(self):
        assert chunk_list([1, 2], 10) == [[1, 2]]

    def test_size_equals_list(self):
        assert chunk_list([1, 2, 3], 3) == [[1, 2, 3]]

    def test_size_one(self):
        assert chunk_list([1, 2, 3], 1) == [[1], [2], [3]]

    def test_empty_list(self):
        assert chunk_list([], 3) == []

    def test_value_error_zero_size(self):
        with pytest.raises(ValueError):
            chunk_list([1, 2], 0)

    def test_value_error_negative_size(self):
        with pytest.raises(ValueError):
            chunk_list([1, 2], -1)

    def test_type_error_not_list(self):
        with pytest.raises(TypeError):
            chunk_list("oops", 2)  # type: ignore[arg-type]

    def test_type_error_size_not_int(self):
        with pytest.raises(TypeError):
            chunk_list([1, 2], 1.5)  # type: ignore[arg-type]


# ── flatten ────────────────────────────────────────────────────────────────────

class TestFlatten:
    def test_already_flat(self):
        assert flatten([1, 2, 3]) == [1, 2, 3]

    def test_one_level(self):
        assert flatten([[1, 2], [3, 4]]) == [1, 2, 3, 4]

    def test_deeply_nested(self):
        assert flatten([1, [2, [3, [4, [5]]]]]) == [1, 2, 3, 4, 5]

    def test_mixed_depth(self):
        assert flatten([1, [2, [3, 4]], 5]) == [1, 2, 3, 4, 5]

    def test_empty_list(self):
        assert flatten([]) == []

    def test_nested_empty_lists(self):
        assert flatten([[], [[]], []]) == []

    def test_mixed_types(self):
        assert flatten([1, ["a", [True, None]]]) == [1, "a", True, None]

    def test_type_error(self):
        with pytest.raises(TypeError):
            flatten("not a list")  # type: ignore[arg-type]
