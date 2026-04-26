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
        from app.agent.loop import _run_agent_loop_impl

        return _run_agent_loop_impl(loop_input, settings)
