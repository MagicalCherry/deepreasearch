"""Stable Milvus collection identifiers; display names may contain Unicode."""
import hashlib
import re


def normalize_collection_name(name: str) -> str:
    if not isinstance(name, str) or not name.strip():
        raise ValueError("集合名称不能为空")
    # Documents also store this identifier in a VARCHAR(128) kb_id field.
    if len(name) <= 128 and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
        return name
    slug = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_")[:48]
    digest = hashlib.sha256(name.encode("utf-8")).hexdigest()
    return f"kb_{slug}_{digest}" if slug else f"kb_{digest}"


def knowledge_collection_name(kb_name: str) -> str:
    # Preserve existing valid English names and use the same mapping everywhere.
    return normalize_collection_name(f"kb_{kb_name}".lower().replace(" ", "_"))
