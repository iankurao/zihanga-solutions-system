"""Pre-traceability (legacy) history: statistics, analytics and records lookups
(super admins), the larval feeding routes that record canonical production
events, and the harvest report email. Nothing here writes a record without a
farm, site and facility any more."""

import smtplib

from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import jsonify, request
from flask_login import login_required

from backend.config import ADMIN_EMAIL, EMAIL_HOST, EMAIL_HOST_PASSWORD, EMAIL_HOST_USER, EMAIL_PORT
from backend.core.web import app, db, logger
from backend.core.http import ProductionEventPermissionError, normalize_keys, serialize_records
from backend.core.security import requires
from backend.domains.production import (
    _create_feeding_event,
    _create_harvest_event,
    _create_health_event,
    _create_monitoring_event,
    _harvest_report_rows,
)


# --- Statistics & Reporting ---
@app.route('/api/statistics/waste-processing', methods=['GET'])
@login_required
@requires('legacy.read')
def get_waste_processing_stats():
    try:
        query = """
            SELECT 
                DATE(processing_date) as date,
                SUM(waste_processed) as total_processed
            FROM processing_records
            GROUP BY DATE(processing_date)
            ORDER BY date DESC
            LIMIT 30;
        """
        stats = db.fetch_all(query)
        # Convert decimal and date objects to string/float for JSON serialization
        for row in stats:
            for key, value in row.items():
                if isinstance(value, (datetime,)):
                    row[key] = value.isoformat()
                elif isinstance(value, float):
                    row[key] = float(value)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error fetching waste processing stats: {e}")
        return jsonify([]), 500


@app.route('/api/statistics/environmental', methods=['GET'])
@login_required
@requires('legacy.read')
def get_environmental_stats():
    try:
        query = """
            SELECT 
                DATE(monitoring_date) as date,
                AVG(temperature) as avg_temp,
                MODE() WITHIN GROUP (ORDER BY water_consistency) as common_water_consistency
            FROM waste_monitoring
            GROUP BY DATE(monitoring_date)
            ORDER BY date DESC
            LIMIT 30;
        """
        stats = db.fetch_all(query)
        for row in stats:
            for key, value in row.items():
                if isinstance(value, (datetime,)):
                    row[key] = value.isoformat()
                elif isinstance(value, float):
                    row[key] = float(value)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error fetching environmental stats: {e}")
        return jsonify([]), 500

@app.route('/api/statistics/larval-growth', methods=['GET'])
@login_required
@requires('legacy.read')
def get_larval_growth_stats():
    try:
        query = """
            SELECT 
                DATE(feeding_date) as date,
                AVG(larvae_weight) as avg_weight,
                AVG(consumption) as avg_consumption
            FROM feeding_schedule
            GROUP BY DATE(feeding_date)
            ORDER BY date DESC
            LIMIT 30;
        """
        stats = db.fetch_all(query)
        for row in stats:
            for key, value in row.items():
                if isinstance(value, (datetime,)):
                    row[key] = value.isoformat()
                elif isinstance(value, float):
                    row[key] = float(value)
        return jsonify(stats)
    except Exception as e:
        logger.error(f"Error fetching larval growth stats: {e}")
        return jsonify([]), 500

@app.route('/api/statistics/system-efficiency', methods=['GET'])
@login_required
@requires('legacy.read')
def get_system_efficiency():
    try:
        query_waste = """
            SELECT SUM(waste_weight) as total_waste_in
            FROM waste_sourcing;
        """
        total_waste_in = db.fetch_one(query_waste)['total_waste_in'] or 0

        query_larvae = """
            SELECT SUM(larvae_collected) as total_larvae_out
            FROM harvest_yield;
        """
        total_larvae_out = db.fetch_one(query_larvae)['total_larvae_out'] or 0
        
        query_compost = """
            SELECT COUNT(*) as total_processing_records
            FROM processing_records;
        """
        total_processing_records = db.fetch_one(query_compost)['total_processing_records'] or 0

        efficiency = float(total_larvae_out) / float(total_waste_in) if total_waste_in > 0 else 0

        return jsonify({
            'total_waste_in': float(total_waste_in),
            'total_larvae_out': float(total_larvae_out),
            'total_processing_records': int(total_processing_records),
            'overall_efficiency': efficiency
        })
    except Exception as e:
        logger.error(f"Error calculating system efficiency: {e}")
        return jsonify({}), 500

