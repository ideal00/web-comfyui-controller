"""面板侧批量任务队列：可暂停、可取消、可只跑入选项、失败自动跳过。

ComfyUI 自己的队列只有「排队 / 执行中」，无法暂停，也不能只跑挑出来的实验项，
所以 EasyPanel 维护一层属于自己的任务队列：

- 队列只在「运行中」状态下把下一个任务交给 ComfyUI（暂停 = 不再投递新任务）；
- 每个任务记录自己的状态与 prompt_id，取消后续只取消还没投递/还在排队的任务；
- 失败自动跳过（默认开启）：单个任务出错只标记该任务失败，队列继续跑下一个；
  关闭后则暂停队列，等用户处理（对应「不要整个实验中断」的需求）；
- 只运行入选实验：实验项带 ``selected`` 标记，开启后未入选项直接记为 skipped。

本模块不依赖 HTTP、不依赖 ComfyUI，只做状态机与持久化，便于单测。
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

STATE_VERSION = 1
MAX_ITEMS = 400
SNAPSHOT_LIMIT = 200

PENDING = "pending"
RUNNING = "running"
COMPLETED = "completed"
ERROR = "error"
CANCELLED = "cancelled"
SKIPPED = "skipped"

TERMINAL_STATUSES = (COMPLETED, ERROR, CANCELLED, SKIPPED)
CLEANABLE_STATUSES = (ERROR, CANCELLED, SKIPPED)
ACTIVE_STATUSES = (PENDING, RUNNING)
CONTROL_ACTIONS = ("run", "pause", "cancel-current", "cancel-pending",
                   "clean-failed", "clean-finished", "select-only", "auto-skip", "select")


def _now_ms() -> int:
    return int(time.time() * 1000)


def _new_task_id() -> str:
    return "task_" + os.urandom(8).hex()


def _compact(value, limit: int = 200):
    text = str(value if value is not None else "").strip()
    return text[:limit]


class TaskQueue:
    """JSON 持久化的面板任务队列（进程内线程安全）。"""

    def __init__(self, path: Path, *, max_items: int = MAX_ITEMS) -> None:
        self.path = Path(path)
        self.max_items = max(1, int(max_items))
        self._lock = threading.RLock()
        self._state: dict = {"version": STATE_VERSION, "paused": False, "auto_skip": True,
                             "selected_only": False, "items": [], "message": ""}
        self._load()

    # ---------------------------------------------------------------- 持久化
    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
            payload = json.loads(raw) if raw.strip() else {}
        except (OSError, ValueError):
            payload = {}
        if isinstance(payload, dict):
            self._state["paused"] = bool(payload.get("paused"))
            self._state["auto_skip"] = bool(payload.get("auto_skip", True))
            self._state["selected_only"] = bool(payload.get("selected_only"))
            self._state["message"] = _compact(payload.get("message"), 200)
            items = payload.get("items")
            if isinstance(items, list):
                self._state["items"] = [item for item in items if isinstance(item, dict)][-self.max_items:]

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: self._state[key] for key in
                   ("version", "paused", "auto_skip", "selected_only", "message", "items")}
        handle = tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", newline="\n", dir=str(self.path.parent),
            prefix=self.path.name + ".", suffix=".tmp", delete=False,
        )
        try:
            json.dump(payload, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()
        os.replace(handle.name, self.path)

    # ---------------------------------------------------------------- 查询
    @property
    def paused(self) -> bool:
        with self._lock:
            return bool(self._state["paused"])

    @property
    def auto_skip(self) -> bool:
        with self._lock:
            return bool(self._state["auto_skip"])

    @property
    def selected_only(self) -> bool:
        with self._lock:
            return bool(self._state["selected_only"])

    def items(self) -> list[dict]:
        with self._lock:
            return [dict(item) for item in self._state["items"]]

    def counts(self) -> dict[str, int]:
        counted = {status: 0 for status in TERMINAL_STATUSES}
        counted[PENDING] = 0
        counted[RUNNING] = 0
        with self._lock:
            for item in self._state["items"]:
                status = str(item.get("status") or PENDING)
                counted[status] = counted.get(status, 0) + 1
        counted["total"] = sum(counted.values())
        return counted

    def snapshot(self, *, limit: int = SNAPSHOT_LIMIT) -> dict:
        with self._lock:
            items = [dict(item) for item in self._state["items"]]
            head = {
                "version": STATE_VERSION,
                "paused": bool(self._state["paused"]),
                "auto_skip": bool(self._state["auto_skip"]),
                "selected_only": bool(self._state["selected_only"]),
                "message": str(self._state["message"] or ""),
            }
        counts = {status: 0 for status in TERMINAL_STATUSES}
        counts[PENDING] = 0
        counts[RUNNING] = 0
        for item in items:
            status = str(item.get("status") or PENDING)
            counts[status] = counts.get(status, 0) + 1
        counts["total"] = len(items)
        running = next((item for item in items if str(item.get("status")) == RUNNING), None)
        shown = items[: max(1, int(limit))]
        return {**head, "counts": counts, "running": running, "items": shown,
                "truncated": len(items) > len(shown)}

    def get(self, task_id: str) -> dict | None:
        wanted = str(task_id or "")
        with self._lock:
            for item in self._state["items"]:
                if str(item.get("id")) == wanted:
                    return dict(item)
        return None

    def next_task(self) -> dict | None:
        """返回下一个可以投递的任务（只在运行状态调用）。"""

        with self._lock:
            if self._state["paused"]:
                return None
            if any(str(item.get("status")) == RUNNING for item in self._state["items"]):
                return None
            selected_only = bool(self._state["selected_only"])
            for item in self._state["items"]:
                if str(item.get("status")) != PENDING:
                    continue
                if selected_only and not bool(item.get("selected", True)):
                    item["status"] = SKIPPED
                    item["finished_at"] = _now_ms()
                    item["error"] = "未入选实验，已跳过。"
                    self._save()
                    continue
                return dict(item)
            return None

    # ---------------------------------------------------------------- 写入
    def add(self, tasks: list[dict], *, message: str = "") -> dict:
        if not tasks:
            raise ValueError("没有要加入队列的任务。")
        stamp = _now_ms()
        added: list[dict] = []
        with self._lock:
            room = self.max_items - len(self._state["items"])
            if room <= 0:
                raise ValueError(f"任务队列已满（{self.max_items} 条），请先清理失败或已完成任务。")
            for raw in tasks[:room]:
                item = {
                    "id": str(raw.get("id") or _new_task_id()),
                    "label": _compact(raw.get("label"), 120) or "任务",
                    "kind": _compact(raw.get("kind"), 32) or "generate",
                    "batch_id": _compact(raw.get("batch_id"), 64),
                    "task_index": int(raw.get("task_index") or 0),
                    "image_index": int(raw.get("image_index") or 0),
                    "image_count": int(raw.get("image_count") or 1),
                    "selected": bool(raw.get("selected", True)),
                    "experiment": _compact(raw.get("experiment"), 120),
                    "experiment_variable": _compact(raw.get("experiment_variable"), 32),
                    "experiment_value": _compact(raw.get("experiment_value"), 48),
                    "payload": raw.get("payload") if isinstance(raw.get("payload"), dict) else {},
                    "status": PENDING,
                    "prompt_id": "",
                    "snapshot_id": "",
                    "generation_id": "",
                    "duplicate_of": _compact(raw.get("duplicate_of"), 64),
                    "error": "",
                    "created_at": stamp,
                    "started_at": 0,
                    "finished_at": 0,
                }
                self._state["items"].append(item)
                added.append(dict(item))
            if message:
                self._state["message"] = _compact(message, 200)
            skipped = len(tasks) - len(added)
            self._save()
        return {"added": added, "added_count": len(added), "dropped": max(0, skipped),
                **self.snapshot()}

    def mark(self, task_id: str, status: str, **fields) -> dict | None:
        wanted = str(task_id or "")
        with self._lock:
            for item in self._state["items"]:
                if str(item.get("id")) != wanted:
                    continue
                item["status"] = str(status)
                if status == RUNNING and not item.get("started_at"):
                    item["started_at"] = _now_ms()
                if status in TERMINAL_STATUSES:
                    item["finished_at"] = _now_ms()
                for key, value in fields.items():
                    if key in {"prompt_id", "snapshot_id", "generation_id", "error",
                               "duplicate_of", "label", "selected", "experiment_value"}:
                        item[key] = value if not isinstance(value, str) else _compact(value, 400)
                self._save()
                return dict(item)
        return None

    def drop(self, statuses: tuple[str, ...]) -> dict:
        wanted = {str(status) for status in statuses}
        with self._lock:
            before = len(self._state["items"])
            kept = [item for item in self._state["items"] if str(item.get("status")) not in wanted]
            removed = before - len(kept)
            self._state["items"] = kept
            if removed:
                self._save()
        return {"removed": removed, **self.snapshot()}

    def cancel(self, *, include_running: bool) -> dict:
        """取消未完成任务；返回需要在 ComfyUI 侧删除的 prompt_id 列表。"""

        prompt_ids: list[str] = []
        cancelled = 0
        with self._lock:
            for item in self._state["items"]:
                status = str(item.get("status"))
                if status not in ACTIVE_STATUSES:
                    continue
                if status == RUNNING and not include_running:
                    continue
                if status == RUNNING and not item.get("prompt_id"):
                    continue
                if item.get("prompt_id"):
                    prompt_ids.append(str(item["prompt_id"]))
                item["status"] = CANCELLED
                item["finished_at"] = _now_ms()
                item["error"] = "已取消。"
                cancelled += 1
            if cancelled:
                self._state["message"] = f"已取消 {cancelled} 个任务。"
                self._save()
        return {"cancelled": cancelled, "prompt_ids": prompt_ids, **self.snapshot()}

    def set_flags(self, **flags) -> dict:
        with self._lock:
            for key, value in flags.items():
                if key in {"paused", "auto_skip", "selected_only"} and value is not None:
                    self._state[key] = bool(value)
            self._save()
        return self.snapshot()

    def select(self, ids, *, selected: bool = True) -> dict:
        wanted = {str(item) for item in (ids if isinstance(ids, (list, tuple, set)) else [ids])}
        with self._lock:
            for item in self._state["items"]:
                if str(item.get("id")) in wanted:
                    item["selected"] = bool(selected)
            self._save()
        return self.snapshot()

    def note(self, message: str) -> dict:
        with self._lock:
            self._state["message"] = _compact(message, 200)
            self._save()
        return self.snapshot()

    def control(self, action: str, **payload) -> dict:
        name = str(action or "").strip().lower()
        if name not in CONTROL_ACTIONS:
            raise ValueError(f"未知的队列操作：{action}")
        if name == "run":
            result = self.set_flags(paused=False)
            result["message"] = "队列已继续。"
            return result
        if name == "pause":
            result = self.set_flags(paused=True)
            result["message"] = "队列已暂停：当前任务跑完，不再投递新任务。"
            return result
        if name == "cancel-current":
            return self.cancel(include_running=True)
        if name == "cancel-pending":
            return self.cancel(include_running=False)
        if name == "clean-failed":
            return self.drop(CLEANABLE_STATUSES)
        if name == "clean-finished":
            return self.drop(TERMINAL_STATUSES)
        if name == "select-only":
            value = payload.get("value", True)
            result = self.set_flags(selected_only=value)
            result["message"] = "只运行入选实验。" if value else "已恢复运行全部任务。"
            return result
        if name == "auto-skip":
            value = payload.get("value", True)
            result = self.set_flags(auto_skip=value)
            result["message"] = "失败自动跳过已开启。" if value else "失败自动跳过已关闭：任务失败会暂停队列。"
            return result
        return self.select(payload.get("ids"), selected=bool(payload.get("selected", True)))


class TaskQueueRunner:
    """把面板队列喂给 ComfyUI 的后台线程（单任务串行，便于暂停与取消）。"""

    def __init__(self, queue: TaskQueue, *, submit, probe, on_status=None, on_outputs=None,
                 poll_seconds: float = 2.0, missing_grace: int = 15,
                 clock=time.monotonic) -> None:
        self.queue = queue
        self.submit = submit            # submit(item) -> dict(prompt_id=..., snapshot_id=..., generation_id=...)
        self.probe = probe              # probe(prompt_id) -> (status, payload)
        self.on_status = on_status      # on_status(item, status, payload)
        self.on_outputs = on_outputs    # on_outputs(item, status, payload)
        self.poll_seconds = max(0.2, float(poll_seconds))
        self.missing_grace = max(1, int(missing_grace))
        self.clock = clock
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_poll = 0.0
        self._missing = 0
        self.last_error = ""

    # ---------------------------------------------------------------- 生命周期
    @property
    def alive(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="easy-panel-task-queue", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=3)
        self._thread = None

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as error:  # 后台线程绝不能让面板崩溃
                self.last_error = f"{type(error).__name__}: {error}"
            self._stop.wait(0.4)

    # ---------------------------------------------------------------- 状态机
    def tick(self) -> str:
        """推进一步；返回本步的动作（idle / submitted / completed / error / skipped / paused）。"""

        running = next((item for item in self.queue.items() if str(item.get("status")) == RUNNING), None)
        if running is not None:
            return self._advance(running)
        if self.queue.paused:
            return "paused"
        item = self.queue.next_task()
        if item is None:
            return "idle"
        try:
            result = self.submit(item) or {}
        except Exception as error:
            self._fail(item, f"{type(error).__name__}: {error}")
            return "error"
        self.queue.mark(str(item["id"]), RUNNING,
                        prompt_id=str(result.get("prompt_id") or ""),
                        snapshot_id=str(result.get("snapshot_id") or ""),
                        generation_id=str(result.get("generation_id") or ""),
                        error="")
        if self.on_status:
            self.on_status(self.queue.get(str(item["id"])) or item, RUNNING, result)
        self._last_poll = 0.0
        self._missing = 0
        return "submitted"

    def _advance(self, running: dict) -> str:
        now = self.clock()
        if now - self._last_poll < self.poll_seconds - 1e-9:
            return "waiting"
        self._last_poll = now
        prompt_id = str(running.get("prompt_id") or "")
        if not prompt_id:
            return "waiting"
        try:
            status, payload = self.probe(prompt_id)
        except Exception as error:
            self.last_error = f"{type(error).__name__}: {error}"
            return "waiting"
        status = str(status or "").lower()
        if status in {"completed", "done", "success"}:
            self.queue.mark(str(running["id"]), COMPLETED, error="")
            if self.on_outputs:
                self.on_outputs(self.queue.get(str(running["id"])) or running, COMPLETED, payload)
            return "completed"
        if status in {"error", "failed"}:
            self._fail(running, str((payload or {}).get("error") or "ComfyUI 执行失败。"))
            return "error"
        if status in {"cancelled", "interrupted"}:
            self.queue.mark(str(running["id"]), CANCELLED, error="已中断。")
            if self.on_outputs:
                self.on_outputs(self.queue.get(str(running["id"])) or running, CANCELLED, payload)
            return "cancelled"
        if status == "missing":
            self._missing += 1
            if self._missing >= self.missing_grace:
                self._fail(running, "任务在 ComfyUI 里已找不到记录，按失败处理。")
                return "error"
        else:
            self._missing = 0
        return "waiting"

    def _fail(self, item: dict, message: str) -> None:
        self.queue.mark(str(item["id"]), ERROR, error=message)
        current = self.queue.get(str(item["id"])) or item
        if self.on_status:
            self.on_status(current, ERROR, {"error": message})
        if not self.queue.auto_skip:
            self.queue.set_flags(paused=True)
            self.queue.note("任务失败已暂停队列（失败自动跳过已关闭）。")


__all__ = [
    "ACTIVE_STATUSES", "CANCELLED", "CLEANABLE_STATUSES", "COMPLETED", "CONTROL_ACTIONS",
    "ERROR", "MAX_ITEMS", "PENDING", "RUNNING", "SKIPPED", "STATE_VERSION", "TERMINAL_STATUSES",
    "TaskQueue", "TaskQueueRunner",
]
