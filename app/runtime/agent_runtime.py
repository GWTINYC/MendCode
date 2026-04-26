from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from app.agent.loop import AgentLoopInput, AgentLoopResult
from app.config.settings import Settings

AgentLoopRunner = Callable[[AgentLoopInput, Settings], AgentLoopResult]


class AgentRuntime(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    settings: Settings
    runner: AgentLoopRunner | None = None

    def run_turn(self, loop_input: AgentLoopInput) -> AgentLoopResult:
        runner = self.runner or self._default_runner
        return runner(loop_input, self.settings)

    @staticmethod
    def _default_runner(loop_input: AgentLoopInput, settings: Settings) -> AgentLoopResult:
        from app.runtime.agent_loop import run_agent_loop_turn

        return run_agent_loop_turn(loop_input, settings)