@app.route('/api/statistics/daily-report', methods=['GET'])
@login_required
@requires('legacy.read')
def get_daily_report():
    today = datetime.now().date()
    try:
        # Waste Sourced Today
        waste_sourced_query = "SELECT SUM(waste_weight) as total FROM waste_sourcing WHERE DATE(collection_date) = %s"
        waste_sourced = db.fetch_one(waste_sourced_query, (today,))['total'] or 0

        # Larvae Harvested Today
        larvae_harvested_query = "SELECT SUM(larvae_collected) as total FROM harvest_yield WHERE DATE(harvest_date) = %s"
        larvae_harvested = db.fetch_one(larvae_harvested_query, (today,))['total'] or 0

        # Feed Given Today
        feed_given_query = "SELECT SUM(feed_quantity) as total FROM feeding_schedule WHERE DATE(feeding_date) = %s"
        feed_given = db.fetch_one(feed_given_query, (today,))['total'] or 0

        # Eggs Collected Today
        eggs_collected_query = "SELECT SUM(eggs_collected) as total FROM egg_collection WHERE DATE(collection_date) = %s"
        eggs_collected = db.fetch_one(eggs_collected_query, (today,))['total'] or 0

        return jsonify({
            'waste_sourced_today': float(waste_sourced),
            'larvae_harvested_today': float(larvae_harvested),
            'feed_given_today': float(feed_given),
            'eggs_collected_today': float(eggs_collected)
        })
    except Exception as e:
        logger.error(f"Error fetching daily report: {e}")
        return jsonify({}), 500

@app.route('/api/statistics/harvest-efficiency', methods=['GET'])
@login_required
@requires('legacy.read')
def get_harvest_efficiency():
    try:
        query = """
            WITH input_totals AS (
                SELECT
                    batch_id,
                    SUM(wet_placed_for_drying_kg) AS total_wet_weight
                FROM drying_input
                GROUP BY batch_id
            ),
            output_totals AS (
                SELECT
                    batch_id,
                    MAX(created_at) AS output_date,
                    SUM(dried_produced_kg) AS total_dried_weight
                FROM drying_output
                GROUP BY batch_id
            )
            SELECT
                input_totals.batch_id,
                output_totals.output_date,
                input_totals.total_wet_weight,
                output_totals.total_dried_weight
            FROM input_totals
            JOIN output_totals ON input_totals.batch_id = output_totals.batch_id
            ORDER BY output_totals.output_date ASC;
        """
        results = db.fetch_all(query)

        efficiency_data = []
        target_ratio = 3.0

        for row in results:
            batch_id = row['batch_id']
            drying_date = row['output_date'].strftime('%Y-%m-%d') if row['output_date'] else None
            total_wet = float(row['total_wet_weight']) if row['total_wet_weight'] is not None else 0
            total_dried = float(row['total_dried_weight']) if row['total_dried_weight'] is not None else 0

            if total_dried > 0:
                actual_ratio_val = total_wet / total_dried
                efficiency_status = 'Efficient' if actual_ratio_val <= target_ratio else 'Inefficient'
            else:
                actual_ratio_val = None
                efficiency_status = 'Inefficient'

            efficiency_data.append({
                'batch_id': batch_id,
                'drying_date': drying_date,
                'wet_placed': round(total_wet, 2),
                'dried_produced': round(total_dried, 2),
                'actual_ratio': round(actual_ratio_val, 4) if actual_ratio_val is not None else None,
                'efficiency_status': efficiency_status,
            })

        return jsonify({'success': True, 'data': efficiency_data})
    except Exception as e:
        logger.error(f"Error fetching harvest efficiency: {e}")
        return jsonify({'success': False, 'error': 'Could not fetch harvest efficiency data'}), 500


# --- GET ALL (for potential future table views) ---
@app.route('/api/waste-sourcing/all', methods=['GET'])
@login_required
@requires('legacy.read')
def get_all_waste_sourcing():
    query = "SELECT * FROM waste_sourcing ORDER BY collection_date DESC"
    records = db.fetch_all(query)
    return jsonify({'records': records, 'success': True})

@app.route('/api/drying/input/all', methods=['GET'])
@login_required
@requires('legacy.read')
def get_all_drying_input():
    query = """
        SELECT di.*, db.id AS drying_batch_id_internal,
               db.business_id AS drying_batch_business_id
        FROM drying_input di
        LEFT JOIN drying_batches db ON db.batch_id = di.batch_id
        ORDER BY di.created_at DESC
    """
    records = db.fetch_all(query)
    return jsonify({'records': records, 'success': True})

