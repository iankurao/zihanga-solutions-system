"""Records by date (super admins: every record of one day, by area) and the
harvest report email. Figures and reports come from the production chain
(domains/reports.py, dashboard.py)."""

import smtplib

from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import jsonify, request
from flask_login import login_required

from backend.config import ADMIN_EMAIL, EMAIL_HOST, EMAIL_HOST_PASSWORD, EMAIL_HOST_USER, EMAIL_PORT
from backend.core.web import app, db, logger
from backend.core.security import requires
from backend.domains.production import _harvest_report_rows


# --- Records by date (super admins) ---
@app.route('/api/records', methods=['GET'])
@login_required
@requires('records.read')
def get_records_by_date_and_section():
    target_date_str = request.args.get('date')
    section = request.args.get('section')

    if not target_date_str:
        return jsonify({'success': False, 'message': 'Date parameter is required'}), 400

    try:
        target_date = datetime.strptime(target_date_str, '%Y-%m-%d').date()
    except ValueError:
        return jsonify({'success': False, 'message': 'Invalid date format. Please use YYYY-MM-DD.'}), 400

    # Section -> {display name: (table or subquery, date column)}.
    section_tables = {
        'waste': {
            'Waste Sourcing': ('waste_sourcing', 'collection_date'),
            'Substrate Preparation': ('substrate_preparation', 'prep_date'),
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
            'Production Events': (
                '(SELECT pe.event_code, pb.business_id AS production_batch, pe.event_type, '
                'pe.occurred_at, pe.quantity, pe.unit, pe.actor, pe.status, pe.notes '
                'FROM production_events AS pe '
                'JOIN production_batches AS pb ON pb.id = pe.production_batch_id) AS events',
                'occurred_at'),
        },
        'drying': {
            'Drying Batches': ('drying_batches', 'drying_date'),
            'Drying Inputs': ('drying_inputs', 'added_at'),
            'Drying Outputs': ('drying_outputs', 'output_date'),
            'Quality Checks': ('quality_checks', 'checked_at'),
            'Quality Decisions': ('quality_approvals', 'decided_at'),
            'Product Lots': ('product_lots', 'production_date'),
        },
        'facility': {
            'Cage Monitoring': ('cage_monitoring', 'monitoring_date'),
            'Facility Maintenance': ('facility_maintenance', 'maintenance_date'),
            'Pupae Transition': ('pupae_transition', 'transition_date'),
            'Egg Collection': ('egg_collection', 'collection_date'),
            'Bait Preparation': ('bait_preparation', 'start_date'),
        },
        'sales': {
            'Customer Orders': ('customer_orders', 'order_date'),
            'Deliveries': ('customer_deliveries', 'dispatched_at'),
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
@requires('records.read')
def send_harvest_report():
    """Email the list of recorded harvests to ADMIN_EMAIL."""
    try:
        rows = sorted(_harvest_report_rows(), key=lambda r: str(r.get('harvest_date') or ''), reverse=True)
        today = datetime.now().date()
        if not rows:
            summary = "No harvests recorded."
        else:
            lines = [f"Harvest Report ({today}):", ""]
            for row in rows:
                quantity = f"{row['wet_weight']} {row.get('unit') or 'kg'} wet"
                lines.append(
                    f"{row.get('harvest_date', '')}  {row.get('business_id') or ''}  "
                    f"batch {row.get('production_batch') or '-'}  {quantity}  "
                    f"{row.get('harvest_stage') or ''}".rstrip()
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
