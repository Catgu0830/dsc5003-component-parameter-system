"""Normalize extracted values against the DB parameter dictionary."""
import math
import re
from decimal import Decimal

from .common import APIError

NUMBER = re.compile(r"^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)\s*(.*?)\s*$")
PREFIX = {
    "p": 1e-12, "n": 1e-9, "u": 1e-6, "µ": 1e-6, "μ": 1e-6,
    "m": 1e-3, "": 1, "k": 1e3, "K": 1e3, "M": 1e6, "G": 1e9,
}
SPEC_PREFIX = "[原文] "


def _text(value, name, limit, required=False):
    if value is None:
        if required:
            raise APIError(f"{name} is required")
        return None
    if not isinstance(value, str):
        value = str(value)
    value = value.strip()
    if required and not value:
        raise APIError(f"{name} is required")
    if len(value) > limit:
        raise APIError(f"{name} is too long")
    return value or None


def _unit(value):
    if value is None:
        return ""
    value = str(value).strip()
    value = (value.replace("ohms", "Ω").replace("ohm", "Ω")
                  .replace("Ohm", "Ω").replace("Ω", "Ω")
                  .replace("欧姆", "Ω").replace("伏", "V").replace("安", "A")
                  .replace("赫兹", "Hz").replace(" ", ""))
    return value


def numeric(value, unit, target_unit, name, allow_missing_unit=False):
    if isinstance(value, bool):
        raise APIError(f"{name}: boolean is not a numeric value")
    raw = str(value).strip().replace("±", "").replace("+/-", "")
    match = NUMBER.fullmatch(raw)
    if not match:
        raise APIError(f"{name}: numeric value expected; ranges/typ/min/max must be separate rows")
    inline = _unit(match.group(2))
    supplied = _unit(unit)
    if inline and supplied and inline != supplied:
        # CSV/XLSX often puts the SI prefix in the value ("10k") and the
        # canonical unit in a separate column ("Ω"): combine them.
        if supplied == target_unit and inline in PREFIX and inline != "":
            unit = inline + supplied
        elif supplied == target_unit and inline.endswith(target_unit):
            unit = inline
        else:
            raise APIError(f"{name}: conflicting inline unit and unit field")
    else:
        unit = inline or supplied
    number = float(match.group(1))
    if not math.isfinite(number):
        raise APIError(f"{name}: value is not finite")

    if target_unit is None:
        # Unitless numeric parameter (e.g. Pin Count): keep the number, ignore a unit.
        return number, None

    if not unit:
        if not allow_missing_unit:
            raise APIError(f"{name}: unit is required")
        return number, None
    if unit == target_unit:
        return number, target_unit
    if target_unit != "%" and unit.endswith(target_unit):
        prefix = unit[: -len(target_unit)]
        if prefix in PREFIX:
            normalized = float(Decimal(match.group(1)) * Decimal(str(PREFIX[prefix])))
            if not math.isfinite(normalized):
                raise APIError(f"{name}: normalized value overflows")
            return normalized, target_unit
    raise APIError(f"{name}: unit {unit!r} is incompatible with {target_unit}")


def normalize_parameter(p, catalog, source=None, allow_missing_unit=True):
    if not isinstance(p, dict):
        raise APIError("Each parameter must be an object")
    raw_name = _text(p.get("name", p.get("parameter_name")), "parameter name", 250, True)
    value = p.get("value", p.get("parameter_value"))
    if value is None or (isinstance(value, str) and not value.strip()):
        return None, [f"{raw_name}: missing value, not stored"]

    unit = p.get("unit")
    confidence = p.get("confidence", 0.7)
    if confidence is not None:
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            raise APIError("confidence must be a number between 0 and 1")
        if not math.isfinite(confidence) or not 0 <= confidence <= 1:
            raise APIError("confidence must be between 0 and 1")

    provenance = dict(source or {})
    extra = p.get("source")
    if extra is not None:
        if not isinstance(extra, dict):
            raise APIError("source must be an object")
        for key in ("page", "row", "snippet"):
            if key in extra:
                provenance[key] = extra[key]
    if "page" in provenance:
        page = provenance["page"]
        if isinstance(page, bool) or not isinstance(page, int) or page < 1:
            raise APIError("source.page must be a positive integer")
    if "snippet" in provenance:
        snippet = provenance["snippet"]
        if not isinstance(snippet, str) or len(snippet) > 4000:
            raise APIError("source.snippet must be a string of at most 4000 characters")

    definition = catalog.parameter(raw_name)
    warnings = []
    if definition is None:
        # Unknown names are kept as unmapped rows. The reviewer must map them
        # to parameter_def before the row can be approved.
        warnings.append(f"{raw_name}: not mapped to parameter_def")
        return {
            "parameter_id": None,
            "canonical_name": raw_name,
            "raw_name": raw_name,
            "raw_value": str(value).strip(),
            "value_num": None,
            "value_text": str(value).strip(),
            "unit": _unit(unit) or None,
            "confidence": float(confidence) if confidence is not None else None,
            "source": provenance,
        }, warnings

    parameter_id = definition["parameter_id"]
    canonical = definition["canonical_name"]
    data_type = definition["data_type"]
    raw_text = str(value).strip()
    if data_type == "numeric":
        value_num, normalized_unit = numeric(
            value, unit, definition["unit"], canonical, allow_missing_unit
        )
        value_text = None
        if definition["unit"] and not normalized_unit:
            warnings.append(f"{canonical}: missing unit; reviewer must correct it")
        if value_num < 0:
            warnings.append(f"{canonical}: negative value")
        if canonical == "Tolerance" and not 0 <= value_num <= 100:
            warnings.append("Tolerance: outside 0-100%")
    else:
        value_num, normalized_unit, value_text = None, None, raw_text

    return {
        "parameter_id": parameter_id,
        "canonical_name": canonical,
        "raw_name": raw_name,
        "raw_value": raw_text,
        "value_num": value_num,
        "value_text": value_text,
        "unit": normalized_unit,
        "confidence": float(confidence) if confidence is not None else None,
        "source": provenance,
    }, warnings


