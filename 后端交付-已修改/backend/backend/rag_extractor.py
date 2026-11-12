"""Adapter for the 最强RAG hybrid retrieval + Prompt v7 extraction method.

The RAG project is kept as an external sibling directory (default ../最强RAG)
because it contains its own config.yaml/.env and embedding/LLM stack.  This
module builds a document corpus from the uploaded PDF or fetched URL, then
runs the same BM25 + embedding + RRF + LLM-rerank + Prompt v7 pipeline for
each parameter definition in our 11-table dictionary.
"""
import math
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

from .common import APIError
from .normalization import numeric


class RAGUnavailable(Exception):
    """Raised when the RAG project or its LLM/embedding backend is unavailable."""


_RAG = None


def _rag_home():
    configured = os.getenv("RAG_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "最强RAG"


def _load_rag():
    global _RAG
    if _RAG is not None:
        return _RAG
    home = _rag_home()
    if not (home / "chips_extractor" / "llm" / "rag_baseline.py").exists():
        raise RAGUnavailable(f"最强RAG directory not found: {home}")
    if str(home) not in sys.path:
        sys.path.insert(0, str(home))
    try:
        import chips_extractor.llm.rag_baseline as rb
        import chips_extractor.llm.Prompt_v7 as prompt
        from chips_extractor.llm.client import LLMClient
        from chips_extractor.llm.config import LLMConfig
        from chips_extractor.llm.extract_parameters import parse_json_loose
    except Exception as exc:  # missing openai/numpy, broken install, etc.
        raise RAGUnavailable(f"cannot import 最强RAG: {exc}") from exc
    _RAG = {
        "home": home,
        "rb": rb,
        "prompt": prompt,
        "LLMClient": LLMClient,
        "LLMConfig": LLMConfig,
        "parse_json_loose": parse_json_loose,
    }
    return _RAG


def _first_number(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if math.isfinite(number) else None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value).replace(",", ""))
    if not match:
        return None
    number = float(match.group(0))
    return number if math.isfinite(number) else None


def _pdf_pages(path, max_pages, max_chars):
    import pymupdf

    pages = []
    total = 0
    with pymupdf.open(path) as doc:
        if doc.needs_pass:
            raise APIError("PDF requires a password")
        for index, page in enumerate(doc):
            if index >= max_pages:
                break
            text = page.get_text("text") or ""
            if not text.strip():
                continue
            total += len(text)
            if total > max_chars:
                text = text[: max(0, max_chars - (total - len(text)))]
            pages.append((index + 1, text))
            if total > max_chars:
                break
    if not pages:
        raise RAGUnavailable("PDF has no text layer; OCR is required")
    return pages


def _url_pages(url, allowed_hosts):
    from .sources import fetch_web

    text, final = fetch_web(url, allowed_hosts)
    if not text.strip():
        raise RAGUnavailable("URL page has no usable text")
    return [(1, text)], final


def _pdf_identity(path, filename):
    model = Path(filename or path).stem[:100] or "Unknown"
    manufacturer = "Unverified manufacturer"
    category = None
    try:
        from .pdf_specs import extract_pdf

        raw = extract_pdf(path, filename)
        model = (raw.get("model") or model)[:100]
        manufacturer = raw.get("manufacturer") or manufacturer
        category = raw.get("category")
    except Exception:
        pass
    return {"model": model, "manufacturer": manufacturer, "category": category, "package": None}


def _url_identity(final_url):
    parsed = urlparse(final_url)
    model = Path(parsed.path).stem or parsed.hostname or "Unknown"
    return {
        "model": model[:100],
        "manufacturer": "Unverified manufacturer",
        "category": None,
        "package": None,
    }


def _build_index(pages, rb, llm_config):
    """Build the same parent/child corpus used by 最强RAG, from page text."""
    parents = []
    for page_no, text in pages:
        text = re.sub(r"\n{3,}", "\n\n", text or "").strip()
        if not text:
            continue
        generated = rb._make_parents_for_text(text, f"p{page_no}", f"Page {page_no}")
        for parent in generated:
            parent["page_start"] = page_no
            parent["page_end"] = page_no
            parents.append(parent)
    if not parents:
        raise RAGUnavailable("No usable document text for RAG")
    for index, parent in enumerate(parents):
        parent["_pid"] = index
    children = []
    for parent in parents:
        children.extend(rb._split_to_children(parent))
    if not children:
        raise RAGUnavailable("No RAG chunks could be built")

    vecs = rb.embed_texts([child["text"] for child in children], verbose=False)
    bm25 = rb.BM25([child["text"] for child in children])
    return {"parents": parents, "children": children, "vecs": vecs, "bm25": bm25}


def _retrieve(query, index, llm, rb):
    queries, _ = rb.expand_queries(query, llm, verbose=False)
    candidates = rb.multi_query_retrieve(
        queries, index["vecs"], index["bm25"], top_n=25
    )
    parents = [index["parents"][i] for i in candidates]
    selected, _ = rb.llm_rerank(query, parents, llm, k=5, verbose=False)
    return selected


