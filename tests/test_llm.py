from __future__ import annotations

from logisql.agent.llm import LLMResponseError, clean_sql_response, parse_json_response


def test_clean_sql_removes_markdown_fence() -> None:
    raw = "```sql\nSELECT order_id FROM orders LIMIT 5;\n```"
    assert clean_sql_response(raw) == "SELECT order_id FROM orders LIMIT 5;"


def test_clean_sql_removes_preamble() -> None:
    raw = "Here is the query you asked for:\nSELECT order_status FROM orders LIMIT 3"
    cleaned = clean_sql_response(raw, dialect="sqlite")
    assert cleaned == "SELECT order_status FROM orders LIMIT 3"


def test_parse_json_response_with_fence() -> None:
    raw = '```json\n{"headline": "Test", "summary": "Hello", "key_takeaways": ["a"]}\n```'
    parsed = parse_json_response(raw)
    assert parsed["headline"] == "Test"


def test_parse_json_response_with_surrounding_text() -> None:
    raw = 'Result follows: {"headline": "Test", "summary": "Hello"} -- done'
    parsed = parse_json_response(raw)
    assert parsed["summary"] == "Hello"


def test_parse_json_response_rejects_non_json() -> None:
    try:
        parse_json_response("not json at all")
    except LLMResponseError:
        return
    raise AssertionError("Expected LLMResponseError")
