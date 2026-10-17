"""Social media post generation for peat fire alerts (simulated, no actual posting)."""

from __future__ import annotations

from typing import Any

MAX_TWITTER_CHARS = 280
MAX_FACEBOOK_CHARS = 63206


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{digits}f}"


def _coord(lat: float, lon: float) -> str:
    return f"{_fmt_num(lat)}, {_fmt_num(lon)}"


def twitter_post(dispatch: dict[str, Any]) -> dict[str, str]:
    """Generate Twitter/X post (≤280 chars)."""
    cell_id = dispatch["cell_id"]
    risk = dispatch.get("rationale", "").split(";")[0]  # First part of rationale
    target = _coord(dispatch["target"]["lat"], dispatch["target"]["lon"])
    
    post_id = (
        f"🔥 SIMULASI: Peringatan kebakaran gambut di {target} (sel {cell_id}). "
        f"{risk}. "
        f"Koordinasi patroli segera. #PeatFireAlert #Kalimantan"
    )
    
    post_en = (
        f"🔥 SIMULATION: Peat fire warning at {target} (cell {cell_id}). "
        f"{risk}. "
        f"Coordinate patrol immediately. #PeatFireAlert #Kalimantan"
    )
    
    # Truncate if too long
    if len(post_id) > MAX_TWITTER_CHARS:
        post_id = post_id[:MAX_TWITTER_CHARS - 3] + "..."
    if len(post_en) > MAX_TWITTER_CHARS:
        post_en = post_en[:MAX_TWITTER_CHARS - 3] + "..."
    
    return {"id": post_id, "en": post_en}


def facebook_post(dispatch: dict[str, Any]) -> dict[str, str]:
    """Generate Facebook post (more detailed, longer)."""
    cell_id = dispatch["cell_id"]
    action = dispatch["action"]
    priority = dispatch["priority"]
    target = _coord(dispatch["target"]["lat"], dispatch["target"]["lon"])
    rationale = dispatch.get("rationale", "")
    
    post_id = (
        f"🔔 SIMULASI - PERINGATAN KEBAKARAN GAMBUT\n\n"
        f"📍 Lokasi: {target} (Sel: {cell_id})\n"
        f"⚠️ Status: {action} (Prioritas: {priority})\n"
        f"📊 {rationale}\n\n"
        f"Tim Manggala Agni, BPBD, dan BRGM diminta siaga. "
        f"Masyarakat di sekitar diminta waspada dan tidak membakar lahan.\n\n"
        f"#PeatFireAlert #Kalimantan #KebakaranHutan #Bencana"
    )
    
    post_en = (
        f"🔔 SIMULATION - PEAT FIRE ALERT\n\n"
        f"📍 Location: {target} (Cell: {cell_id})\n"
        f"⚠️ Status: {action} (Priority: {priority})\n"
        f"📊 {rationale}\n\n"
        f"Manggala Agni, BPBD, and BRGM teams are requested to stay alert. "
        f"Nearby communities are advised to remain alert and avoid land burning.\n\n"
        f"#PeatFireAlert #Kalimantan #ForestFire #Disaster"
    )
    
    return {"id": post_id, "en": post_en}


def generate_social_media_posts(dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate social media posts for all dispatches."""
    posts = {
        "twitter": [twitter_post(d) for d in dispatches],
        "facebook": [facebook_post(d) for d in dispatches],
        "generated_at": dispatches[0]["ts"] if dispatches else None,
        "total_dispatches": len(dispatches),
    }
    return posts
