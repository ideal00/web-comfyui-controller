"""Anima 专属「高清重建（Highres Reconstruction）」：放大 → 二采 → 高清输出。

与「细节增强（Detail Refine）」是两件不同的事：

* Detail Refine = 同尺寸、低 denoise，只补高频细节（不放大，见 anima_refine.py）；
* Highres       = 学习型超分（Anime6B）→ 缩放回目标倍率 → VAE Encode →
                  二采 → Decode，让 Anima 在更高空间分辨率上重建细节。

本模块只负责 Anima 的高清重建参数与目标尺寸计算；工作流节点仍复用主流程
已有的 Hires 链（UpscaleModelLoader → ImageUpscaleWithModel → ImageScale →
VAEEncode → KSampler → VAEDecode），不新增第二套架构。

约束取自成熟 Anima 工作流（EasyUseAnima / AnimaFlow）：
倍率 1.15–2.0、denoise 0.20–0.35、默认 1.5× / 0.28、长边上限 2560；二采采样器与
调度器可被 ``animaHighres.sampler`` / ``.scheduler`` 覆盖（beta57 由 RES4LYF 提供）。
"""

from __future__ import annotations

#: 二采档位（前端 anima-highres.js 同步使用）：
#: 细节 = DPM++ 2M SDE GPU / SGM Uniform（默认）；保真 = ER-SDE / SGM Uniform；
#: 纹理 = ER-SDE / beta57（低噪声纹理，需 RES4LYF 节点）。
ANIMA_HIGHRES_PRESETS = {
    "detail": {"label": "二采·细节", "scale": 1.50, "denoise": 0.28, "steps": 24, "cfg": 4.2,
               "sampler": "dpmpp_2m_sde_gpu", "scheduler": "sgm_uniform",
               "denoise_range": [0.20, 0.35]},
    "fidelity": {"label": "二采·保真", "scale": 1.50, "denoise": 0.24, "steps": 24, "cfg": 4.2,
                 "sampler": "er_sde", "scheduler": "sgm_uniform",
                 "denoise_range": [0.20, 0.30]},
    "texture": {"label": "二采·纹理", "scale": 1.50, "denoise": 0.26, "steps": 24, "cfg": 4.2,
                "sampler": "er_sde", "scheduler": "beta57",
                "denoise_range": [0.20, 0.30]},
}

#: 兜底边界（profile 未提供 min/max 时使用）。
HIGHRES_SCALE_FLOOR = 1.15
HIGHRES_SCALE_CAP = 2.0
HIGHRES_DENOISE_FLOOR = 0.20
HIGHRES_DENOISE_CAP = 0.35
HIGHRES_STEPS_RANGE = (6, 40)
HIGHRES_CFG_RANGE = (1.0, 10.0)
DEFAULT_MAX_LONG_EDGE = 2560

#: 二采前「蒙版手部修复」：在 Anime6B 超分之前，用上传的黑白蒙版对手部区域
#: inpaint 一次（白色=重绘区），修好结构再进二采。默认值取常用手修复参数。
HAND_REPAIR_DEFAULTS = {
    "denoise": 0.45,
    "steps": 24,
    "grow": 6,
    "positive": "perfect hands, five fingers, detailed hands, natural hand pose",
    "negative": ("bad hands, extra fingers, missing fingers, fused fingers, "
                 "malformed hands, extra limbs, wrong finger count"),
}
HAND_REPAIR_DENOISE_RANGE = (0.20, 0.65)
HAND_REPAIR_STEPS_RANGE = (8, 40)
HAND_REPAIR_GROW_RANGE = (0, 48)


