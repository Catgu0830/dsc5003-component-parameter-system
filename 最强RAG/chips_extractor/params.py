"""参数名单一事实源（Single Source of Truth）。

规则（强制）：发给模型的查询串**只能是英文**，且必须来自数据手册规格表中的原文标签。
中文只作为 gloss 供作者阅读，永不参与检索或提取。

用法：
    from chips_extractor.params import names, specs, keys, family_of

    names("stm32")            # -> ['Operating voltage', 'Operating temperature', ...]
    specs("stm32")            # -> [{'key','name','aliases','gloss','type','unit'}, ...]
    names("stm32")[0]         # 直接作为 route_run / one_query 的 query 参数

保证：
    - load() 时会校验所有 name 均为纯 ASCII（不含 CJK），否则抛 ParamNameError；
    - 参数顺序在 registry.json 中固定，不得在调用处重排。
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "params" / "registry.json"

_CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")


class ParamNameError(ValueError):
    """参数名不符合规范（非英文或缺失）。"""


_cache: Dict[str, dict] = {}


def _load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"找不到参数表: {REGISTRY_PATH}")
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def _validate(family: str, spec: dict) -> None:
    name = spec.get("name", "")
    if not name:
        raise ParamNameError(f"[{family}] 缺少 name 字段: {spec}")
    if _CJK.search(name):
        raise ParamNameError(
            f"[{family}] 参数名含中文，违反规范: {name!r}。"
            f"请改用数据手册中的英文原文标签。")
    if not re.fullmatch(r"[\x20-\x7e]+", name):
        raise ParamNameError(f"[{family}] 参数名含非 ASCII 字符: {name!r}")


def families() -> List[str]:
    reg = _load_registry()
    return [k for k in reg if not k.startswith("_")]


def load(family: str) -> dict:
    """返回某家族的完整定义（含已验证的 params 列表）。"""
    if family in _cache:
        return _cache[family]
    reg = _load_registry()
    if family not in reg:
        raise KeyError(f"未定义的家族 {family!r}，可用: {families()}")
    block = reg[family]
    for spec in block.get("params", []):
        _validate(family, spec)
    keys = [s["key"] for s in block["params"]]
    if len(keys) != len(set(keys)):
        raise ParamNameError(f"[{family}] key 重复: {keys}")
    _cache[family] = block
    return block


def specs(family: str) -> List[dict]:
    return list(load(family)["params"])


def names(family: str) -> List[str]:
    """按固定顺序返回英文参数名列表，可直接作为查询串使用。"""
    return [s["name"] for s in load(family)["params"]]


def keys(family: str) -> List[str]:
    return [s["key"] for s in load(family)["params"]]


def by_key(family: str) -> Dict[str, dict]:
    return {s["key"]: s for s in load(family)["params"]}


def by_name(family: str) -> Dict[str, dict]:
    return {s["name"]: s for s in load(family)["params"]}


def aliases(family: str) -> Dict[str, List[str]]:
    """name -> aliases，供存在性判定与宽松匹配使用（不用于查询）。"""
    return {s["name"]: list(s.get("aliases", [])) for s in load(family)["params"]}


def gloss(family: str) -> Dict[str, str]:
    """name -> 中文备注，仅供作者阅读。"""
    return {s["name"]: s.get("gloss", "") for s in load(family)["params"]}


def label(family: str) -> str:
    return load(family).get("label", family)


def family_of(chip: str) -> str:
    """按芯片名推断家族（用于选择参数表）。"""
    n = (chip or "").lower()
    if n.startswith("stm32"):
        return "stm32"
    if n.startswith("gd32"):
        return "gd32"
    if n.startswith("esp") or n.startswith("0a-esp"):
        return "esp"
    if n.startswith("ad"):
        return "adi_opamp"
    raise KeyError(f"无法推断 {chip!r} 的家族，请显式指定")


def as_query(family: str, key: str) -> str:
    """按 key 取英文查询串。"""
    spec = by_key(family).get(key)
    if not spec:
        raise KeyError(f"[{family}] 无此 key: {key}")
    return spec["name"]


# ─────────────────────── 适用性矩阵 ───────────────────────

APPLICABILITY_PATH = Path(__file__).resolve().parent.parent / "params" / "applicability.json"
_app_cache: Dict[str, Dict[str, List[str]]] = {}


def _applicability() -> Dict[str, Dict[str, List[str]]]:
    global _app_cache
    if _app_cache:
        return _app_cache
    if not APPLICABILITY_PATH.exists():
        _app_cache = {}
        return _app_cache
    _app_cache = json.loads(APPLICABILITY_PATH.read_text(encoding="utf-8"))
    return _app_cache


def applicable(family: str, chip: str, name: str) -> bool:
    """该参数在该文档中是否适用。

    依据 params/applicability.json（由 audit_params.py --emit-applicability 生成）。
    文件缺失或该文档未被审计时**返回 True**（fail-open），避免误伤正常实验。
    """
    app = _applicability()
    per_chip = app.get(family) or {}
    allowed = per_chip.get(chip)
    if allowed is None:
        return True
    return name in allowed


def applicable_params(family: str, chip: str) -> List[str]:
    """该文档适用的参数名列表；未审计时返回该家族全部参数。"""
    app = _applicability()
    per_chip = app.get(family) or {}
    allowed = per_chip.get(chip)
    return list(allowed) if allowed is not None else names(family)


# ─────────────────────── 量纲校验 ───────────────────────
# 每个参数在 registry 里声明 unit_kind（count/size/voltage/current/temperature/
# frequency/resolution/power/ratio/slew/noise/text）。提取结果的 unit 若明显属于
# 另一个量纲，说明答错了东西（如把 SPI 接口数答成 30 MHz），应判为无效。
_KIND_UNITS = {
    "count": {"", "pin", "pins", "timer", "timers", "interface", "interfaces",
              "channel", "channels", "controller", "controllers", "port", "ports",
              "instance", "instances", "unit", "units", "core", "cores", "gpio", "gpios"},
    "size": {"b", "byte", "bytes", "kb", "kbyte", "kbytes", "kbit", "kbits",
             "mb", "mbyte", "mbytes", "gb"},
    "voltage": {"v", "mv", "uv", "kv"},
    "current": {"a", "ma", "ua", "na", "pa"},
    "temperature": {"c", "°c", "℃", "degc", "deg.c", "k"},
    "frequency": {"hz", "khz", "mhz", "ghz"},
    "resolution": {"bit", "bits"},
    "power": {"dbm", "dbw", "w", "mw"},
    "ratio": {"db", "db/decade", "v/v", "%"},
    "slew": {"v/us", "v/μs", "v/µs", "v/ns", "ma/us"},
    "noise": {"nv/√hz", "nv/rthz", "uv/√hz", "pa/√hz", "fa/√hz", "nv"},
}

_KIND_TOKENS = {k: v for k, v in _KIND_UNITS.items()}


def normalize_unit(unit: str) -> str:
    u = (unit or "").strip().lower()
    for a, b in {"µ": "u", "μ": "u", "℃": "°c", "deg.c": "deg.c", "√hz": "√hz"}.items():
        u = u.replace(a, b)
    u = re.sub(r"\s+", "", u)
    return u


def detect_unit_kind(unit: str) -> str:
    """把单位字符串映射到量纲；无法判定时返回 'unknown'。"""
    u = normalize_unit(unit)
    for kind, vals in _KIND_TOKENS.items():
        if u in vals:
            return kind
    if "/" in u:
        if re.search(r"bits?/s$", u) or u.endswith("bps"):
            return "bitrate"
        if u.startswith(("nv", "uv", "pv")) and "hz" in u:
            return "noise"
        if u in _KIND_UNITS["slew"]:
            return "slew"
    return "unknown"


_name_kind_cache: Dict[str, str] = {}


def unit_kind_for_name(name: str) -> str:
    """按参数名查其声明的量纲（跨家族同名视为同一量纲）。"""
    if name in _name_kind_cache:
        return _name_kind_cache[name]
    for fam in [k for k in _load_registry() if not k.startswith("_")]:
        for spec in load(fam)["params"]:
            if spec["name"] == name:
                _name_kind_cache[name] = spec.get("unit_kind", "text")
                return _name_kind_cache[name]
    _name_kind_cache[name] = "text"
    return "text"


def unit_kind_ok(name: str, unit: str) -> bool:
    """返回该单位是否与参数声明的量纲相容。

    规则：能识别出明确量纲且与声明不符 → False；识别不出（unknown）或声明为 text → True。
    """
    declared = unit_kind_for_name(name)
    if declared in ("text", None):
        return True
    got = detect_unit_kind(unit)
    if got in ("unknown", "bitrate"):
        # bitrate 与 frequency 都不属于计数类，但为避免误杀，只拦"明确错"的情况
        return got != "bitrate" or declared in ("frequency", "size")
    return got == declared
