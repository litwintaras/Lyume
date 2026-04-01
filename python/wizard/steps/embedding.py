from wizard.engine import BaseStep, StepResult
from wizard.state import WizardState
from wizard import strings as S
from rich.prompt import Prompt
from rich.console import Console
import httpx
from wizard.backend_detect import filter_embedding_models


class EmbeddingStep(BaseStep):
    title = S.STEP_EMBEDDING

    def run(self, state: WizardState, console: Console) -> StepResult:
        # Step 1: Fetch models from backend using state.llm_url
        try:
            r = httpx.get(f"{state.llm_url}/v1/models", timeout=5)
            all_ids = [m["id"] for m in r.json().get("data", [])]
        except Exception as e:
            console.print(S.t("embed_fetch_fail", url=state.llm_url, err=e))
            return StepResult.BACK

        # Step 2: Filter embedding models
        embed_models = filter_embedding_models(all_ids)

        selected_model = None
        dims = 768

        # Step 3: If embedding models found
        if embed_models:
            console.print(f"\n{S.t('embed_models_available')}")
            for i, m in enumerate(embed_models, 1):
                console.print(f"  {i}. {m}")

            choice = Prompt.ask(S.t("pick_embed_model"), default="1")
            if choice == 'b':
                return StepResult.BACK

            try:
                selected_model = embed_models[int(choice) - 1]
            except Exception:
                selected_model = None

        # Step 4: No embedding models found
        if not selected_model:
            console.print(f"\n! {S.t('no_embed_models')}")
            console.print(S.t("embed_recommend"))
            console.print(f"\n[1] {S.t('embed_download')}")
            console.print(f"[2] {S.t('embed_diff_url')}")
            console.print(f"[3] {S.t('embed_local_gguf')}")

            choice = Prompt.ask(S.t("embed_pick_option"), default="1")
            if choice == 'b':
                return StepResult.BACK

            if choice == '1':
                console.print(S.t("embed_run_ollama"))
                console.print(S.t("embed_then_restart"))
                return StepResult.BACK
            elif choice == '2':
                new_url = Prompt.ask(S.t("embed_enter_url"))
                if new_url == 'b':
                    return StepResult.BACK
                state.llm_url = new_url.rstrip('/').removesuffix("/v1")
                return self.run(state, console)
            elif choice == '3':
                path = Prompt.ask(S.t("enter_gguf_path"))
                if path == 'b':
                    return StepResult.BACK
                state.embed_provider = "local"
                state.embed_model_path = path
                state.embed_dimensions = 768
                return StepResult.NEXT
            else:
                return StepResult.BACK

        # Step 5: Test embedding endpoint if we have a model
        if selected_model:
            try:
                r = httpx.post(
                    f"{state.llm_url}/v1/embeddings",
                    json={"input": "test", "model": selected_model},
                    timeout=10
                )
                if r.status_code == 200:
                    data = r.json()
                    embeddings = data.get('data', [])
                    if embeddings:
                        dims = len(embeddings[0].get('embedding', []))
                        console.print(S.t("embed_dims", dims=dims))
            except Exception as e:
                console.print(S.t("embed_test_fail", err=e))

        # Step 6, 7: Save state
        state.embed_provider = "http"
        state.embed_url = state.llm_url
        state.embed_model = selected_model or ""
        state.embed_dimensions = dims

        return StepResult.NEXT
