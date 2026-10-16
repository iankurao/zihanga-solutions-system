"""Pre-traceability (legacy) leftovers: the records-by-date history lookup
(super admins, every older table), the larval feeding routes that record
canonical production events, and the harvest report email. Figures and
reports come from the production chain (domains/reports.py, dashboard.py);
nothing here writes a record without a farm, site and facility."""

import smtplib

from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import jsonify, request
from flask_login import login_required

from backend.config import ADMIN_EMAIL, EMAIL_HOST, EMAIL_HOST_PASSWORD, EMAIL_HOST_USER, EMAIL_PORT
from backend.core.web import app, db, logger
from backend.core.http import ProductionEventPermissionError, normalize_keys
from backend.core.security import requires
from backend.domains.production import (
    _create_feeding_event,
    _create_harvest_event,
    _create_health_event,
    _create_monitoring_event,
    _harvest_report_rows,
)


# --- Larval feeding forms: record canonical production events ---
@app.route('/api/feeding/environmental-monitoring', methods=['POST'])
@login_required
@requires('production.write')
def create_feeding_environmental_monitoring():
    try:
        result = _create_monitoring_event(normalize_keys(request.get_json() or {}))
        return jsonify({
            'success': True,
            'message': 'Environmental monitoring data saved successfully',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving larval env monitoring data: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/feeding/health-intervention', methods=['POST'])
@login_required
@requires('production.write')
def create_feeding_health_intervention():
    try:
        result = _create_health_event(normalize_keys(request.get_json() or {}))
        return jsonify({
            'success': True,
            'message': 'Health intervention data saved successfully',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving health intervention data: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/feeding/harvest-yield', methods=['POST'])
@login_required
@requires('production.write')
def create_feeding_harvest_yield():
    try:
        result = _create_harvest_event(normalize_keys(request.get_json() or {}))
        return jsonify({
            'success': True,
            'message': 'Harvest recorded',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving harvest/yield data: {e}", exc_info=True)
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/feeding/schedule', methods=['POST'])
@login_required
@requires('production.write')
def create_feeding_schedule():
    try:
        result = _create_feeding_event(normalize_keys(request.get_json() or {}))
        return jsonify({
            'success': True,
            'message': 'Feeding schedule saved successfully',
            **result,
        }), 201
    except ProductionEventPermissionError as e:
        return jsonify({'success': False, 'message': str(e)}), 403
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        logger.error(f"Error saving feeding schedule: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

# --- Records by date (legacy history, super admins) ---
@app.route('/api/records', methods=['GET'])
@login_required
@requires('legacy.read')
def get_records_by_date_and_section():
    target_date_str = request.args.get('date')
    section = request.args.get('section')

    if not target_date_str:
        return jsonify({'success': False, 'message': 'Date parameter is required'}), 400

    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format. Please use YYYY-MM-DD.'}), 400

    # Map sections to tables and their respective date columns
    section_tables = {
        'waste': {
            'Waste Sourcing': ('waste_sourcing', 'collection_date'),
            'Storage Records': ('storage_records', 'storage_date'),
            'Processing Records': ('processing_records', 'processing_date'),
            'Waste Monitoring': ('waste_monitoring', 'monitoring_date'),
        },
        'hatchery': {
            'Batch Information': ('hatchery_batches', 'batch_date'),
            'Feeding Records': ('hatchery_feeding', 'feeding_date'),
            'Environmental Monitoring': ('hatchery_monitoring', 'monitoring_date'),
            'Cleaning & Sanitation': ('hatchery_cleaning', 'cleaning_date'),
            'Problems & Solutions': ('hatchery_problems', 'problem_date'),
        },
        'feeding': {
            'Environmental Monitoring': ('environmental_monitoring_larvaefeeding', 'monitoring_date'),
            'Health & Intervention': ('health_intervention', 'health_date'),
            'Harvest & Yield': ('harvest_yield', 'harvest_date'),
            'Feeding Schedule': ('feeding_schedule', 'feeding_date'),
        },
        'drying': {
            'Batch Information': ('drying_batches', 'drying_date'),
            'Input Records': ('drying_input', 'created_at'),
            'Output Records': ('drying_output', 'created_at'),
            'Quality Control': ('drying_quality_control', 'qc_date'),
            'Review & Approval': ('drying_review_approval', 'review_date'),
        },
        'facility': {
            'Cage Monitoring': ('cage_monitoring', 'monitoring_date'),
            'Facility Maintenance': ('facility_maintenance', 'maintenance_date'),
            'Pupae Transition': ('pupae_transition', 'transition_date'),
            'Egg Collection': ('egg_collection', 'collection_date'),
            'Bait Preparation': ('bait_preparation', 'start_date'),
        },
        # Sales before customer orders existed (read-only history).
        'sales': {
            'Sales': ('sales', 'date'),
            'Deliveries': ('deliveries', 'date'),
            'Customer Feedback': ('customer_feedback', 'date'),
        },
    }

    tables_to_query = {}
    if section == 'all':
        for sec in section_tables:
            tables_to_query.update(section_tables[sec])
    elif section in section_tables:
        tables_to_query = section_tables[section]
    else:
        return jsonify({'success': False, 'message': 'Invalid section specified'}), 400

    all_records = {}
    try:
        for display_name, (table_name, date_col) in tables_to_query.items():
            # The DATE() function is used to ignore the time part of datetime columns
            query = f"SELECT * FROM {table_name} WHERE DATE({date_col}) = %s"
            records = db.fetch_all(query, (target_date,))
            if records:
                # Convert datetime and timedelta objects to strings for JSON serialization
                for record in records:
                    for key, value in record.items():
                        if isinstance(value, (datetime, timedelta)):
                            record[key] = str(value)
                all_records[display_name] = records
        
        return jsonify({'success': True, 'records': all_records})

    except Exception as e:
        logger.error(f"Error fetching records for date {target_date_str} and section {section}: {e}")
        return jsonify({'success': False, 'message': 'An error occurred while fetching records.'}), 500

# --- Harvest report email ---
def send_email(subject, body, to_emails):
    """Send one plain-text email; True when the server accepted it."""
    msg = MIMEMultipart()
    msg['From'] = EMAIL_HOST_USER
    msg['To'] = ', '.join(to_emails) if isinstance(to_emails, list) else to_emails
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    try:
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
        server.sendmail(EMAIL_HOST_USER, to_emails, msg.as_string())
        server.quit()
        logger.info('Harvest report emailed')
        return True
    except Exception as e:
        logger.error('Failed to send email: %s', type(e).__name__)
        return False

@app.route('/api/send-harvest-report', methods=['POST'])
@login_required
@requires('legacy.read')
def send_harvest_report():
    """Email the harvest list (recorded harvests and older harvest-yield rows)
    to ADMIN_EMAIL."""
    try:
        rows = sorted(_harvest_report_rows(), key=lambda r: str(r.get('harvest_date') or ''), reverse=True)
        today = datetime.now().date()
        if not rows:
            summary = "No harvests recorded."
        else:
            lines = [f"Harvest Report ({today}):", ""]
            for row in rows:
                if row.get('wet_weight') is not None:
                    quantity = f"{row['wet_weight']} {row.get('unit') or 'kg'} wet"
                else:
                    quantity = f"{row.get('larvae_collected') or ''} kg"
                lines.append(
                    f"{row.get('harvest_date', '')}  {row.get('business_id') or ''}  "
                    f"batch {row.get('tray_batch_id') or '-'}  {quantity}  "
                    f"{row.get('instar_stage') or ''}".rstrip()
                )
            summary = "\n".join(lines) + "\n"
        if not (EMAIL_HOST_USER and EMAIL_HOST_PASSWORD and ADMIN_EMAIL):
            return jsonify({'success': False,
                            'message': 'Email is not set up (EMAIL_HOST_USER, EMAIL_HOST_PASSWORD, ADMIN_EMAIL).'}), 503
        if not send_email(f"Harvest Report ({today})", summary, ADMIN_EMAIL):
            return jsonify({'success': False, 'message': 'The email could not be sent; see the server log.'}), 502
        return jsonify({'success': True, 'message': 'Harvest report sent to admin.'})
    except Exception:
        logger.exception('Sending the harvest report failed')
        return jsonify({'success': False, 'error': 'An internal error occurred.'}), 500
