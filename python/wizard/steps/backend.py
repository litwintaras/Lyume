from wizard.engine import BaseStep, StepResult
from wizard.state import WizardState
from wizard import strings as S
from rich.prompt import Prompt
from rich.console import Console
import asyncio
from wizard.backend_detect import scan_backends, filter_llm_models
import httpx


class BackendStep(BaseStep):
    title = S.STEP_BACKEND

    def run(self, state: WizardState, console: Console) -> StepResult:
        backends = asyncio.run(scan_backends())

        # Select backend
        url = None
        if backends:
            console.print("\nFound backends:")
            for i, b in enumerate(backends, 1):
                console.print(f"  {i}. {b.name} ({b.url})")

            choice = Prompt.ask("Pick (1-N) or 'm' for manual or 'b' back", default="1")
            if choice == 'b':
                return StepResult.BACK
            if choice != 'm':
                try:
                    url = backends[int(choice) - 1].url.rstrip('/').removesuffix("/v1")
                except Exception:
                    pass

        # Manual URL if needed
        if url is None:
            url = Prompt.ask("Backend URL or 'b' back", default="http://localhost:8000")
            if url == 'b':
                return StepResult.BACK
            url = url.rstrip('/').removesuffix("/v1")

        # Fetch and filter models
        try:
            r = httpx.get(f"{url}/v1/models", timeout=5)
            all_ids = [m["id"] for m in r.json().get("data", [])]
            models = filter_llm_models(all_ids)
        except Exception:
            console.print("Could not fetch models")
            models = []

        # Select model
        if not models:
            model = Prompt.ask("No models found. Enter model name")
        else:
            console.print("\nLLM Models:")
            for i, m in enumerate(models, 1):
                console.print(f"  {i}. {m}")

            choice = Prompt.ask("Pick model or 'b' back", default="1")
            if choice == 'b':
                return StepResult.BACK
            try:
                model = models[int(choice) - 1]
            except Exception:
                model = choice

        # Save backend name from detected backends
        backend_name = "Custom"
        if backends:
            for b in backends:
                if b.url.rstrip("/").removesuffix("/v1") == url.rstrip("/"):
                    backend_name = b.name
                    break

        state.backend_name = backend_name
        state.llm_url = url
        state.llm_model = model

        return StepResult.NEXT
