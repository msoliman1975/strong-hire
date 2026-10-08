"""The interviewer (P7): a session controller in code and the interviewer's turn logic.

It depends only on strong_core, so the voice agent, the text-mode session API and the eval
harness all run the same logic:

    controller = SessionController(brief)        # phases, clock, time budget, probe limits
    interviewer = Interviewer(gateway, brief)    # what to say, and probe or move on
    runner = InterviewRunner(controller, interviewer)
    opening = await runner.open()                # interviewer turns
    replies = await runner.respond("candidate answer")
"""

from strong_interview.controller import (
    PROBE_LIMIT,
    CoachNotAllowedError,
    Move,
    MoveKind,
    SessionController,
    Why,
)
from strong_interview.interviewer import Interviewer, SessionFacts
from strong_interview.runner import InterviewRunner
from strong_interview.trace import ListTraceSink, TraceRecord, TraceSink

__all__ = [
    "PROBE_LIMIT",
    "CoachNotAllowedError",
    "InterviewRunner",
    "Interviewer",
    "ListTraceSink",
    "Move",
    "MoveKind",
    "SessionController",
    "SessionFacts",
    "TraceRecord",
    "TraceSink",
    "Why",
]