def _generate(query, selected, identity, definition, prompt_module, parse_json_loose, llm):
    body_parts = []
    table_parts = []
    titles = []
    pages = []
    for item in selected:
        title = str(item.get("title") or "")
        titles.append(title)
        if item.get("type") == "table":
            table_parts.append(f"### 表: {item.get('caption') or title}\n{item.get('text', '')}")
        else:
            body_parts.append(f"## [{title}]\n{item.get('text', '')}")
        if isinstance(item.get("page_start"), int):
            pages.append(item["page_start"])
        if isinstance(item.get("page_end"), int):
            pages.append(item["page_end"])
    shape = "text" if definition["data_type"] != "numeric" else "scalar"
    user = prompt_module.render_user_prompt(
        part=identity["model"],
        name=definition["canonical_name"],
        shape=shape,
        unit=definition.get("unit") or "",
        convention="",
        title=" / ".join(dict.fromkeys(t for t in titles if t))[:200],
        page_range=f"{min(pages)}-{max(pages)}" if pages else "",
        body="\n\n".join(body_parts)[:40000] or "(本节无正文)",
        tables="\n\n".join(table_parts)[:80000] or "(本节无表格)",
    )
    response = llm.chat(
        [
            {"role": "system", "content": prompt_module.SYSTEM_PROMPT},
            {"role": "user", "content": user},
        ]
    )
    if not response.success:
        raise RAGUnavailable(response.error_msg or "RAG LLM generation failed")
    try:
        result = parse_json_loose(response.text)
    except Exception as exc:
        raise RAGUnavailable(f"RAG returned invalid JSON: {exc}") from exc
    if not isinstance(result, dict):
        raise RAGUnavailable("RAG returned a non-object result")
    return result, selected


def _to_parameter(result, definition, selected):
    if result.get("found") is False:
        return None
    raw = str(result.get("raw") or "").strip()
    value = result.get("value")
    minimum = result.get("min")
    maximum = result.get("max")
    if value is None and minimum is None and maximum is None:
        return None
    if raw:
        raw_value = raw
    elif minimum is not None and maximum is not None:
        raw_value = f"{minimum}-{maximum} {definition.get('unit') or ''}".strip()
    elif value is not None:
        raw_value = f"{value} {definition.get('unit') or ''}".strip()
    else:
        return None
    if not raw_value:
        return None
    number = None
    value_text = None
    result_unit = result.get("unit") or None
    if definition["data_type"] == "numeric":
        if value is not None:
            try:
                number, _ = numeric(
                    value,
                    result_unit,
                    definition.get("unit"),
                    definition["canonical_name"],
                    True,
                )
            except APIError:
                number = None
        if number is None and value is None and (minimum is not None or maximum is not None):
            value_text = raw_value[:4000]
    else:
        value_text = str(value if value is not None else raw_value)[:4000]
        number = None
    page = None
    for item in selected:
        if isinstance(item.get("page_start"), int):
            page = item["page_start"]
            break
    return {
        "parameter_id": definition["parameter_id"],
        "canonical_name": definition["canonical_name"],
        "raw_name": definition["canonical_name"],
        "raw_value": raw_value[:4000],
        "value_num": number,
        "value_text": value_text,
        "unit": definition.get("unit") or (result.get("unit") or None),
        "confidence": 0.7,
        "source": {"page": page, "snippet": raw[:4000] if raw else raw_value[:4000]},
    }


def extract_with_rag(task, config, catalog):
    """Run 最强RAG for a PDF/URL task and return one normalized component."""
    rag = _load_rag()
    rb = rag["rb"]
    prompt_module = rag["prompt"]
    llm_config = rag["LLMConfig"]()
    llm_config.temperature = 0.0
    llm_config.max_tokens = int(os.getenv("RAG_MAX_TOKENS", "4096"))
    llm = rag["LLMClient"](llm_config)

    source_type = task["source_type"]
    allowed_hosts = config.get("URL_ALLOWED_HOSTS", [])
    if source_type == "pdf":
        pages = _pdf_pages(
            task["source_location"],
            int(config.get("RAG_MAX_PAGES", 100)),
            int(config.get("RAG_MAX_CHARS", 120000)),
        )
        identity = _pdf_identity(task["source_location"], Path(task["source_location"]).name)
    elif source_type == "url":
        pages, final_url = _url_pages(task["source_location"], allowed_hosts)
        identity = _url_identity(final_url)
        pages = [(1, pages[0][1][: int(config.get("RAG_MAX_CHARS", 120000))])]
    else:
        raise RAGUnavailable("RAG extraction only supports PDF and URL")

    index = _build_index(pages, rb, llm_config)
    parameters = list(catalog.parameters)
    limit = int(config.get("RAG_PARAMETER_LIMIT", 0))
    if limit > 0:
        parameters = parameters[:limit]

    rows = []
    warnings = []
    for definition in parameters:
        query = f"{identity['model']}: {definition['canonical_name']} {definition['display_name']} datasheet"
        try:
            selected = _retrieve(query, index, llm, rb)
            result, selected = _generate(
                query, selected, identity, definition, prompt_module,
                rag["parse_json_loose"], llm,
            )
            row = _to_parameter(result, definition, selected)
            if row is None:
                retry_query = query + " specification table absolute maximum ratings"
                selected = _retrieve(retry_query, index, llm, rb)
                result, selected = _generate(
                    retry_query, selected, identity, definition, prompt_module,
                    rag["parse_json_loose"], llm,
                )
                row = _to_parameter(result, definition, selected)
            if row is not None:
                rows.append(row)
            else:
                warnings.append(f"{definition['canonical_name']}: RAG found no grounded value")
        except RAGUnavailable:
            raise
        except Exception as exc:
            warnings.append(f"{definition['canonical_name']}: RAG error ({type(exc).__name__})")

    if not rows:
        raise RAGUnavailable("RAG found no parameters in this document")
    return {
        "component": {
            **identity,
            "parameters": rows,
            "warnings": warnings,
        },
        "method": "rag_strong",
        "warnings": warnings,
    }
