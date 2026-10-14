"""Request parsing, JSON shaping and the shared error types used by every domain."""

import decimal
import re

from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from flask import jsonify
from flask_login import current_user

from backend.core.web import logger


def _parse_chain_quantity(value, field_name):
    try:
        quantity = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{field_name} must be a valid number')
    if not quantity.is_finite() or quantity <= 0:
        raise ValueError(f'{field_name} must be greater than zero')
    if quantity.as_tuple().exponent < -3:
        raise ValueError(f'{field_name} supports at most three decimal places')
    return quantity


def _chain_actor(data):
    return getattr(current_user, 'username', None) or data.get('recorded_by') or 'system'


def _production_actor(data):
    actor = _chain_actor(data)
    actor_user_id = None
    if getattr(current_user, 'is_authenticated', False):
        try:
            actor_user_id = int(current_user.id)
        except (TypeError, ValueError):
            actor_user_id = None
    return actor, actor_user_id


class ProductionEventPermissionError(Exception):
    """Raised when an event is outside the caller's authorized scope."""
EVENT_UNIT_CODES = {'kg', 'g', 'count', 'days', 'celsius', 'percent', 'ppm', 'none'}


def _event_decimal(value, field_name, *, minimum=None, maximum=None, required=False):
    if value in (None, ''):
        if required:
            raise ValueError(f'{field_name} is required')
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f'{field_name} must be a valid number')
    if not parsed.is_finite():
        raise ValueError(f'{field_name} must be a finite number')
    if minimum is not None and parsed < Decimal(str(minimum)):
        raise ValueError(f'{field_name} must be at least {minimum}')
    if maximum is not None and parsed > Decimal(str(maximum)):
        raise ValueError(f'{field_name} must be at most {maximum}')
    if parsed.as_tuple().exponent < -3:
        raise ValueError(f'{field_name} supports at most three decimal places')
    return parsed


def _event_unit(value, field_name, default=None, allowed=None):
    unit = str(value or default or '').strip().lower()
    allowed_units = set(allowed or EVENT_UNIT_CODES)
    if unit not in allowed_units:
        raise ValueError(f'{field_name} must be one of: {", ".join(sorted(allowed_units))}')
    return unit


def _event_occurred_at(data, date_fields):
    raw = data.get('occurred_at')
    if raw in (None, ''):
        date_value = next((data.get(field) for field in date_fields if data.get(field)), None)
        if not date_value:
            raise ValueError('occurred_at or an event date is required')
        raw = f'{date_value}T{data.get("event_time") or data.get("monitoring_time") or "00:00:00"}'
    try:
        parsed = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('occurred_at must be a valid ISO timestamp or date')
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _parse_positive_integer(value, field_name):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise ValueError(f'{field_name} must be a valid integer')
    if parsed <= 0:
        raise ValueError(f'{field_name} must be greater than zero')
    return parsed


def _to_kg(quantity, unit):
    if quantity is None:
        return None
    value = Decimal(str(quantity))
    return value / Decimal('1000') if str(unit or 'kg').lower() == 'g' else value


def _ratio_percent(numerator, denominator):
    if numerator is None or not denominator:
        return None
    return (Decimal(str(numerator)) / Decimal(str(denominator)) * Decimal('100')).quantize(
        Decimal('0.01')
    )


def _kg_text(value):
    """Human-readable kilograms without trailing zeros (e.g. 2.5 kg)."""
    if value is None:
        return '—'
    text = f"{Decimal(str(value)):.3f}".rstrip('0').rstrip('.')
    return f'{text} kg'


def _jsonable(value):
    """Recursively convert dates to ISO strings for the Batch 360 payload."""
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


class RecordNotFoundError(ValueError):
    """Raised when a requested record does not exist or is not visible."""


class InventoryConflictError(ValueError):
    """Raised when a movement would duplicate an existing ledger fact."""


def _optional_text(data, field, maximum):
    value = str(data.get(field) or '').strip() or None
    if value and len(value) > maximum:
        raise ValueError(f'{field} must be at most {maximum} characters')
    return value


def _alert_response(handler, *args, status=200):
    try:
        return jsonify({'success': True, **handler(*args)}), status
    except ProductionEventPermissionError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 403
    except RecordNotFoundError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 404
    except InventoryConflictError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 409
    except ValueError as exc:
        return jsonify({'success': False, 'message': str(exc)}), 400
    except Exception:
        logger.exception('Error processing alerts request')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500


def camel_to_snake(name):
  pattern = re.compile(r'(?<!^)(?=[A-Z])')
  return pattern.sub('_', name).lower()

def serialize_records(records):
    import datetime as _dt
    result = []
    for row in records:
        serialized = {}
        for k, v in row.items():
            if isinstance(v, _dt.datetime):
                serialized[k] = v.isoformat()
            elif isinstance(v, _dt.date):
                serialized[k] = v.isoformat()
            elif isinstance(v, _dt.time):
                serialized[k] = v.strftime('%H:%M:%S')
            elif isinstance(v, decimal.Decimal):
                serialized[k] = float(v)
            else:
                serialized[k] = v
        result.append(serialized)
    return result


def normalize_keys(data):
    if isinstance(data, dict):
        return {camel_to_snake(k): normalize_keys(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [normalize_keys(i) for i in data]
    else:
        return data

def validate_fields(data, required_fields):
    missing_fields = [field for field in required_fields if field not in data]
    return missing_fields
