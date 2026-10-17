"""Email notification templates for peat fire alerts (simulated, no actual sending)."""

from __future__ import annotations

from typing import Any


def _fmt_num(value: Any, digits: int = 2) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, int):
        return str(value)
    return f"{float(value):.{digits}f}"


def _coord(lat: float, lon: float) -> str:
    return f"{_fmt_num(lat)}, {_fmt_num(lon)}"


def email_subject(dispatch: dict[str, Any]) -> dict[str, str]:
    """Generate email subject line."""
    cell_id = dispatch["cell_id"]
    action = dispatch["action"]
    
    subject_id = f"[SIMULASI] {action} - Peringatan Kebakaran Gambut Sel {cell_id}"
    subject_en = f"[SIMULATION] {action} - Peat Fire Warning Cell {cell_id}"
    
    return {"id": subject_id, "en": subject_en}


def email_body(dispatch: dict[str, Any]) -> dict[str, str]:
    """Generate detailed email body."""
    cell_id = dispatch["cell_id"]
    action = dispatch["action"]
    priority = dispatch["priority"]
    target = _coord(dispatch["target"]["lat"], dispatch["target"]["lon"])
    rationale = dispatch.get("rationale", "")
    water = dispatch.get("water_source")
    
    water_text = ""
    if water:
        water_text = (
            f"Sumber air terdekat: {water['kind']} di {_coord(water['lat'], water['lon'])} "
            f"({water['distance_km']} km)\n"
        )
    else:
        water_text = "Sumber air: Tidak tersedia\n"
    
    body_id = (
        f"PERINGATAN KEBAKARAN GAMBUT - SIMULASI\n\n"
        f"ID Dispatch: {dispatch['dispatch_id']}\n"
        f"Waktu: {dispatch['ts']}\n"
        f"Sel: {cell_id}\n"
        f"Lokasi: {target}\n"
        f"Aksi: {action}\n"
        f"Prioritas: {priority}\n\n"
        f"DETAIL RISIKO:\n"
        f"{rationale}\n\n"
        f"{water_text}\n"
        f"PESAN UNTUK AUDIENS:\n"
    )
    
    for audience, messages in dispatch["messages"].items():
        body_id += f"\n{audience.upper()}:\n"
        body_id += f"  Indonesia: {messages['id']}\n"
        body_id += f"  English: {messages['en']}\n"
    
    body_id += "\n---\n"
    body_id += "Ini adalah simulasi sistem peringatan dini kebakaran gambut. "
    body_id += "Tidak ada notifikasi nyata yang dikirim.\n"
    
    body_en = (
        f"PEAT FIRE WARNING - SIMULATION\n\n"
        f"Dispatch ID: {dispatch['dispatch_id']}\n"
        f"Time: {dispatch['ts']}\n"
        f"Cell: {cell_id}\n"
        f"Location: {target}\n"
        f"Action: {action}\n"
        f"Priority: {priority}\n\n"
        f"RISK DETAILS:\n"
        f"{rationale}\n\n"
        f"{water_text}\n"
        f"MESSAGES FOR AUDIENCES:\n"
    )
    
    for audience, messages in dispatch["messages"].items():
        body_en += f"\n{audience.upper()}:\n"
        body_en += f"  Indonesian: {messages['id']}\n"
        body_en += f"  English: {messages['en']}\n"
    
    body_en += "\n---\n"
    body_en += "This is a simulation of the peat fire early warning system. "
    body_en += "No actual notifications are sent.\n"
    
    return {"id": body_id, "en": body_en}


def generate_email_notification(dispatch: dict[str, Any]) -> dict[str, Any]:
    """Generate complete email notification."""
    return {
        "subject": email_subject(dispatch),
        "body": email_body(dispatch),
        "dispatch_id": dispatch["dispatch_id"],
        "generated_at": dispatch["ts"],
    }


def generate_batch_email_summary(dispatches: list[dict[str, Any]]) -> dict[str, Any]:
    """Generate summary email for multiple dispatches."""
    if not dispatches:
        return {"subject": {"id": "[SIMULASI] Ringkasan - Tidak ada dispatch", "en": "[SIMULATION] Summary - No dispatches"},
                "body": {"id": "Tidak ada peringatan baru.", "en": "No new alerts."}, "count": 0}
    
    count = len(dispatches)
    critical = sum(1 for d in dispatches if d["action"] == "DISPATCH")
    high = sum(1 for d in dispatches if d["action"] in ["SMS_WARN", "REWET"])
    
    subject_id = f"[SIMULASI] Ringkasan Peringatan - {count} Dispatch ({critical} Kritis, {high} Tinggi)"
    subject_en = f"[SIMULATION] Alert Summary - {count} Dispatches ({critical} Critical, {high} High)"
    
    body_id = f"RINGKASAN PERINGATAN GAMBUT - SIMULASI\n\n"
    body_id += f"Total Dispatch: {count}\n"
    body_id += f"Kritis: {critical}\n"
    body_id += f"Tinggi: {high}\n"
    body_id += f"Moderate/Low: {count - critical - high}\n\n"
    body_id += "DETAIL DISPATCH:\n"
    
    for d in dispatches:
        body_id += f"\n- {d['dispatch_id']}: {d['action']} di sel {d['cell_id']}\n"
    
    body_en = f"PEAT FIRE ALERT SUMMARY - SIMULATION\n\n"
    body_en += f"Total Dispatches: {count}\n"
    body_en += f"Critical: {critical}\n"
    body_en += f"High: {high}\n"
    body_en += f"Moderate/Low: {count - critical - high}\n\n"
    body_en += "DISPATCH DETAILS:\n"
    
    for d in dispatches:
        body_en += f"\n- {d['dispatch_id']}: {d['action']} at cell {d['cell_id']}\n"
    
    return {
        "subject": {"id": subject_id, "en": subject_en},
        "body": {"id": body_id, "en": body_en},
        "count": count,
        "critical_count": critical,
        "high_count": high,
        "generated_at": dispatches[0]["ts"] if dispatches else None,
    }