def _unique(seen, name):
    candidate = name
    index = 2
    while candidate.casefold() in seen:
        candidate = f"{name} ({index})"
        index += 1
    seen.add(candidate.casefold())
    return candidate


def normalize_component(raw, catalog, source=None, allow_missing_unit=True):
    """Normalize one component. One extraction_task represents one component."""
    if not isinstance(raw, dict):
        raise APIError("Component must be an object")

    model = _text(raw.get("model"), "model", 100)
    manufacturer = _text(raw.get("manufacturer"), "manufacturer", 100)
    category_name = _text(raw.get("category"), "category", 100)
    category_def = catalog.category(category_name)
    if category_name and category_def is None:
        warnings_category = [f"category {category_name!r} is not in category dictionary"]
    else:
        warnings_category = []
    package = _text(raw.get("package"), "package", 100)
    if package:
        package = package.upper().replace(" ", "")

    params = raw.get("parameters", [])
    if isinstance(params, dict):
        params = [
            {"name": key, "value": value} if not isinstance(value, dict) else {"name": key, **value}
            for key, value in params.items()
        ]
    if not isinstance(params, list) or len(params) > 100:
        raise APIError("parameters must be a list with at most 100 entries")

    normalized = []
    warnings = list(warnings_category)
    seen = set()
    for p in params:
        if isinstance(p, dict) and str(p.get("name", p.get("parameter_name", ""))).strip().casefold() in {
            "package", "封装", "封装形式"
        }:
            if not package:
                package = _text(p.get("value"), "package", 100)
                if package:
                    package = package.upper().replace(" ", "")
            continue
        item, issues = normalize_parameter(p, catalog, source, allow_missing_unit)
        warnings.extend(issues)
        if item is None:
            continue
        item["raw_name"] = _unique(seen, item["raw_name"])
        normalized.append(item)

    raw_specs = raw.get("specifications", [])
    if raw_specs is not None and not isinstance(raw_specs, list):
        raise APIError("specifications must be a list")
    for spec in (raw_specs or []):
        if not isinstance(spec, dict):
            raise APIError("Each specification must be an object")
        label = _text(spec.get("label"), "specification label", 200, True)
        value_text = _text(spec.get("value_text"), "specification value", 4000, True)
        source_page = spec.get("source", {}).get("page") if isinstance(spec.get("source"), dict) else None
        snippet = spec.get("source", {}).get("snippet") if isinstance(spec.get("source"), dict) else None
        if not isinstance(snippet, str) or not snippet.strip():
            snippet = value_text
        if isinstance(source_page, bool) or not isinstance(source_page, int) or source_page < 1:
            source_page = None
        raw_name = _unique(seen, SPEC_PREFIX + label)
        normalized.append({
            "parameter_id": None,
            "canonical_name": label,
            "raw_name": raw_name,
            "raw_value": value_text,
            "value_num": None,
            "value_text": value_text,
            "unit": None,
            "confidence": None,
            "source": {"page": source_page, "snippet": snippet[:4000]},
        })

    if not normalized:
        raise APIError("Component has no parameters or specifications")
    return {
        "model": model,
        "manufacturer": manufacturer,
        "category": category_name,
        "category_id": category_def["category_id"] if category_def else None,
        "package": package,
        "parameters": normalized,
        "warnings": warnings,
    }
