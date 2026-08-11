"""Read generation metadata from ComfyUI, A1111, and NovelAI images."""

from __future__ import annotations

import json
import re

from easy_panel_app.model_profiles import (
    is_anima_model,
    is_illustrious_model,
    is_krea2_model,
)

def _num(value):
    """Best-effort numeric conversion returning None for non-numeric values."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        value = value.strip()
        try:
            return int(value)
        except ValueError:
            pass
        try:
            return float(value)
        except ValueError:
            pass
    return None


def _seed(value):
    """Return seeds as decimal strings so JSON never loses 64-bit precision."""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else None
    if isinstance(value, str):
        value = value.strip()
        if re.fullmatch(r"[+-]?\d+", value):
            return value.lstrip("+")
    return None


def _resolve_clip_text(nodes: dict, ref) -> str:
    """Trace a node reference back to the CLIPTextEncode text it originates from."""
    queue = [ref]
    seen: set[str] = set()
    while queue:
        current = queue.pop(0)
        if not (isinstance(current, list) and current):
            continue
        node_id = str(current[0])
        if node_id in seen:
            continue
        seen.add(node_id)
        node = nodes.get(node_id)
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs", {}) or {}
        if class_type == "CLIPTextEncode":
            return str(inputs.get("text", "") or "")
        for value in inputs.values():
            if isinstance(value, list) and value:
                queue.append(value)
    return ""


def _empty_image_result(source: str) -> dict:
    return {"source": source, "model": "", "family": "sdxl", "positive": "",
            "negative": "", "steps": None, "cfg": None, "sampler": "", "scheduler": "",
            "seed": None, "width": None, "height": None,
            "base_width": None, "base_height": None, "hires": {"enabled": False},
            "output_enhancement": {"mode": "off"}, "face_detailer": False,
            "hand_detailer": False, "foot_detailer": False,
            "color_match": False,
            "loras": [], "prediction": ""}


def parse_comfyui_prompt(workflow: dict) -> dict:
    """Extract generation parameters from a ComfyUI API-format workflow (the 'prompt' chunk)."""
    result = _empty_image_result("comfyui")
    nodes = workflow if isinstance(workflow, dict) else {}
    ksamplers: list[dict] = []
    has_model_upscale = False
    hires_scale = None
    hires_method = ""
    for node in nodes.values():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type", ""))
        inputs = node.get("inputs", {}) or {}
        if class_type == "KSampler":
            model_input = inputs.get("model")
            model_node = nodes.get(str(model_input[0])) if isinstance(model_input, list) and model_input else None
            model_inputs = model_node.get("inputs", {}) if isinstance(model_node, dict) else {}
            is_seedvr_sampler = (
                isinstance(model_node, dict)
                and model_node.get("class_type") == "UNETLoader"
                and "seedvr2" in str(model_inputs.get("unet_name", "")).lower()
            )
            if not is_seedvr_sampler:
                ksamplers.append(node)
        elif class_type == "CheckpointLoaderSimple":
            result["model"] = str(inputs.get("ckpt_name", "") or "")
        elif class_type == "UNETLoader":
            unet_name = str(inputs.get("unet_name", "") or "")
            if "seedvr2" not in unet_name.lower():
                result["model"] = unet_name
                result["family"] = "anima"
        elif class_type in ("LoraLoader", "LoraLoaderModelOnly"):
            name = str(inputs.get("lora_name", "") or "")
            if name:
                result["loras"].append({"name": name,
                                         "strength": _num(inputs.get("strength_model", 0.7)) or 0.7})
        elif class_type == "EmptyLatentImage":
            result["width"] = _num(inputs.get("width"))
            result["height"] = _num(inputs.get("height"))
            result["base_width"] = result["width"]
            result["base_height"] = result["height"]
        elif class_type == "LatentUpscaleBy":
            hires_scale = _num(inputs.get("scale_by"))
            hires_method = str(inputs.get("upscale_method", "") or "")
        elif class_type == "ImageScale":
            result["width"] = _num(inputs.get("width")) or result["width"]
            result["height"] = _num(inputs.get("height")) or result["height"]
            hires_method = str(inputs.get("upscale_method", "") or "")
        elif class_type == "ImageUpscaleWithModel":
            has_model_upscale = True
        elif class_type in ("SeedVR2Conditioning", "SeedVR2PostProcessing"):
            result["output_enhancement"]["mode"] = "seedvr2"
        elif class_type == "UltimateSDUpscale":
            result["output_enhancement"] = {
                "mode": "ultimate",
                "scale": _num(inputs.get("upscale_by")),
                "denoise": _num(inputs.get("denoise")),
                "steps": _num(inputs.get("steps")),
            }
        elif class_type == "FaceDetailer":
            detector_model = ""
            detector_ref = inputs.get("bbox_detector")
            if isinstance(detector_ref, list) and detector_ref:
                detector_node = nodes.get(str(detector_ref[0])) or nodes.get(detector_ref[0])
                if isinstance(detector_node, dict):
                    detector_model = str((detector_node.get("inputs") or {}).get("model_name", "")).lower()
            if "hand_" in detector_model or "/hand" in detector_model:
                result["hand_detailer"] = True
            elif "foot_" in detector_model or "/foot" in detector_model:
                result["foot_detailer"] = True
            else:
                result["face_detailer"] = True
        elif class_type == "ColorTransfer":
            result["color_match"] = True
        elif class_type == "ModelSamplingDiscrete":
            result["prediction"] = str(inputs.get("sampling", "") or "")
    if ksamplers:
        inputs = ksamplers[0].get("inputs", {}) or {}
        result["seed"] = _seed(inputs.get("seed"))
        result["steps"] = _num(inputs.get("steps"))
        result["cfg"] = _num(inputs.get("cfg"))
        result["sampler"] = str(inputs.get("sampler_name", "") or "")
        result["scheduler"] = str(inputs.get("scheduler", "") or "")
        result["positive"] = _resolve_clip_text(nodes, inputs.get("positive"))
        result["negative"] = _resolve_clip_text(nodes, inputs.get("negative"))
        if len(ksamplers) > 1:
            second = ksamplers[-1].get("inputs", {}) or {}
            if hires_scale is None and result["base_width"] and result["width"]:
                inferred = result["width"] / result["base_width"]
                hires_scale = round(round(inferred / 0.05) * 0.05, 2)
            result["hires"] = {
                "enabled": True,
                "scale": hires_scale,
                "denoise": _num(second.get("denoise")),
                "steps": _num(second.get("steps")),
                "cfg": _num(second.get("cfg")),
                "sampler": str(second.get("sampler_name", "") or ""),
                "scheduler": str(second.get("scheduler", "") or ""),
                "upscale_method": hires_method,
            }
        elif has_model_upscale and result["output_enhancement"]["mode"] == "off":
            result["output_enhancement"] = {
                "mode": "anime6b",
                "scale": (round(result["width"] / result["base_width"], 2)
                          if result["width"] and result["base_width"] else None),
            }
    return result


def parse_comfyui_ui_workflow(data: dict) -> dict:
    """Extract parameters from ComfyUI's UI-format workflow (the 'workflow' chunk)."""
    result = _empty_image_result("comfyui")
    nodes = data.get("nodes", []) or []
    links = data.get("links", []) or []

    def node_by_id(node_id):
        for node in nodes:
            if isinstance(node, dict) and node.get("id") == node_id:
                return node
        return None

    def resolve_text(node, input_name):
        seen: set = set()
        queue = [(node, input_name)]
        while queue:
            current, name = queue.pop(0)
            if not isinstance(current, dict):
                continue
            node_id = current.get("id")
            if node_id in seen:
                continue
            seen.add(node_id)
            ntype = str(current.get("type", ""))
            widgets = current.get("widgets_values", []) or []
            if ntype == "CLIPTextEncode" and widgets:
                return str(widgets[0] or "")
            if name == "__any__":
                for entry in current.get("inputs", []) or []:
                    link_id = entry.get("link")
                    if link_id is None:
                        continue
                    for link in links:
                        if isinstance(link, list) and link and link[0] == link_id:
                            upstream = node_by_id(link[1])
                            if upstream:
                                queue.append((upstream, "__any__"))
                            break
                continue
            link_id = None
            for entry in current.get("inputs", []) or []:
                if str(entry.get("name", "")) == name:
                    link_id = entry.get("link")
                    break
            if link_id is None:
                continue
            for link in links:
                if isinstance(link, list) and link and link[0] == link_id:
                    upstream = node_by_id(link[1])
                    if upstream:
                        queue.append((upstream, "__any__"))
                    break
        return ""

    ksamplers: list[dict] = []
    for node in nodes:
        if not isinstance(node, dict):
            continue
        ntype = str(node.get("type", ""))
        widgets = node.get("widgets_values", []) or []
        if ntype == "KSampler":
            result["seed"] = _seed(widgets[0] if len(widgets) > 0 else None)
            result["steps"] = _num(widgets[2] if len(widgets) > 2 else None)
            result["cfg"] = _num(widgets[3] if len(widgets) > 3 else None)
            result["sampler"] = str(widgets[4] or "") if len(widgets) > 4 else ""
            result["scheduler"] = str(widgets[5] or "") if len(widgets) > 5 else ""
            ksamplers.append(node)
        elif ntype == "CheckpointLoaderSimple":
            if widgets:
                result["model"] = str(widgets[0] or "")
        elif ntype == "UNETLoader":
            if widgets:
                result["model"] = str(widgets[0] or "")
                result["family"] = "anima"
        elif ntype in ("LoraLoader", "LoraLoaderModelOnly"):
            if widgets and widgets[0]:
                result["loras"].append({"name": str(widgets[0]),
                                         "strength": _num(widgets[1] if len(widgets) > 1 else 0.7) or 0.7})
        elif ntype == "EmptyLatentImage":
            if len(widgets) >= 2:
                result["width"] = _num(widgets[0])
                result["height"] = _num(widgets[1])
                result["base_width"] = result["width"]
                result["base_height"] = result["height"]
    if ksamplers:
        result["positive"] = resolve_text(ksamplers[0], "positive")
        result["negative"] = resolve_text(ksamplers[0], "negative")
    return result


