"""Per-session market sampling; all checkpoint writes share the chat session lock."""
from __future__ import annotations

import asyncio
import copy
from contextvars import Context, ContextVar
from datetime import datetime, timezone
import logging
import time
from uuid import uuid4

from app.services.session_store import session_lock, session_can_read_checkpoint
from .service import direction_key
from .storage import Store

logger = logging.getLogger(__name__)
BUDGET_SECONDS = 60
FAILED = "岗位画像暂未整理完成，可以继续聊经历，或直接提供 JD。"
_tasks: dict[tuple, tuple[asyncio.Task, dict]] = {}
current_graph = ContextVar("job_intel_graph", default=None)


def cached_sample(direction):
    return Store().get("sample", direction_key(direction), 7)


def expired(profile):
    if profile.get("status") != "pending":
        return False
    try:
        return time.time() >= float(profile["deadline_at"])
    except (KeyError, TypeError, ValueError):
        return True


def expire_info(info):
    info = copy.deepcopy(info or {})
    if expired(info.get("role_profile") or {}):
        info["role_profile"].update(status="failed", message=FAILED)
    return info


def completed_info(info, result):
    info = copy.deepcopy(info)
    profile = info.get("role_profile") or {}
    if result.get("status") == "ok":
        profile = {key: value for key, value in profile.items()
                   if key not in {"task_id", "deadline_at", "started_at", "message", "candidate_count"}}
        profile.update(result["profile"], status="ready")
        info.update(role_profile=profile, source="market_sample",
                    fetched_at=profile["fetched_at"],
                    urls=[item["url"] for item in profile["sources"]])
        info.pop("intel_notice", None)
    else:
        info["role_profile"] = {**profile, "status": "failed",
                                "message": result.get("message") or FAILED}
    return info


async def refresh_expired(graph, session, values, *, locked=False):
    """Read endpoints never wait for generation. Re-read before the rare repair."""
    if not expired((values.get("jd_info") or {}).get("role_profile") or {}):
        return values

    async def repair():
        if not session_can_read_checkpoint(session):
            return values
        snapshot = await graph.aget_state({"configurable": {"thread_id": session}})
        latest = (snapshot.values if snapshot else {}) or {}
        info = expire_info(latest.get("jd_info"))
        if info != latest.get("jd_info"):
            await graph.aupdate_state({"configurable": {"thread_id": session}},
                                      {"jd_info": info}, as_node="dialogue")
        return {**latest, "jd_info": info}

    if locked:
        return await repair()
    lock = session_lock(session)
    if lock.locked():
        return {**values, "jd_info": expire_info(values.get("jd_info"))}
    async with lock:
        return await repair()


async def _merge(graph, session, task_id, *, result=None, count=None):
    async with session_lock(session):
        if not session_can_read_checkpoint(session):
            return  # deleted/expired sessions must never be resurrected
        config = {"configurable": {"thread_id": session}}
        snapshot = await graph.aget_state(config)
        values = (snapshot.values if snapshot else {}) or {}
        info = copy.deepcopy(values.get("jd_info") or {})
        profile = info.get("role_profile") or {}
        from app.services.resume_strategy import has_job_description
        if (profile.get("task_id") != task_id or profile.get("status") != "pending"
                or direction_key(info.get("role_direction", "")) != direction_key(profile.get("direction", ""))
                or values.get("jd_text") or has_job_description(info)):
            return  # a newer direction/JD or cancellation owns the checkpoint
        if expired(profile):
            info = expire_info(info)
        elif result is not None:
            info = completed_info(info, result)
        else:
            info["role_profile"] = {**profile, "candidate_count": count}
        await graph.aupdate_state(config, {"jd_info": info}, as_node="dialogue")


def schedule(graph, session, direction, llm, profile, sampler):
    key = (id(asyncio.get_running_loop()), session, direction_key(direction))
    existing = _tasks.get(key)
    if existing and not existing[0].done():
        return copy.deepcopy(existing[1])
    pending = {**profile, "status": "pending", "direction": direction,
               "task_id": uuid4().hex, "started_at": datetime.now(timezone.utc).isoformat(),
               "deadline_at": time.time() + BUDGET_SECONDS, "candidate_count": 0}

    async def run():
        progress = set()

        def on_progress(count):
            pending["candidate_count"] = count
            task = asyncio.create_task(_merge(graph, session, pending["task_id"], count=count))
            progress.add(task)

        result = {"status": "failed", "message": FAILED}
        try:
            async with asyncio.timeout(max(0, pending["deadline_at"] - time.time())):
                result = await sampler(direction, llm=llm, session=session, on_progress=on_progress)
        except asyncio.CancelledError:
            # Shutdown can interrupt persistence; the saved deadline repairs on read.
            raise
        except Exception as error:
            logger.info("job_intel_background_failed error_type=%s", type(error).__name__)
        finally:
            if progress:
                await asyncio.gather(*progress, return_exceptions=True)
        try:
            await _merge(graph, session, pending["task_id"], result=result)
        except Exception as error:
            logger.info("job_intel_background_save_failed error_type=%s", type(error).__name__)

    # Do not inherit a cancelled ChatTurn or LangGraph node callback/config.
    task = asyncio.create_task(run(), context=Context())
    _tasks[key] = (task, pending)

    def finished(done):
        if _tasks.get(key, (None,))[0] is done:
            _tasks.pop(key, None)
        if not done.cancelled():
            done.exception()  # failures are repaired by the persisted deadline

    task.add_done_callback(finished)
    return copy.deepcopy(pending)
