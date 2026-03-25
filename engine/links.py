from __future__ import annotations

from typing import Any, Dict


def _slugify(value: str | None) -> str:
    text = str(value or "").strip().lower()
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in text)
    while "--" in cleaned:
        cleaned = cleaned.replace("--", "-")
    return cleaned.strip("-")



def build_signal_links(signal: Dict[str, Any]) -> Dict[str, str]:
    project = str(signal.get("project") or signal.get("name") or "").strip()
    pool_id = str(signal.get("pool_id") or "").strip()
    protocol_url = str(signal.get("protocol_url") or "").strip()
    pool_url = str(signal.get("pool_url") or signal.get("llama_pool_url") or "").strip()

    if not protocol_url and project:
        protocol_url = f"https://defillama.com/protocol/{_slugify(project)}"
    if not pool_url and pool_id:
        pool_url = f"https://defillama.com/yields/pool/{pool_id}"

    return {
        "protocol_url": protocol_url,
        "pool_url": pool_url,
        "llama_pool_url": pool_url,
    }
