from wizard.engine import BaseStep, StepResult
from wizard.state import WizardState
from wizard import strings as S
from rich.prompt import Prompt
from rich.console import Console


class IdentityStep(BaseStep):
    title = S.STEP_IDENTITY

    def run(self, state: WizardState, console: Console) -> StepResult:
        console.print(S.t("back_hint"))

        agent_name_input = Prompt.ask(S.t("agent_name"), default=state.agent_name)
        if agent_name_input == 'b':
            return StepResult.BACK

        user_name_input = Prompt.ask(S.t("user_name"), default=state.user_name)
        if user_name_input == 'b':
            return StepResult.BACK

        state.agent_name = agent_name_input
        state.user_name = user_name_input

        return StepResult.NEXT
