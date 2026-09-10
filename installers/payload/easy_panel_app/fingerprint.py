"""生成任务指纹：判断两次提交是不是"完全相同的生成任务"。

指纹只覆盖「复现这张图需要的配方」——模型、LoRA 及权重、正向/负面提示词、
seed、采样参数、尺寸、二采参数、区域/局部重绘等；不包含请求 id、批次数量、
临时上传文件名、实验标签这些每次都会变的东西，所以同一次生成重复提交会得到
同一个指纹。

设计约定：
- 顶层只取标量字段，且跳过 ``IGNORED_KEYS`` 里的易变字段（未来新增的采样参数
  会自动进入指纹，不必每次改这里）；
- ``loras`` / ``promptSections`` / ``regions`` 等做排序或稳定化处理，
  顺序不同但内容相同的写法视为同一任务；
- 输出 ``{"version": 1, "hash": "<sha256>", "parts": {...}}``，
  其中 ``hash`` 存进创作索引，``parts`` 只用于界面展示与人眼核对。
"""

from __future__ import annotations

import hashlib
import json
import re

FINGERPRINT_VERSION = 1

# 每次都不同、与复现无关的字段
IGNORED_KEYS = {
    "requestId", "request_id", "clientId", "client_id", "clientToken", "jobId", "job_id",
    "batchCount", "batch_count", "batchId", "batch_id", "taskId", "task_id",
    "experiment", "experimentLabel", "experimentVariable", "experimentValue",
    "label", "note", "notes", "title", "favorite", "rating", "selected",
    "presetName", "savePresetName", "promptPresetName", "snapshotId", "snapshot_id",
    "promptId", "prompt_id", "generationId", "generation_id", "duplicatePolicy",
    "allowDuplicate", "queueMode", "createdAt", "created_at", "updatedAt", "updated_at",
    "source", "origin", "logicalTaskIndex", "generatedAt", "generated_at", "createdTime",
    "timestamp", "queuedAt", "startedAt", "finishedAt",
}

# 值是临时文件/上传物的字段（每次上传换名字，不代表配方变化）
VOLATILE_NESTED_KEYS = ("image", "imageName", "filename", "file", "mask", "maskName",
                        "upload", "uploadedImage", "uploadedMask", "path", "subfolder")

# 需要排序或稳定化的列表字段
LIST_KEYS = ("loras", "regions", "colorCorrection", "outputEnhancement")

_WHITESPACE = re.compile(r"\s+")


def _clean_text(value) -> str:
    text = str(value if value is not None else "")
    return _WHITESPACE.sub(" ", text).strip()


def _normalize_scalar(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    if value is None:
        return None
    return _clean_text(value).casefold()


def _normalize_loras(value) -> list:
    rows: list[tuple[str, str, str]] = []
    if isinstance(value, dict):
        for name, weight in value.items():
            rows.append((_clean_text(name).casefold(), str(_normalize_scalar(weight)), ""))
    elif isinstance(value, (list, tuple)):
        for entry in value:
            if isinstance(entry, dict):
                name = _clean_text(entry.get("name") or entry.get("lora") or entry.get("path"))
                weight = _normalize_scalar(entry.get("weight", entry.get("strength")))
                role = _clean_text(entry.get("role") or entry.get("source"))
                rows.append((name.casefold(), str(weight), role.casefold()))
            else:
                rows.append((_clean_text(entry).casefold(), "", ""))
    return sorted(row for row in rows if row[0])


def _normalize_regions(value) -> list:
    if isinstance(value, dict):
        value = list(value.values())
    rows: list[dict] = []
    if isinstance(value, (list, tuple)):
        for entry in value:
            if not isinstance(entry, dict):
                continue
            normalized = {key: _normalize_scalar(item) for key, item in sorted(entry.items())
                          if key not in VOLATILE_NESTED_KEYS}
            normalized["prompt"] = _clean_text(entry.get("prompt")).casefold()
            rows.append(normalized)
    # 分区是按位置生成的，比较时需要保留顺序，但可以按内容排序去重
    return sorted(rows, key=lambda row: json.dumps(row, sort_keys=True, ensure_ascii=False))


def _normalize_nested(value):
    if isinstance(value, dict):
        return {str(key): _normalize_nested(item) for key, item in sorted(value.items())
                if key not in VOLATILE_NESTED_KEYS}
    if isinstance(value, (list, tuple)):
        return [_normalize_nested(item) for item in value]
    return _normalize_scalar(value)


def fingerprint_parts(data) -> dict:
    """抽出参与指纹的字段（可用于界面展示"相同在哪"）。"""

    if not isinstance(data, dict):
        return {}
    parts: dict = {}
    for key, value in data.items():
        name = str(key)
        if name in IGNORED_KEYS or name.startswith("_"):
            continue
        if name == "loras":
            normalized = _normalize_loras(value)
        elif name == "regions":
            normalized = _normalize_regions(value)
        elif isinstance(value, dict):
            if name in ("promptSections", "prompt_sections"):
                normalized = {str(section): _clean_text(text).casefold()
                              for section, text in sorted(value.items())}
            else:
                normalized = _normalize_nested(value)
        elif isinstance(value, (list, tuple)):
            normalized = _normalize_nested(value)
        else:
            normalized = _normalize_scalar(value)
        if normalized in ("", None, [], {}):
            continue
        parts[name] = normalized
    return dict(sorted(parts.items()))


def generation_fingerprint(data) -> str:
    """返回稳定的 64 位十六进制指纹；配方为空时返回空串。"""

    parts = fingerprint_parts(data)
    if not parts:
        return ""
    payload = json.dumps({"version": FINGERPRINT_VERSION, "parts": parts},
                         ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def fingerprint_summary(data) -> dict:
    parts = fingerprint_parts(data)
    return {"version": FINGERPRINT_VERSION, "hash": generation_fingerprint(data), "parts": parts}


__all__ = ["FINGERPRINT_VERSION", "IGNORED_KEYS", "fingerprint_parts", "fingerprint_summary",
           "generation_fingerprint"]
