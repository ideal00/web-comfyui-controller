"""Logical task expansion independent from HTTP and workflow construction."""

from __future__ import annotations

import re


MAX_BATCH_TASKS = 50
MAX_BATCH_IMAGES = 200
MAX_IMAGES_PER_TASK = 16


def expand_generation_jobs(jobs) -> list[dict]:
    """Expand logical panel tasks into independent ComfyUI prompt jobs."""

    if not isinstance(jobs, list) or not jobs or len(jobs) > MAX_BATCH_TASKS:
        raise ValueError(f"任务队列必须包含 1-{MAX_BATCH_TASKS} 个逻辑任务。")
    expanded: list[dict] = []
    for task_index, job in enumerate(jobs):
        if not isinstance(job, dict):
            raise ValueError("第 %d 个任务格式不正确。" % (task_index + 1))
        raw_count = job.get("batchCount", 1)
        try:
            image_count = int(raw_count)
        except (TypeError, ValueError):
            raise ValueError("第 %d 个任务的生成数量无效。" % (task_index + 1)) from None
        if not 1 <= image_count <= MAX_IMAGES_PER_TASK:
            raise ValueError(
                "第 %d 个任务的生成数量必须为 1-%d。"
                % (task_index + 1, MAX_IMAGES_PER_TASK)
            )
        for image_index in range(image_count):
            item = dict(job)
            item.pop("batchCount", None)
            seed_text = str(item.get("seed", "") or "").strip()
            if re.fullmatch(r"\d+", seed_text):
                item["seed"] = str((int(seed_text) + image_index) % (2**63 - 1))
            expanded.append(
                {
                    "task_index": task_index,
                    "image_index": image_index,
                    "image_count": image_count,
                    "payload": item,
                }
            )
    if len(expanded) > MAX_BATCH_IMAGES:
        raise ValueError(
            f"任务队列展开后共 {len(expanded)} 张，超过 {MAX_BATCH_IMAGES} 张上限；请拆成两次发送。"
        )
    return expanded


__all__ = [
    "MAX_BATCH_IMAGES",
    "MAX_BATCH_TASKS",
    "MAX_IMAGES_PER_TASK",
    "expand_generation_jobs",
]
