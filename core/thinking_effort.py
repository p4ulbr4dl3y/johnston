EFFORT_AUTO = "auto"
SUPPORTED_THINKING_EFFORTS = ("low", "medium", "high")
GEMINI_25_THINKING_BUDGET_BY_EFFORT = {
    "low": 1024,
    "medium": 8192,
    "high": 24576,
}


def normalize_thinking_effort(value: str | None) -> str | None:
    if not value:
        return None
    effort = str(value).strip().lower()
    if effort in ("", EFFORT_AUTO, "unset", "none"):
        return None
    if effort in SUPPORTED_THINKING_EFFORTS:
        return effort
    return None


def display_thinking_effort(value: str | None) -> str:
    return normalize_thinking_effort(value) or EFFORT_AUTO


def is_gemini_25_model(model: str) -> bool:
    model_id = (model or "").lower()
    return "gemini-2.5" in model_id


def is_gemini_3_model(model: str) -> bool:
    model_id = (model or "").lower()
    return "gemini-3" in model_id


def build_openai_thinking_kwargs(effort: str | None) -> dict[str, object]:
    normalized = normalize_thinking_effort(effort)
    return {"reasoning_effort": normalized} if normalized else {}


def build_anthropic_thinking_payload(effort: str | None) -> dict[str, object]:
    normalized = normalize_thinking_effort(effort)
    return {"output_config": {"effort": normalized}} if normalized else {}


def build_gemini_thinking_config(model: str, effort: str | None) -> dict[str, object] | None:
    normalized = normalize_thinking_effort(effort)
    if not normalized:
        return None
    if is_gemini_25_model(model):
        return {
            "thinkingBudget": GEMINI_25_THINKING_BUDGET_BY_EFFORT[normalized],
            "includeThoughts": True,
        }
    if is_gemini_3_model(model):
        return {"thinkingLevel": normalized}
    return None


def build_ollama_thinking_payload(effort: str | None) -> dict[str, object]:
    normalized = normalize_thinking_effort(effort)
    return {"think": normalized} if normalized else {}