def _number(value, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    if number != number:  # NaN
        return float(default)
    return max(low, min(high, number))


def _align8(value: float) -> int:
    # 与前端 Math.round(x / 8) * 8 以及 sampling 对齐保持一致。
    return max(8, int(value / 8 + 0.5) * 8)


def normalize_anima_highres(data: dict, hires_defaults: dict | None,
                            base_width: int, base_height: int,
                            first_pass_cfg: float) -> dict:
    """把请求里的 ``animaHighres`` 收敛成一组安全参数（含目标尺寸）。

    ``hires_defaults`` 来自模型 profile 的 ``hires`` 段；Anima profile 提供
    1.5× / 0.25 / 20 步 / 4.8 CFG / 长边 2560 / Anime6B。请求值只允许在
    profile 的 [min_scale, max_scale] / [min_denoise, max_denoise] 内微调，
    长边超过上限时按比例缩回（再 8 对齐）。
    """

    raw = (data or {}).get("animaHighres")
    if not isinstance(raw, dict):
        raw = {}
    defaults = hires_defaults if isinstance(hires_defaults, dict) else {}

    enabled = bool(raw.get("enabled"))

    scale_min = _number(defaults.get("min_scale"), HIGHRES_SCALE_FLOOR, 1.0, 8.0)
    scale_max = _number(defaults.get("max_scale"), HIGHRES_SCALE_CAP, 1.0, 8.0)
    if scale_max < scale_min:
        scale_max = scale_min
    scale = _number(raw.get("scale"), defaults.get("scale", 1.5), scale_min, scale_max)

    denoise_min = _number(defaults.get("min_denoise"), HIGHRES_DENOISE_FLOOR, 0.0, 0.95)
    denoise_max = _number(defaults.get("max_denoise"), HIGHRES_DENOISE_CAP, 0.0, 1.0)
    if denoise_max < denoise_min:
        denoise_max = denoise_min
    denoise = _number(raw.get("denoise"), defaults.get("denoise", 0.25),
                      denoise_min, denoise_max)

    steps = int(round(_number(raw.get("steps"), defaults.get("steps", 24),
                              *HIGHRES_STEPS_RANGE)))
    cfg_default = defaults.get("cfg")
    if cfg_default in (None, ""):
        cfg_default = first_pass_cfg
    cfg = _number(raw.get("cfg"), cfg_default, *HIGHRES_CFG_RANGE)

    # 二采采样器/调度器：请求值 > profile 默认 > auto（auto = 按档位预设，
    # 只有 profile 也没给时才由主流程回退到首采）。
    def _pick_sampler(raw_value, default_value) -> str:
        text = str(raw_value or "").strip()
        if not text or text == "auto":
            text = str(default_value or "").strip()
        return text or "auto"

    sampler = _pick_sampler(raw.get("sampler"), defaults.get("sampler"))
    scheduler = _pick_sampler(raw.get("scheduler"), defaults.get("scheduler"))

    # 二采前手部修复：蒙版走 ComfyUI input 目录里的文件名（上传接口返回）；
    # cfg 默认跟随首采，denoise/steps/grow 各自有安全范围。
    hand_raw = raw.get("handRepair") if isinstance(raw.get("handRepair"), dict) else {}

    def _hand_text(key: str) -> str:
        value = hand_raw.get(key)
        if value is None:
            return HAND_REPAIR_DEFAULTS[key]
        return str(value).strip()[:400]

    hand_repair = {
        "enabled": bool(hand_raw.get("enabled")),
        "image": str(hand_raw.get("image") or "").strip(),
        "mask": str(hand_raw.get("mask") or "").strip(),
        "denoise": round(_number(hand_raw.get("denoise"), HAND_REPAIR_DEFAULTS["denoise"],
                                 *HAND_REPAIR_DENOISE_RANGE), 3),
        "steps": int(round(_number(hand_raw.get("steps"), HAND_REPAIR_DEFAULTS["steps"],
                                  *HAND_REPAIR_STEPS_RANGE))),
        "grow": int(round(_number(hand_raw.get("grow"), HAND_REPAIR_DEFAULTS["grow"],
                                 *HAND_REPAIR_GROW_RANGE))),
        "cfg": round(_number(hand_raw.get("cfg"), cfg, *HIGHRES_CFG_RANGE), 3),
        "positive": _hand_text("positive"),
        "negative": _hand_text("negative"),
    }

    max_long_edge = int(_number(defaults.get("max_long_edge"), DEFAULT_MAX_LONG_EDGE,
                                0, 8192))
    target_width = _align8(base_width * scale)
    target_height = _align8(base_height * scale)
    if max_long_edge > 0 and max(target_width, target_height) > max_long_edge:
        ratio = max_long_edge / max(target_width, target_height)
        target_width = _align8(target_width * ratio)
        target_height = _align8(target_height * ratio)

    return {
        "enabled": enabled,
        "scale": round(scale, 3),
        "denoise": round(denoise, 3),
        "steps": steps,
        "cfg": round(cfg, 3),
        "sampler": sampler,
        "scheduler": scheduler,
        "handRepair": hand_repair,
        "maxLongEdge": max_long_edge,
        "targetWidth": target_width,
        "targetHeight": target_height,
        "upscaler": str(defaults.get("upscaler") or "").strip(),
    }


__all__ = [
    "ANIMA_HIGHRES_PRESETS", "DEFAULT_MAX_LONG_EDGE", "HAND_REPAIR_DEFAULTS",
    "HAND_REPAIR_DENOISE_RANGE", "HAND_REPAIR_GROW_RANGE", "HAND_REPAIR_STEPS_RANGE",
    "HIGHRES_CFG_RANGE", "HIGHRES_DENOISE_CAP", "HIGHRES_DENOISE_FLOOR",
    "HIGHRES_SCALE_CAP", "HIGHRES_SCALE_FLOOR", "HIGHRES_STEPS_RANGE",
    "normalize_anima_highres",
]
