# -*- coding: utf-8 -*-
"""相机机位控制（BSK 语义）：把面板滑杆折算成加权相机提示词。

面板「机位控制」滑杆的值在生成时经本模块变成 ``(from left:0.72), (eye-level:3.00), ...``
这样的加权相机词，由 ``compile_prompt`` 直接并入正向提示词。本模块不加载任何模型——
真正的机位效果来自配套的「相机机位控制（BSK）」LoRA（Anima 版已装在 03_通用功能）。

参数语义对照 BSK 原生节点（``BSK_相机控制``，作者 灰暗x）的默认配置，数值请勿随手改，
否则面板滑杆位置和 BSK 原生节点画布上的位置会对不上：

- 方位 ``pos_x``：``az = x * pi`` 分解成 front / back / left / right 四个方向分量，
  按总和归一化后瓜分「方位预算 = azimuth.weight * 极向门控」。方向标签沿用 BSK 的映射
  （``right`` 分量输出 ``from left``、``left`` 分量输出 ``from right``），不要按字面纠正。
- 高度 ``pos_y``：互斥单档 bird / high / eye / low / worm。eye 是中心档（y=0 权重最高），
  其余档随 ``|y|`` 单调递增；整个高度轴不会同时输出两个方向，避免模型收到冲突信号。
- 距离 ``pos_z``：档位 ecu / cu / medium / full / wide，基础权重恒 1.00。
- 翻滚 ``roll``：``|roll| >= 0.15`` 时输出 dutch angle。
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Sequence

AZ_POLE = 0.9         # 相机接近完全指向上/下时，水平方位被门控掉
ELEV_EYE_MAX = 0.2    # 平视档上界，与俯视档下界一致
TILT_DEADZONE = 0.15  # 翻滚死区

DEFAULT_CONFIG: dict[str, Any] = {
    "weight_min": 0.1,
    "weight_max": 10.0,
    "no_weight": False,
    "no_weight_threshold": 0.5,
    "azimuth": {
        "enabled": True,
        "weight": 10.0,
        "deadzone_ratio": 0.2,
        "directions": {
            "front": {"tag": "from front", "enabled": True},
            "back": {"tag": "from behind", "enabled": True},
            "left": {"tag": "from right", "enabled": True},
            "right": {"tag": "from left", "enabled": True},
        },
    },
    "elevation": {
        "enabled": True,
        "extra": 10.0,
        "eye_peak": 3.0,
        "categories": {
            "bird": {"tag": "directly above, from above, aerial view,", "enabled": True},
            "high": {"tag": "high angle, from above", "enabled": True},
            "eye": {"tag": "eye-level", "enabled": True},
            "low": {"tag": "low angle, from below,", "enabled": True},
            "worm": {"tag": "directly below", "enabled": True},
        },
    },
    "distance": {
        "enabled": True,
        "extra": 0.0,
        "categories": {
            "ecu": {"tag": "extreme close-up", "enabled": True},
            "cu": {"tag": "close-up", "enabled": True},
            "medium": {"tag": "medium shot", "enabled": True},
            "full": {"tag": "full body", "enabled": True},
            "wide": {"tag": "wide shot", "enabled": True},
        },
    },
    "tilt": {"enabled": True, "deadzone": TILT_DEADZONE, "extra": 0.0, "dutch_tag": "dutch angle"},
    "extra_master": 1.0,
    "extras": {
        "lens": {"enabled": False, "value": "85mm lens"},
        "dof": {"enabled": False, "value": "shallow depth of field", "weight": 1.3},
        "movement": {"enabled": False, "value": "handheld camera"},
        "composition": {"enabled": False, "value": "rule of thirds"},
        "style": {"enabled": False, "value": "cinematic"},
    },
}

# 距离档位的 z 区间：档内权重从区间起点（0% 额外权重）线性爬到终点（100%）。
DIST_RANGES: dict[str, tuple[float, float]] = {
    "ecu": (0.7, 1.0),
    "cu": (0.2, 0.7),
    "medium": (-0.2, 0.2),
    "full": (-0.7, -0.2),
    "wide": (-1.0, -0.7),
}
# 中景/全身/远景：距离越远权重越大，档内 frac 要反向计算。
DIST_FAR_STRONGER = {"medium", "full", "wide"}

STATE_LIMIT = 1.0


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def _number(value: Any, fallback: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    if math.isnan(result) or math.isinf(result):
        return fallback
    return result


def _fmt_weight(weight: float) -> str:
    return f"{round(float(weight), 2):.2f}"


def _split_tags(tag: Any) -> list[str]:
    return [part.strip() for part in str(tag or "").split(",") if part.strip()]


def _emit_weighted(tag: Any, weight: float) -> list[str]:
    return [f"({part}:{_fmt_weight(weight)})" for part in _split_tags(tag)]


def _emit_plain(tag: Any) -> list[str]:
    return _split_tags(tag)


def elevation_key(y: float) -> str:
    if y > 0.7:
        return "bird"
    if y > ELEV_EYE_MAX:
        return "high"
    if y >= 0:
        return "eye"
    if y >= -0.7:
        return "low"
    return "worm"


def elevation_weight(cfg: Mapping[str, Any], y: float, key: str) -> float:
    """高度权重：极端档随 |y| 递增，中心档 eye 随 |y| 递减。"""
    elevation = cfg.get("elevation") or {}
    if key == "eye":
        peak = _number(elevation.get("eye_peak"), 3.0)
        t = _clamp(y / ELEV_EYE_MAX, 0.0, 1.0)
        return peak + (1.0 - peak) * t
    factor = 1.0 + _number(cfg.get("extra_master"), 1.0) * _number(elevation.get("extra"), 0.0)
    if factor <= 0:
        return 0.0
    return abs(y) * factor


def distance_key(z: float) -> str:
    if z > 0.7:
        return "ecu"
    if z > 0.2:
        return "cu"
    if z >= -0.2:
        return "medium"
    if z >= -0.7:
        return "full"
    return "wide"


def _distance_parts(cfg: Mapping[str, Any], z: float) -> list[str]:
    distance = cfg.get("distance") or {}
    if not distance.get("enabled", True):
        return []
    key = distance_key(z)
    category = (distance.get("categories") or {}).get(key)
    if not category or not category.get("tag") or not category.get("enabled", True):
        return []
    weight_min = _number(cfg.get("weight_min"), 0.1)
    weight_max = _number(cfg.get("weight_max"), 10.0)
    extra = _number(distance.get("extra"), 0.0)
    start, end = DIST_RANGES[key]
    if key in DIST_FAR_STRONGER:
        frac = _clamp((end - z) / (end - start), 0.0, 1.0)
    else:
        frac = _clamp((z - start) / (end - start), 0.0, 1.0)
    weight = _clamp(1.0 + frac * _number(cfg.get("extra_master"), 1.0) * extra, weight_min, weight_max)
    return _emit_weighted(category.get("tag"), weight)


def _tilt_parts(cfg: Mapping[str, Any], roll: float) -> list[str]:
    tilt = cfg.get("tilt") or {}
    if not tilt.get("enabled", True):
        return []
    if abs(roll) < _number(tilt.get("deadzone"), TILT_DEADZONE):
        return []
    weight_max = _number(cfg.get("weight_max"), 10.0)
    weight = 1.0 + _number(cfg.get("extra_master"), 1.0) * _number(tilt.get("extra"), 0.0)
    weight = min(weight_max, max(0.1, weight))
    return _emit_weighted(tilt.get("dutch_tag"), weight)


def _azimuth_ratios(x: float) -> dict[str, float]:
    az = x * math.pi
    ratios = {
        "front": max(0.0, math.cos(az)),
        "back": max(0.0, -math.cos(az)),
        "right": max(0.0, math.sin(az)),
        "left": max(0.0, -math.sin(az)),
    }
    total = sum(ratios.values())
    if total > 0:
        for name in ratios:
            ratios[name] /= total
    return ratios


def _azimuth_gate(y: float) -> float:
    return _clamp((1.0 - abs(y)) / (1.0 - AZ_POLE), 0.0, 1.0)


def _azimuth_parts(cfg: Mapping[str, Any], x: float, y: float) -> list[str]:
    azimuth = cfg.get("azimuth") or {}
    if not azimuth.get("enabled", True):
        return []
    weight_min = _number(cfg.get("weight_min"), 0.1)
    weight_max = _number(cfg.get("weight_max"), 10.0)
    deadzone = _number(azimuth.get("deadzone_ratio"), 0.2)
    budget = _number(azimuth.get("weight"), 10.0) * _azimuth_gate(y)
    parts: list[str] = []
    for name, ratio in _azimuth_ratios(x).items():
        direction = (azimuth.get("directions") or {}).get(name)
        if not direction or not direction.get("enabled", True):
            continue
        weight = ratio * budget
        if ratio <= 0 or weight < deadzone:
            continue  # 死区以下的方向不输出，避免把中线两侧都说成机位
        weight = _clamp(weight, weight_min, weight_max)
        parts.extend(_emit_weighted(direction.get("tag"), weight))
    return parts


def _elevation_parts(cfg: Mapping[str, Any], y: float) -> list[str]:
    elevation = cfg.get("elevation") or {}
    if not elevation.get("enabled", True):
        return []
    key = elevation_key(y)
    category = (elevation.get("categories") or {}).get(key)
    if not category or not category.get("tag") or not category.get("enabled", True):
        return []
    weight = elevation_weight(cfg, y, key)
    if weight <= 0:
        return []
    weight = _clamp(weight, _number(cfg.get("weight_min"), 0.1), _number(cfg.get("weight_max"), 10.0))
    return _emit_weighted(category.get("tag"), weight)


def _extras_parts(cfg: Mapping[str, Any]) -> list[str]:
    extras = cfg.get("extras") or {}
    parts: list[str] = []
    for key in ("lens", "dof", "movement", "composition", "style"):
        item = extras.get(key)
        if not item or not item.get("enabled"):
            continue
        value = str(item.get("value") or "").strip()
        if not value:
            continue
        if key == "dof":
            parts.append(f"({value}:{_fmt_weight(_number(item.get('weight'), 1.3))})")
        else:
            parts.append(value)
    return parts


def compute_camera_terms(x: float, y: float, z: float, roll: float,
                         cfg: Mapping[str, Any] | None = None) -> list[str]:
    """机位 → 提示词词条列表（加权模式）。"""
    settings: Mapping[str, Any] = cfg or DEFAULT_CONFIG
    parts: list[str] = []
    parts.extend(_azimuth_parts(settings, x, y))
    parts.extend(_elevation_parts(settings, y))
    parts.extend(_distance_parts(settings, z))
    parts.extend(_tilt_parts(settings, roll))
    parts.extend(_extras_parts(settings))
    return parts


def compute_camera_prompt(x: float, y: float, z: float, roll: float,
                          cfg: Mapping[str, Any] | None = None) -> str:
    """机位 → 单行提示词片段（与 BSK 节点输出一致，非空时以逗号结尾）。"""
    parts = compute_camera_terms(x, y, z, roll, cfg)
    result = ", ".join(parts)
    return result + "," if result else ""


def normalize_camera_control(raw: Any) -> dict[str, Any] | None:
    """把请求里的 cameraControl 规范化；未启用或形状不对时返回 None。"""
    if not isinstance(raw, Mapping) or not raw.get("enabled"):
        return None
    return {
        "enabled": True,
        "x": _clamp(_number(raw.get("x")), -STATE_LIMIT, STATE_LIMIT),
        "y": _clamp(_number(raw.get("y")), -STATE_LIMIT, STATE_LIMIT),
        "z": _clamp(_number(raw.get("z")), -STATE_LIMIT, STATE_LIMIT),
        "roll": _clamp(_number(raw.get("roll")), -STATE_LIMIT, STATE_LIMIT),
    }


def prompt_terms(data: Mapping[str, Any] | None) -> list[str]:
    """生成/编译提示词时使用：返回本次机位词条（未启用返回空列表）。"""
    if not isinstance(data, Mapping):
        return []
    state = normalize_camera_control(data.get("cameraControl"))
    if not state:
        return []
    return compute_camera_terms(state["x"], state["y"], state["z"], state["roll"])


def preview_response(data: Mapping[str, Any] | None) -> dict[str, Any]:
    """面板滑杆实时预览用（POST /api/camera-prompt）。"""
    state = normalize_camera_control(data.get("cameraControl") if isinstance(data, Mapping) else None)
    if state is None:
        state = {
            "enabled": True,
            "x": _clamp(_number((data or {}).get("x")), -STATE_LIMIT, STATE_LIMIT),
            "y": _clamp(_number((data or {}).get("y")), -STATE_LIMIT, STATE_LIMIT),
            "z": _clamp(_number((data or {}).get("z")), -STATE_LIMIT, STATE_LIMIT),
            "roll": _clamp(_number((data or {}).get("roll")), -STATE_LIMIT, STATE_LIMIT),
        }
    terms = compute_camera_terms(state["x"], state["y"], state["z"], state["roll"])
    return {
        "prompt": ", ".join(terms) + ("," if terms else ""),
        "terms": terms,
        "state": state,
        "weighted": True,
    }


def state_summary(state: Mapping[str, Any] | None) -> str:
    """一行式状态（日志/水印用）。"""
    if not state:
        return "机位控制：关闭"
    return "机位控制：X %.2f / Y %.2f / Z %.2f / Roll %.2f" % (
        _number(state.get("x")), _number(state.get("y")),
        _number(state.get("z")), _number(state.get("roll")))


__all__: Sequence[str] = (
    "DEFAULT_CONFIG",
    "compute_camera_prompt",
    "compute_camera_terms",
    "normalize_camera_control",
    "preview_response",
    "prompt_terms",
    "state_summary",
)
