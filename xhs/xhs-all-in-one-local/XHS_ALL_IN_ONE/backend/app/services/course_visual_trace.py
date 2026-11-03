"""Private production provenance, separate from user-facing workflow steps.

This records identifiers and digests, never prompts, source excerpts, credentials,
or copies of course files.  The caller persists the enclosing workflow normally.
Recording an operation does not approve, render, export or publish anything.
"""
from collections.abc import Mapping
from hashlib import sha256
import json
from urllib.parse import urlsplit

from backend.app.core.time import shanghai_now


def _digest(value):
    if value is None:
        return None
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False,
                         separators=(',', ':'), default=str).encode('utf-8')
    return sha256(payload).hexdigest()


def _model(value):
    """Whitelist model metadata; URL userinfo and token-bearing queries are private."""
    if not isinstance(value, Mapping):
        return None
    result = {key: str(value[key])[:240] for key in ('name', 'model_name')
              if value.get(key) is not None}
    destination = value.get('destination')
    if isinstance(destination, str):
        try:
            parsed = urlsplit(destination)
            if parsed.scheme in {'http', 'https'} and parsed.hostname:
                host = parsed.hostname
                if ':' in host:
                    host = f'[{host}]'
                port = f':{parsed.port}' if parsed.port is not None else ''
                result['destination'] = f'{parsed.scheme}://{host}{port}'
        except ValueError:
            pass
    return result or None


def record(data, step, tool, model=None, inputs=None, outputs=None,
           status='completed', scope=None):
    """Append a small provenance entry to ``data.production_trace`` in place.

    ``inputs`` and ``outputs`` are hashed only.  Model metadata is strictly
    whitelisted, and the selected PDF is identified by revision and SHA-256.
    Existing entries are retained to keep failed and superseded work traceable.
    """
    rules = data.get('rules') or {}
    source = data.get('source') or {}
    entry = {
        'schema_version': 1,
        'workflow_contract': '2026.10.30.simple.1',
        'at': shanghai_now().isoformat(),
        'step': str(step),
        'tool': str(tool),
        'status': str(status),
        'rules_version': rules.get('version'),
        'skills': [{key: item[key] for key in ('skill', 'sha256') if key in item}
                   for item in rules.get('skills', []) if isinstance(item, Mapping)],
        'model': _model(model),
        'source': {key: source[key] for key in ('revision_id', 'sha256') if key in source},
        'selected_source_ids': list(data.get('selected_source_ids') or []),
        'inputs_digest': _digest(inputs),
        'outputs_digest': _digest(outputs),
        'scope': str(scope) if scope is not None else None,
    }
    data.setdefault('production_trace', []).append(entry)
    return entry
