"""HTTP fetcher and wire payload parser for models.dev and OpenRouter catalogs."""

import asyncio
import logging
from typing import Any, Dict, List, Tuple

import httpx

from core.infrastructure.adapters.models_source import (
    MODELS_DEV_URL,
    OPENROUTER_MODELS_URL,
    extract_context_length,
    extract_provider_def,
)

logger = logging.getLogger(__name__)


async def fetch_catalog_endpoints(
    client: httpx.AsyncClient,
) -> Tuple[
    Dict[str, int],
    Dict[str, str],
    Dict[str, Dict[str, float]],
    Dict[str, List[str]],
    Dict[str, Dict[str, Any]],
]:
    """Fetch and parse catalog data from models.dev and OpenRouter APIs concurrently."""
    model_limits: Dict[str, int] = {}
    model_names: Dict[str, str] = {}
    model_pricing: Dict[str, Dict[str, float]] = {}
    model_modalities: Dict[str, List[str]] = {}
    provider_catalog: Dict[str, Dict[str, Any]] = {}

    mdev_res, openrouter_res = await asyncio.gather(
        client.get(MODELS_DEV_URL, timeout=10),
        client.get(OPENROUTER_MODELS_URL, timeout=10),
        return_exceptions=True,
    )

    # 1. Parse models.dev response
    if isinstance(mdev_res, httpx.Response) and mdev_res.status_code == 200:
        try:
            mdev_data = mdev_res.json()
            if isinstance(mdev_data, dict):
                for prov_key, prov_info in mdev_data.items():
                    if not isinstance(prov_info, dict):
                        continue
                    pdef = extract_provider_def(prov_key, prov_info)
                    if pdef:
                        provider_catalog[prov_key] = pdef
                    models_dict = prov_info.get("models", {})
                    if not isinstance(models_dict, dict):
                        continue
                    for m_key, m_info in models_dict.items():
                        if not isinstance(m_info, dict):
                            continue
                        full_id = f"{prov_key}/{m_key}"
                        alias_id = m_key

                        raw_name = m_info.get("name", m_key)
                        model_names[full_id] = raw_name
                        model_names[alias_id] = raw_name

                        limits_info = m_info.get("limit", {})
                        if isinstance(limits_info, dict):
                            ctx = limits_info.get("context")
                            if ctx and isinstance(ctx, (int, float)):
                                model_limits[full_id] = int(ctx)
                                model_limits[alias_id] = int(ctx)

                        cost_info = m_info.get("cost", {})
                        if isinstance(cost_info, dict):
                            p_in = float(cost_info.get("input") or 0.0)
                            p_out = float(cost_info.get("output") or 0.0)
                            p_cr = float(cost_info.get("cache_read") or 0.0)
                            p_cw = float(cost_info.get("cache_write") or 0.0)
                            # Convert models.dev 1M token costs to per-token rate
                            if p_in > 0:
                                p_in /= 1_000_000.0
                            if p_out > 0:
                                p_out /= 1_000_000.0
                            if p_cr > 0:
                                p_cr /= 1_000_000.0
                            if p_cw > 0:
                                p_cw /= 1_000_000.0
                            if p_in > 0 or p_out > 0 or p_cr > 0 or p_cw > 0:
                                pricing_item: Dict[str, float] = {"prompt": p_in, "completion": p_out}
                                if p_cr > 0:
                                    pricing_item["cache_read"] = p_cr
                                if p_cw > 0:
                                    pricing_item["cache_write"] = p_cw
                                model_pricing[full_id] = pricing_item
                                model_pricing[alias_id] = pricing_item

                        modalities_info = m_info.get("modalities", {})
                        if isinstance(modalities_info, dict):
                            in_mods = modalities_info.get("input", [])
                            if isinstance(in_mods, list) and in_mods:
                                model_modalities[full_id] = [str(x).lower() for x in in_mods]
                                model_modalities[alias_id] = [str(x).lower() for x in in_mods]
        except Exception as e:
            logger.warning("Error parsing models.dev response: %s", e)

    # 2. Parse OpenRouter response
    if isinstance(openrouter_res, httpx.Response) and openrouter_res.status_code == 200:
        try:
            or_data = openrouter_res.json()
            for m in or_data.get("data", []):
                if isinstance(m, dict) and "id" in m:
                    m_id = m["id"]
                    short_id = m_id.split("/")[-1].lower()
                    raw_name = m.get("name", "")
                    clean_name = raw_name.split(": ", 1)[-1] if ": " in raw_name else raw_name
                    if clean_name:
                        model_names.setdefault(m_id, clean_name)
                        model_names.setdefault(short_id, clean_name)

                    ctx = extract_context_length(m)
                    if ctx:
                        model_limits.setdefault(m_id, ctx)
                        model_limits.setdefault(short_id, ctx)

                    pricing_raw = m.get("pricing") if isinstance(m.get("pricing"), dict) else {}
                    p_prompt = float(pricing_raw.get("prompt") or 0.0)
                    p_comp = float(pricing_raw.get("completion") or 0.0)
                    p_cr = float(pricing_raw.get("input_cache_read") or pricing_raw.get("cache_read") or 0.0)
                    p_cw = float(pricing_raw.get("input_cache_write") or pricing_raw.get("cache_write") or 0.0)
                    if p_prompt > 0 or p_comp > 0 or p_cr > 0 or p_cw > 0:
                        pricing_item = {"prompt": p_prompt, "completion": p_comp}
                        if p_cr > 0:
                            pricing_item["cache_read"] = p_cr
                        if p_cw > 0:
                            pricing_item["cache_write"] = p_cw
                        model_pricing.setdefault(m_id, pricing_item)
                        model_pricing.setdefault(short_id, pricing_item)

                    arch = m.get("architecture") if isinstance(m.get("architecture"), dict) else {}
                    in_mods = arch.get("input_modalities", [])
                    if isinstance(in_mods, list) and in_mods:
                        normalized_mods = [str(x).lower() for x in in_mods]
                        model_modalities.setdefault(m_id, normalized_mods)
                        model_modalities.setdefault(short_id, normalized_mods)
        except Exception as e:
            logger.warning("Error parsing OpenRouter response: %s", e)

    return model_limits, model_names, model_pricing, model_modalities, provider_catalog
