"""只记录保存阶段的耗时；不记录参数、结果、异常正文或学习内容。"""
from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import json
import logging
from threading import get_ident
from time import perf_counter_ns

LOGGER_NAME = "app.desktop_review.observation_timing"
_logger = logging.getLogger(LOGGER_NAME)
_parent = ContextVar("observation_timing_parent", default=None)


@contextmanager
def observation_span(name):
    started = perf_counter_ns()
    parent = _parent.get()
    token = _parent.set(started)
    outcome = "error"
    try:
        yield
        outcome = "ok"
    finally:
        finished = perf_counter_ns()
        _parent.reset(token)
        _logger.info("%s", json.dumps({
            "contract_version": "observation_timing_v1", "span": name,
            "started_ns": started, "finished_ns": finished,
            "elapsed_ms": (finished - started) / 1_000_000,
            "parent_started_ns": parent, "thread_id": get_ident(), "outcome": outcome,
        }, separators=(",", ":")))


def timed_observation(name):
    def decorate(function):
        @wraps(function)
        def run(*args, **kwargs):
            with observation_span(name):
                return function(*args, **kwargs)
        return run
    return decorate


def timed_call(name, function, *args, **kwargs):
    with observation_span(name):
        return function(*args, **kwargs)
