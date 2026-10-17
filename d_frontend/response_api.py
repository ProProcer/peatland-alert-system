"""Same-origin interface adapter for Role C's simulated response engine."""
import json
from pathlib import Path
import threading
from c_agent.agent import dispatch_live
from c_agent import llm
from c_agent.email import generate_batch_email_summary, generate_email_notification
from c_agent.social_media import generate_social_media_posts
from c_agent.summary import generate_summary, generate_incident_timeline
from c_agent.water import resolve_water_catalogue_path, _WATER_INDEX_AVAILABLE

ROOT = Path(__file__).resolve().parents[1]
LOCK = threading.Lock()
STATE = ROOT / 'c_agent/state/frontend_incidents.json'
LOG = ROOT / 'c_agent/logs/frontend_notifications.log'


def response_bundle(directory, *, state_path=None, log_path=None, water_sources=None):
    path = directory / 'dispatch.json'
    from contracts.validate import validate_file
    records = validate_file('dispatch', path) if path.is_file() else []
    water = resolve_water_catalogue_path(water_sources, directory)
    state_path = Path(state_path) if state_path is not None else STATE
    log_path = Path(log_path) if log_path is not None else LOG
    return {'dispatches': records, 'available': path.is_file(), 'summary': generate_summary(records),
            'timeline': generate_incident_timeline(records), 'social': generate_social_media_posts(records),
            'email': generate_batch_email_summary(records),
            'individual_emails': [generate_email_notification(row) for row in records],
            'engine': {'simulation': True, 'water_available': water is not None,
                       'water_catalogue': water.name if water else None,
                       'spatial_water': _WATER_INDEX_AVAILABLE,
                       'llm_available': llm._pick_provider(None) is not None,
                       'state_persisted': state_path.is_file()},
            'log': log_path.read_text(encoding='utf-8').splitlines()[-100:] if log_path.exists() else []}


def run_response(directory, options):
    if not isinstance(options, dict) or set(options) - {'cooldown_hours', 'max_water_km', 'use_llm'}:
        raise ValueError('Unsupported response options')
    cooldown = options.get('cooldown_hours', 6)
    water = options.get('max_water_km', 15)
    if isinstance(cooldown, bool) or not isinstance(cooldown, (float, int)) or not 0 <= cooldown <= 168:
        raise ValueError('Cooldown must be between 0 and 168 hours')
    if isinstance(water, bool) or not isinstance(water, (float, int)) or not 0 <= water <= 100:
        raise ValueError('Water cutoff must be between 0 and 100 km')
    if not isinstance(options.get('use_llm', False), bool):
        raise ValueError('LLM setting must be a boolean')
    if not LOCK.acquire(blocking=False):
        raise ValueError('A response run is already in progress')
    try:
        dispatch_live(directory, directory / 'dispatch.json', state_path=STATE, log_path=LOG,
                      cooldown_hours=cooldown, max_water_km=water or None,
                      use_llm=options.get('use_llm', False))
        return response_bundle(directory)
    finally:
        LOCK.release()