def parse_a1111_parameters(text: str) -> dict:
    """Parse A1111 / WebUI 'parameters' text into generation fields."""
    result = _empty_image_result("a1111")
    parts = str(text or "").split("Negative prompt:", 1)
    result["positive"] = parts[0].strip()
    rest = parts[1] if len(parts) > 1 else ""
    if "Steps:" in rest:
        negative, params = rest.split("Steps:", 1)
        result["negative"] = negative.strip()
        # The value of "Steps:" directly follows the split, so restore the key
        # to make the first "key: value" pair parseable.
        params = "Steps:" + params
        for pair in params.split(","):
            if ":" not in pair:
                continue
            key, value = pair.split(":", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "steps":
                result["steps"] = _num(value)
            elif key == "cfg scale":
                result["cfg"] = _num(value)
            elif key == "sampler":
                result["sampler"] = value
            elif key == "scheduler":
                result["scheduler"] = value
            elif key == "seed":
                result["seed"] = _seed(value)
            elif key == "model":
                result["model"] = value
            elif key == "size":
                wh = re.split(r"[xX×]", value)
                if len(wh) == 2:
                    result["width"] = _num(wh[0])
                    result["height"] = _num(wh[1])
    else:
        result["negative"] = rest.strip()
    return result


def parse_novelai_comment(text: str) -> dict:
    """Parse NovelAI's 'Comment' JSON metadata."""
    result = _empty_image_result("novelai")
    try:
        data = json.loads(str(text or ""))
    except (TypeError, json.JSONDecodeError):
        return result
    if not isinstance(data, dict):
        return result
    result["positive"] = str(data.get("prompt", "") or "")
    result["negative"] = str(data.get("uc", "") or "")
    params = data.get("parameters", {}) or {}
    if isinstance(params, dict):
        result["steps"] = _num(params.get("steps"))
        result["cfg"] = _num(params.get("scale"))
        result["sampler"] = str(params.get("sampler", "") or "")
        result["seed"] = _seed(params.get("seed"))
        result["model"] = str(params.get("model", "") or "")
    return result


def _read_exif_user_comment(image) -> str:
    """Best-effort EXIF UserComment extraction for WebP / JPEG images."""
    try:
        exif = image.getexif()
        if not exif:
            return ""
        raw = None
        try:
            raw = exif.get_ifd(0x8769).get(37510)
        except Exception:
            pass
        if raw is None:
            raw = exif.get(37510)
        if isinstance(raw, bytes):
            for prefix in (b"ASCII\x00\x00\x00", b"\x00" * 8):
                if raw.startswith(prefix):
                    return raw[len(prefix):].decode("utf-8", "replace").rstrip("\x00")
            if raw.startswith(b"UNICODE\x00"):
                try:
                    return raw[8:].decode("utf-16", "replace").rstrip("\x00")
                except Exception:
                    pass
            return raw.decode("utf-8", "replace").rstrip("\x00")
        return str(raw or "")
    except Exception:
        return ""


def parse_generation_info(content: bytes) -> dict:
    """Read AI-generation metadata (prompt/params) embedded in a PNG/WebP/JPEG image."""
    try:
        from PIL import Image
        import io
    except ImportError as exc:
        raise ValueError("缺少 Pillow 库，无法读取图片元数据。") from exc
    try:
        image = Image.open(io.BytesIO(content))
        image.load()
        info = dict(getattr(image, "info", {}) or {})
    except Exception as exc:
        raise ValueError("无法解析图片文件：" + str(exc)) from exc
    chunks: dict[str, str] = {}
    for key, value in info.items():
        if isinstance(value, str):
            chunks[str(key)] = value
    if not any(key in chunks for key in ("parameters", "prompt", "Comment", "Description", "workflow")):
        user_comment = _read_exif_user_comment(image)
        if user_comment:
            chunks["parameters"] = user_comment
    if "parameters" in chunks:
        result = parse_a1111_parameters(chunks["parameters"])
    elif "prompt" in chunks or "workflow" in chunks:
        workflow_text = chunks.get("prompt") or chunks.get("workflow")
        try:
            parsed = json.loads(workflow_text)
        except (TypeError, json.JSONDecodeError):
            parsed = None
        if isinstance(parsed, dict) and isinstance(parsed.get("nodes"), list):
            result = parse_comfyui_ui_workflow(parsed)
        elif isinstance(parsed, dict):
            result = parse_comfyui_prompt(parsed)
        else:
            result = _empty_image_result("comfyui")
            result["positive"] = str(workflow_text or "")[:2000]
    elif "Comment" in chunks:
        result = parse_novelai_comment(chunks["Comment"])
    elif "Description" in chunks:
        result = parse_a1111_parameters(chunks["Description"])
    else:
        raise ValueError("未在图片中找到 AI 生成参数。请使用未经二次压缩的原始 PNG / WebP（ComfyUI、WebUI 或 NovelAI 生成）。")
    # The encoded workflow may describe the base latent rather than the saved
    # image after a hires pass. The file dimensions are the authoritative output.
    result["width"], result["height"] = image.size
    model = result.get("model", "")
    if is_anima_model(model):
        result["family"] = "anima"
    elif is_krea2_model(model):
        result["family"] = "krea2"
    elif is_illustrious_model(model):
        result["family"] = "illustrious"
    else:
        result["family"] = "sdxl"
    return result

__all__ = [
    "parse_a1111_parameters",
    "parse_comfyui_prompt",
    "parse_comfyui_ui_workflow",
    "parse_generation_info",
    "parse_novelai_comment",
]
