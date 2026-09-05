import pytest


def test_division_by_zero():
    """测试除以零的错误"""
    result = 10 / 0
    assert result == 5


def test_index_error():
    """测试索引错误"""
    lst = [1, 2, 3]
    value = lst[5]
    assert value == 4


def test_key_error():
    """测试键错误"""
    d = {"a": 1, "b": 2}
    value = d["c"]
    assert value == 3
