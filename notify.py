"""Notification dispatcher — fans events out to all configured platforms.

Each backend (feishu_notify, slack_notify, dingtalk_notify, ...) is its own
parallel module with an identical public API. The dispatcher imports each one
optionally and calls every available backend on every event. A failure in one
backend does not block others, and is logged but never raised — kanban writes
must succeed even if every chat integration is down.

Calling sites use:

    import notify
    notify.notify_bug_created(...)

No backend code is loaded if the corresponding optional dependency is missing
or the env vars aren't set.
"""

import logging

log = logging.getLogger(__name__)

# ── Lazy, optional backend imports ──────────────────────────────────────
# Each backend is wrapped so an ImportError doesn't break the dispatcher.

_BACKENDS: list = []

try:
    import feishu_notify  # noqa: F401
    _BACKENDS.append(feishu_notify)
except ImportError:
    pass

try:
    import slack_notify  # noqa: F401
    _BACKENDS.append(slack_notify)
except ImportError:
    pass

try:
    import dingtalk_notify  # noqa: F401
    _BACKENDS.append(dingtalk_notify)
except ImportError:
    pass


def _dispatch(method_name: str, *args, **kwargs) -> None:
    """Call `method_name(*args, **kwargs)` on every loaded backend."""
    for backend in _BACKENDS:
        fn = getattr(backend, method_name, None)
        if fn is None:
            continue
        try:
            fn(*args, **kwargs)
        except Exception as e:
            log.warning(
                "notify backend %s.%s raised %s (swallowed)",
                backend.__name__, method_name, e,
            )


def notify_task_created(title: str, project: str, workstream: str,
                         assignee: str, actor: str) -> None:
    _dispatch("notify_task_created", title, project, workstream, assignee, actor)


def notify_task_status_changed(title: str, project: str, workstream: str,
                                old_status: str, new_status: str,
                                actor: str) -> None:
    _dispatch("notify_task_status_changed",
              title, project, workstream, old_status, new_status, actor)


def notify_blocker_created(description: str, project: str,
                            workstream: str, actor: str) -> None:
    _dispatch("notify_blocker_created", description, project, workstream, actor)


def notify_blocker_resolved(description: str, project: str,
                             workstream: str, actor: str) -> None:
    _dispatch("notify_blocker_resolved", description, project, workstream, actor)


def notify_bug_created(title: str, severity: str, reporter: str) -> None:
    _dispatch("notify_bug_created", title, severity, reporter)


def active_backends() -> list[str]:
    """Names of loaded backends, for diagnostics / GET /api/health."""
    return [b.__name__ for b in _BACKENDS]