@app.route('/api/drying/output/all', methods=['GET'])
@login_required
@requires('legacy.read')
def get_all_drying_output():
    query = """
        SELECT dout.*, db.id AS drying_batch_id_internal,
               db.business_id AS drying_batch_business_id
        FROM drying_output dout
        LEFT JOIN drying_batches db ON db.batch_id = dout.batch_id
        ORDER BY dout.created_at DESC
    """
    records = db.fetch_all(query)
    return jsonify({'records': records, 'success': True})

@app.route('/api/drying/qc/all', methods=['GET'])
@login_required
@requires('legacy.read')
def get_all_drying_qc():
    query = "SELECT * FROM drying_quality_control ORDER BY qc_date DESC"
    records = db.fetch_all(query)
    return jsonify({'records': records, 'success': True})

@app.route('/api/drying/remarks/all', methods=['GET'])
@login_required
@requires('legacy.read')
def get_all_drying_remarks():
    return jsonify({'records': [], 'success': True})

@app.route('/api/drying/review/all', methods=['GET'])
@login_required
@requires('legacy.read')
def get_all_drying_review():
    query = "SELECT * FROM drying_review_approval ORDER BY review_date DESC"
    records = db.fetch_all(query)
    return jsonify({'records': records, 'success': True})

@app.route('/api/feeding/harvest/all', methods=['GET'])
@login_required
@requires('legacy.read')
def get_all_feeding_harvest():
    records = _harvest_report_rows()
    return jsonify({'records': records, 'success': True})

