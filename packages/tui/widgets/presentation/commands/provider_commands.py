"""Provider and model management slash commands (providers, models, thinking)."""
from __future__ import annotations

import asyncio
from typing import Any

from core.application.provider.actions import (
    fetch_grouped_models,
    get_current_thinking_effort,
    select_model,
    set_provider_credentials,
    set_thinking_effort,
)
from widgets.chat_input import ChatInput
from widgets.presentation.commands.base import BaseCommand
from widgets.presentation.screens.constants import MESSAGE_INPUT
from widgets.presentation.screens.model import ModelScreen
from widgets.presentation.screens.thinking_effort import ThinkingEffortScreen


class ProvidersCommand(BaseCommand):
    name = "/providers"
    aliases = ["/provider", "/connect"]
    description = "Manage AI providers and API keys"

    async def execute(self, app) -> None:
        from widgets.presentation.screens.providers import ProvidersScreen

        try:
            provs = await asyncio.to_thread(app.pm.load_providers, True)
        except Exception:
            provs = {}
        if not provs:
            app.notify("No available providers configured", severity="warning")
            return

        def _load_cfg() -> tuple:
            act_key = app.pm.get_active_provider_key()
            cfg_keys = {k: app.pm.get_api_key(k) for k in provs}
            dis_provs = app.pm.get_disabled_providers()
            return act_key, cfg_keys, dis_provs

        act_key, cfg_keys, dis_provs = await asyncio.to_thread(_load_cfg)

        def on_provider_selected(result: tuple[str, str] | None) -> None:
            if not result or not isinstance(result, tuple):
                app.query_one(MESSAGE_INPUT, ChatInput).focus()
                return

            selected_key, entered_key = result

            if entered_key is not None:
                fetched = set_provider_credentials(app.pm, selected_key, entered_key, app)
                if fetched:
                    asyncio.create_task(ModelsCommand().execute(app))
                else:
                    open_providers_screen(focus_key=selected_key)

        def open_providers_screen(focus_key: str | None = None) -> None:
            if focus_key:
                asyncio.create_task(
                    ProvidersCommand()._open_with_key(app, focus_key, on_provider_selected)
                )
                return
            app.push_screen(
                ProvidersScreen(
                    provs,
                    act_key,
                    cfg_keys,
                    disabled_providers=dis_provs,
                    pm=app.pm,
                ),
                callback=on_provider_selected,
            )

        open_providers_screen()

    async def _open_with_key(self, app, focus_key, on_provider_selected) -> None:
        from widgets.presentation.screens.providers import ProvidersScreen

        try:
            provs = await asyncio.to_thread(app.pm.load_providers, True)
        except Exception:
            return
        if not provs:
            app.notify("No available providers configured", severity="warning")
            return
        act_key = app.pm.get_active_provider_key()
        cfg_keys = {k: app.pm.get_api_key(k) for k in provs}
        dis_provs = app.pm.get_disabled_providers()
        app.push_screen(
            ProvidersScreen(
                provs,
                focus_key or act_key,
                cfg_keys,
                disabled_providers=dis_provs,
                pm=app.pm,
            ),
            callback=on_provider_selected,
        )


class ModelsCommand(BaseCommand):
    name = "/models"
    aliases = ["/model"]
    description = "Switch active LLM model"

    async def execute(self, app) -> None:
        if not getattr(app, "pm", None):
            app.notify("Provider manager not available", severity="warning")
            return

        grouped_models, is_disconnected = await fetch_grouped_models(app.pm)
        if not grouped_models:
            if is_disconnected:
                await ProvidersCommand().execute(app)
                return
            app.notify("Failed to fetch models: check API key or network connection", severity="warning")
            return

        curr_provider = app.pm.get_active_provider_key()
        curr_model = getattr(app.agent, "model", "") if getattr(app, "agent", None) else ""
        if not curr_model and hasattr(app.pm, "get_provider_model"):
            curr_model = app.pm.get_provider_model(curr_provider)

        def on_model_selected(selection: Any) -> None:
            if selection and isinstance(selection, (tuple, list)):
                selected_prov, selected_model = selection[0], selection[1]
                select_model(app.pm, app.agent, selected_prov, selected_model, app)
                app.refresh_status_footer()
            app.query_one(MESSAGE_INPUT, ChatInput).focus()

        app.push_screen(ModelScreen(grouped_models, curr_model, curr_provider, pm=app.pm), callback=on_model_selected)


class ThinkingEffortCommand(BaseCommand):
    name = "/thinking"
    aliases = ["/effort", "/reasoning"]
    description = "Set model reasoning and thinking effort"

    async def execute(self, app) -> None:
        if not getattr(app, "pm", None):
            app.notify("Provider manager not available", severity="warning")
            return

        provider_key, model_name, current_effort = get_current_thinking_effort(app.pm, app.agent)

        def on_effort_selected(effort: str):
            if not effort:
                app.query_one(MESSAGE_INPUT, ChatInput).focus()
                return

            set_thinking_effort(app.pm, provider_key, model_name, effort, app)
            app.query_one(MESSAGE_INPUT, ChatInput).focus()

        app.push_screen(ThinkingEffortScreen(current_effort), callback=on_effort_selected)
