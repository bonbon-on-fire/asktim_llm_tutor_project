from tutor import json_mode as jm


def test_gate_defaults_on_and_falsey_off(monkeypatch):
    monkeypatch.delenv("TUTOR_JSON_MODE", raising=False)
    assert jm.json_mode_enabled() is True
    for off in ("0", "false", "no", "off", "OFF", " Off "):
        monkeypatch.setenv("TUTOR_JSON_MODE", off)
        assert jm.json_mode_enabled() is False
    monkeypatch.setenv("TUTOR_JSON_MODE", "1")
    assert jm.json_mode_enabled() is True


def test_anthropic_tool_kwargs_shape():
    kw = jm.anthropic_tool_kwargs()
    assert kw["tool_choice"] == {"type": "tool", "name": "tutor_reply"}
    tool = kw["tools"][0]
    assert tool["name"] == "tutor_reply"
    props = tool["input_schema"]["properties"]
    assert set(props) == {"pedagogical-reasoning", "Student-facing-answer"}
    assert tool["input_schema"]["additionalProperties"] is False
    assert set(tool["input_schema"]["required"]) == {"pedagogical-reasoning", "Student-facing-answer"}


def test_openai_response_format_shape():
    rf = jm.openai_response_format()
    assert rf["type"] == "json_schema"
    js = rf["json_schema"]
    assert js["name"] == "tutor_reply"
    assert js["strict"] is True
    assert set(js["schema"]["properties"]) == {"pedagogical-reasoning", "Student-facing-answer"}