# --- Analytics GET Endpoints ---
@app.route('/api/analytics/waste-sourcing', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_waste_sourcing():
    records = db.fetch_all("SELECT * FROM waste_sourcing ORDER BY collection_date DESC")
    return jsonify({'records': serialize_records(records), 'success': True})

@app.route('/api/analytics/storage-records', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_storage_records():
    records = db.fetch_all("SELECT * FROM storage_records ORDER BY storage_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/processing-records', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_processing_records():
    records = db.fetch_all("SELECT * FROM processing_records ORDER BY processing_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/waste-monitoring', methods=['GET'])
@app.route('/api/analytics/waste-env-monitoring', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_waste_monitoring():
    records = db.fetch_all("SELECT * FROM waste_monitoring ORDER BY monitoring_date DESC")
    return jsonify({'records': serialize_records(records), 'success': True})

@app.route('/api/analytics/hatchery-batches', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_hatchery_batches():
    records = db.fetch_all("SELECT * FROM hatchery_batches ORDER BY batch_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/hatchery-feeding', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_hatchery_feeding():
    records = db.fetch_all("SELECT * FROM hatchery_feeding ORDER BY feeding_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/hatchery-monitoring', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_hatchery_monitoring():
    records = db.fetch_all("SELECT * FROM hatchery_monitoring ORDER BY monitoring_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/larvae-env-monitoring', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_larvae_env_monitoring():
    records = db.fetch_all("SELECT * FROM environmental_monitoring_larvaefeeding ORDER BY monitoring_date DESC")
    return jsonify({'records': serialize_records(records), 'success': True})

@app.route('/api/analytics/substrate-preparation', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_substrate_preparation():
    records = db.fetch_all("SELECT * FROM substrate_preparation ORDER BY prep_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/health-intervention', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_health_intervention():
    records = db.fetch_all("SELECT * FROM health_intervention ORDER BY health_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/harvest-yield', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_harvest_yield():
    records = _harvest_report_rows()
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/feeding-schedule', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_feeding_schedule():
    records = db.fetch_all("SELECT * FROM feeding_schedule ORDER BY feeding_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/cage-monitoring', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_cage_monitoring():
    records = db.fetch_all("SELECT * FROM cage_monitoring ORDER BY monitoring_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/facility-maintenance', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_facility_maintenance():
    records = db.fetch_all("SELECT * FROM facility_maintenance ORDER BY maintenance_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/pupae-transition', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_pupae_transition():
    records = db.fetch_all("SELECT * FROM pupae_transition ORDER BY transition_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/egg-collection', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_egg_collection():
    records = db.fetch_all("SELECT * FROM egg_collection ORDER BY collection_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/bait-preparation', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_bait_preparation():
    records = db.fetch_all("SELECT * FROM bait_preparation ORDER BY start_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/drying-batches', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_drying_batches():
    records = db.fetch_all("SELECT * FROM drying_batches ORDER BY drying_date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/customers', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_customers():
    records = db.fetch_all("SELECT * FROM customers ORDER BY name")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/sales', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_sales():
    records = db.fetch_all("SELECT s.*, c.name as customer_name FROM sales s JOIN customers c ON s.customer_id = c.id ORDER BY s.date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/deliveries', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_deliveries():
    records = db.fetch_all("SELECT d.*, c.name as customer_name FROM deliveries d JOIN customers c ON d.customer_id = c.id ORDER BY d.date DESC")
    return jsonify({'records': records, 'success': True})

@app.route('/api/analytics/feedback', methods=['GET'])
@login_required
@requires('legacy.read')
def analytics_feedback():
    records = db.fetch_all("SELECT f.*, c.name as customer_name FROM customer_feedback f JOIN customers c ON f.customer_id = c.id ORDER BY f.date DESC")
    return jsonify({'records': records, 'success': True})


# --- Feeding Section ---
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
        }
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

# --- Legacy sales history (read only; new sales use customer orders) ---
@app.route('/api/sales', methods=['GET'])
@login_required
@requires('legacy.read')
def get_sales():
    sales = db.fetch_all("SELECT s.*, c.name as customer_name FROM sales s JOIN customers c ON s.customer_id = c.id")
    return jsonify(sales)

# --- Deliveries CRUD ---
@app.route('/api/deliveries', methods=['GET'])
@login_required
@requires('legacy.read')
def get_deliveries():
    deliveries = db.fetch_all("SELECT d.*, c.name as customer_name FROM deliveries d JOIN customers c ON d.customer_id = c.id")
    return jsonify(deliveries)

# --- Customer Feedback CRUD ---
@app.route('/api/feedback', methods=['GET'])
@login_required
@requires('legacy.read')
def get_feedback():
    feedback = db.fetch_all("SELECT f.*, c.name as customer_name FROM customer_feedback f JOIN customers c ON f.customer_id = c.id")
    return jsonify(feedback)

def send_email(subject, body, to_emails):
    print(f"[DEBUG] Preparing to send email to: {to_emails}")
    msg = MIMEMultipart()
    msg['From'] = EMAIL_HOST_USER
    msg['To'] = ', '.join(to_emails) if isinstance(to_emails, list) else to_emails
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    try:
        server = smtplib.SMTP(EMAIL_HOST, EMAIL_PORT)
        server.starttls()
        server.login(EMAIL_HOST_USER, EMAIL_HOST_PASSWORD)
        print("[DEBUG] Logged in to SMTP server.")
        server.sendmail(EMAIL_HOST_USER, to_emails, msg.as_string())
        print("[DEBUG] Email sent successfully.")
        server.quit()
        logger.info(f"Email sent to {to_emails}")
    except Exception as e:
        print(f"[DEBUG] Failed to send email: {e}")
        logger.error(f"Failed to send email: {e}")

@app.route('/api/send-harvest-report', methods=['POST'])
@login_required
@requires('legacy.read')
def send_harvest_report():
    # Perform the same analysis as /api/statistics/harvest-efficiency
    try:
        # Query to get harvest yield data with correct column names
        query = "SELECT tray_batch_id, harvest_date, larvae_collected, processing_method, storage_temp FROM harvest_yield ORDER BY harvest_date DESC"
        data = db.fetch_all(query)
        if not data:
            summary = "No harvest yield records found."
        else:
            summary = f"Harvest Yield Report ({datetime.now().date()}):\n\n"
            for item in data:
                summary += (
                    f"Tray/Batch ID: {item.get('tray_batch_id', '')}, "
                    f"Date: {item.get('harvest_date', '')}, "
                    f"Larvae Collected: {item.get('larvae_collected', '')} kg, "
                    f"Processing Method: {item.get('processing_method', '')}, "
                    f"Storage Temp: {item.get('storage_temp', 'N/A')}°C\n"
                )
        subject = f"Harvest Yield Report ({datetime.now().date()})"
        send_email(subject, summary, ADMIN_EMAIL)
        return jsonify({'success': True, 'message': 'Harvest report sent to admin.'})
    except Exception as e:
        print(f"[DEBUG] Failed to send harvest report: {e}")
        logger.exception('Request failed')
        return jsonify({'success': False, 'error': 'An internal error occurred.'}), 500
