from typing import Any, Dict, Optional

from core.models_catalog import catalog
from core.provider_manager import is_local_provider


def accumulate_usage(
    agent: Any,
    step_usage: Optional[Dict[str, Any]] = None,
    prompt_tokens_est: int = 0,
    output_tokens_est: int = 0,
) -> None:
    """Accumulates input/output/cache tokens and estimates USD cost based on API reporting or model pricing."""
    is_local = is_local_provider(
        agent.provider_key, getattr(agent, "api_type", ""), getattr(agent, "base_url", "")
    )
    is_free_model = catalog.is_free_model(agent.model)

    pricing = catalog.get_model_pricing(agent.provider_key, agent.model)
    p_prompt = pricing.get("prompt", 0.0)
    p_comp = pricing.get("completion", 0.0)
    p_cr = pricing.get("cache_read")
    p_cw = pricing.get("cache_write")

    if step_usage and step_usage.get("total_tokens", 0) > 0:
        in_tok = step_usage.get("prompt_tokens", 0)
        out_tok = step_usage.get("completion_tokens", 0)
        cache_read_tok = step_usage.get("cache_read_tokens", 0)
        cache_write_tok = step_usage.get("cache_write_tokens", 0)
        uncached_in = max(0, in_tok - cache_read_tok - cache_write_tok)

        api_cost = step_usage.get("cost")
        if api_cost is not None:
            cost = float(api_cost)
        elif is_local or is_free_model:
            cost = 0.0
        else:
            if p_cr is not None:
                cr_rate = p_cr
            else:
                cache_mult = 0.1 if getattr(agent, "api_type", "openai") == "anthropic" else 0.5
                cr_rate = p_prompt * cache_mult

            cw_rate = p_cw if p_cw is not None else (p_prompt * 1.25 if p_prompt > 0 else 0.0)

            cost = uncached_in * p_prompt + cache_read_tok * cr_rate + cache_write_tok * cw_rate + out_tok * p_comp

        agent.tokens_input += in_tok
        agent.tokens_output += out_tok
        agent.tokens_cache_read += cache_read_tok
        agent.last_context_tokens = in_tok
        agent.total_tokens += step_usage.get("total_tokens", in_tok + out_tok)
        agent.cost_usd += cost
    else:
        agent.tokens_input += prompt_tokens_est
        agent.tokens_output += output_tokens_est
        agent.last_context_tokens = prompt_tokens_est
        agent.total_tokens += prompt_tokens_est + output_tokens_est
        if not is_local and not is_free_model:
            agent.cost_usd += prompt_tokens_est * p_prompt + output_tokens_est * p_comp
