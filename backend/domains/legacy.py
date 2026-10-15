"""Pre-traceability (legacy) records: forms, statistics and analytics endpoints."""

import smtplib

from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import jsonify, request
from flask_login import current_user, login_required

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
from backend.domains.drying import (
    _canonical_drying_batch_request,
    _drying_add_inputs,
    _drying_batch_detail,
    _drying_batch_row,
    _drying_create_batch,
    _drying_input_rows,
    add_canonical_drying_output,
)
from backend.domains.quality import (
    _canonical_quality_check_response,
    create_canonical_drying_quality_approval,
)


@app.route('/api/waste-monitoring', methods=['POST'])
@login_required
@requires('production.write')
def handle_waste_environmental_monitoring():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data provided'}), 400

    normalized_data = normalize_keys(data)
    required_fields = ['monitoring_date', 'monitoring_time', 'temperature', 'water_consistency', 'odor_level', 'pest_presence']
    
    missing_fields = [field for field in required_fields if field not in normalized_data or not normalized_data.get(field)]
    if missing_fields:
        return jsonify({'success': False, 'message': f'Missing or empty required fields: {", ".join(missing_fields)}'}), 400

    query = """
        INSERT INTO waste_monitoring (
            monitoring_date, monitoring_time, temperature, water_consistency, odor_level, 
            pest_presence, pest_details, mitigation_actions, remarks, recorded_by
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (
        normalized_data.get('monitoring_date'),
        normalized_data.get('monitoring_time'),
        normalized_data.get('temperature'),
        normalized_data.get('water_consistency'),
        normalized_data.get('odor_level'),
        normalized_data.get('pest_presence'),
        normalized_data.get('pest_details'),
        normalized_data.get('mitigation_actions'),
        normalized_data.get('remarks'),
        current_user.username
    )

    try:
        db.execute_query(query, params)
        logger.info(f"Waste environmental monitoring data saved for {normalized_data.get('monitoring_date')}")
        return jsonify({'success': True, 'message': 'Environmental monitoring record created successfully'})
    except Exception as e:
        logger.error(f"Error creating waste environmental monitoring record: {e}")
        return jsonify({'success': False, 'message': 'Failed to create environmental monitoring record'}), 500


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


@app.route('/api/drying/batch', methods=['POST'])
@login_required
@requires('production.write')
def create_drying_batch():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400

    data = normalize_keys(data)
    if _canonical_drying_batch_request(data):
        try:
            record = _drying_create_batch(data)
            return jsonify({
                'success': True,
                'message': 'Drying Batch created',
                'record': record,
                'data': record,
                'id': record['id'],
                'business_id': record['business_id'],
            }), 201
        except ProductionEventPermissionError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 400
        except Exception:
            logger.exception('Error creating canonical Drying Batch through legacy route')
            return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500
    required_fields = ['batch_id', 'drying_date', 'drying_method', 'personnel', 'status']
    if any(field not in data for field in required_fields):
        missing_fields = [field for field in required_fields if field not in data]
        return jsonify({'success': False, 'message': f'Missing required fields: {", ".join(missing_fields)}'}), 400

    try:
        query = """INSERT INTO drying_batches (batch_id, drying_date, drying_method, personnel, status) 
                   VALUES (%s, %s, %s, %s, %s)"""
        params = (data['batch_id'], data['drying_date'], data['drying_method'], data['personnel'], data['status'])
        record = db.execute_returning(query + " RETURNING id, business_id, batch_id", params)
        logger.info(f"Drying batch {data['batch_id']} created.")
        return jsonify({
            'success': True,
            'message': 'Drying batch created successfully',
            'record': record,
            'id': record['id'],
            'business_id': record['business_id'],
        }), 201
    except Exception as e:
        logger.error(f"Error creating drying batch: {e}")
        logger.exception('Request failed')
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/drying/input', methods=['POST'])
@login_required
@requires('production.write')
def create_drying_input():
    data = request.get_json()
    data = normalize_keys(data)
    if any(data.get(key) not in (None, '') for key in (
        'drying_batch_id', 'harvest_id', 'harvest_code', 'harvest_inputs', 'inputs'
    )):
        try:
            batch_ref = data.get('drying_batch_id') or data.get('batch_code') or data.get('batch_id')
            if batch_ref in (None, ''):
                raise ValueError('drying_batch_id or batch_code is required')
            rows = _drying_input_rows(data)
            with db.transaction() as cursor:
                batch = _drying_batch_row(cursor, batch_ref, for_update=True)
                _drying_add_inputs(cursor, batch, rows, data)
                record = _drying_batch_detail(cursor, batch)
            return jsonify({
                'success': True,
                'message': 'Drying inputs recorded',
                'data': record,
            }), 201
        except ProductionEventPermissionError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 403
        except ValueError as exc:
            return jsonify({'success': False, 'message': str(exc)}), 400
        except Exception:
            logger.exception('Error recording canonical Drying inputs through legacy route')
            return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500
    
    # Basic validation
    required_fields = ['batch_id', 'wet_harvested', 'wet_placed', 'dried_by_personnel', 'sand_used']
    if any(f not in data for f in required_fields):
        return jsonify({'success': False, 'message': 'Missing required fields.'}), 400

    query = """INSERT INTO drying_input (batch_id, wet_harvested_kg, wet_placed_for_drying_kg, dried_by_personnel_kg, sand_used_kg, sand_reused_kg, notes, recorded_by) 
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"""
    params = (
        data['batch_id'], data['wet_harvested'], data['wet_placed'], 
        data['dried_by_personnel'], data['sand_used'], data.get('sand_reused'), data.get('notes'), current_user.username
    )
    db.execute_query(query, params)
    return jsonify({'success': True, 'message': 'Drying input recorded successfully.'})

@app.route('/api/drying/output', methods=['POST'])
@login_required
@requires('production.write')
def create_drying_output():
    data = request.get_json()
    data = normalize_keys(data)
    if any(data.get(key) not in (None, '') for key in (
        'drying_batch_id', 'output_date', 'produced_at', 'output_unit', 'moisture_percent'
    )):
        batch_ref = data.get('drying_batch_id') or data.get('batch_code') or data.get('batch_id')
        if batch_ref in (None, ''):
            return jsonify({'success': False, 'message': 'drying_batch_id or batch_code is required'}), 400
        data['drying_batch_id'] = batch_ref
        return add_canonical_drying_output(batch_ref)
    required = ['batch_id', 'dried_produced']
    if any(field not in data for field in required):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        # Fetch the wet weight from drying_input to calculate ratio and yield
        input_query = "SELECT SUM(wet_placed_for_drying_kg) as total_wet FROM drying_input WHERE batch_id = %s"
        input_result = db.fetch_one(input_query, (data['batch_id'],))
        # NUMERIC columns come back as Decimal; mixing with float would raise TypeError.
        total_wet_weight = float(input_result['total_wet']) if input_result and input_result['total_wet'] else 0.0

        dried_produced = float(data['dried_produced'])
        actual_ratio = f"{total_wet_weight}:{dried_produced}" if dried_produced > 0 else "N/A"
        yield_percentage = (dried_produced / total_wet_weight) * 100 if total_wet_weight > 0 else 0

        query = """INSERT INTO drying_output (batch_id, dried_produced_kg, solar_drying_taken_kg, stored_in_silo_bag_kg, sold_kg, actual_ratio, yield_percentage, notes, recorded_by) 
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
        params = (
            data['batch_id'],
            dried_produced,
            data.get('solar_drying_taken'),
            data.get('silo_bag_stored'),
            data.get('dried_sold'),
            actual_ratio,
            yield_percentage,
            data.get('notes'),
            current_user.username
        )
        db.execute_query(query, params)
        logger.info(f"Drying output recorded for batch {data['batch_id']}")
        return jsonify({'success': True, 'message': 'Drying output recorded successfully', 'actual_ratio': actual_ratio, 'yield_percentage': yield_percentage}), 201
    except Exception as e:
        logger.error(f"Error in create_drying_output: {e}")
        return jsonify({'success': False, 'message': 'An error occurred'}), 500

@app.route('/api/drying/qc', methods=['POST'])
@login_required
@requires('quality.decide')
def create_drying_qc():
    data = request.get_json()
    data = normalize_keys(data)
    if any(data.get(key) not in (None, '') for key in (
        'drying_batch_id', 'check_status', 'moisture_percent'
    )):
        return _canonical_quality_check_response(data)
    required = ['batch_id', 'qc_date', 'sand_removal', 'color_quality', 'moisture_level', 'qc_personnel']
    if any(field not in data for field in required):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    # Handle multiple selection for contaminants
    contaminants = data.get('contaminants_found', [])
    contaminants_str = ','.join(contaminants) if isinstance(contaminants, list) else contaminants

    query = """INSERT INTO drying_quality_control (batch_id, qc_date, sand_removal, contaminants_found, color_quality, moisture_level, qc_personnel, notes, recorded_by) 
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
    params = (data['batch_id'], data['qc_date'], data['sand_removal'], contaminants_str, data['color_quality'], data['moisture_level'], data['qc_personnel'], data.get('notes'), current_user.username)
    db.execute_query(query, params)
    return jsonify({'success': True, 'message': 'Drying QC recorded successfully.'})

@app.route('/api/drying/quality-control', methods=['POST'])
@login_required
@requires('quality.decide')
def deprecated_create_drying_quality_control():
    # This is a deprecated route name, redirecting logic to the new one.
    return create_drying_qc()

@app.route('/api/drying/remarks', methods=['POST'])
@login_required
@requires('production.write')
def create_drying_remarks():
    # This route seems to be unused based on frontend JS.
    # If it were to be used, it would likely add remarks to an existing batch.
    return jsonify({'success': False, 'message': 'This route is not implemented.'}), 404

@app.route('/api/drying/review', methods=['POST'])
@login_required
@requires('quality.decide')
def create_drying_review():
    data = request.get_json()
    data = normalize_keys(data)
    if any(data.get(key) not in (None, '') for key in (
        'quality_check_id', 'check_id', 'drying_batch_id', 'decision'
    )):
        return create_canonical_drying_quality_approval()
    required = ['batch_id', 'reviewed_by', 'review_date', 'approval_status']
    if any(field not in data for field in required):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    query = """INSERT INTO drying_review_approval (batch_id, reviewed_by, review_date, approval_status, comments, recorded_by) 
               VALUES (%s, %s, %s, %s, %s, %s)"""
    params = (data['batch_id'], data['reviewed_by'], data['review_date'], data['approval_status'], data.get('comments'), current_user.username)
    db.execute_query(query, params)
    return jsonify({'success': True, 'message': 'Drying review recorded successfully.'})

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

# --- Fly Facility Section ---
@app.route('/api/facility/cage-monitoring', methods=['POST'])
@login_required
@requires('production.write')
def create_cage_monitoring():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400

    data = normalize_keys(data)
    
    required_fields = ['date', 'cage_id', 'temperature', 'humidity', 'lighting_hours', 'ventilation_ok', 'cage_cleaned', 'cage_damage']
    if any(field not in data for field in required_fields):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        query = """
            INSERT INTO cage_monitoring (
                monitoring_date, cage_id, temperature, humidity, lighting_hours, ventilation_ok, 
                cage_cleaned, cage_damage, damage_notes, additional_notes, cages_damaged_list, recorded_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            data['date'], data['cage_id'], data['temperature'], data['humidity'], data['lighting_hours'],
            data['ventilation_ok'], data['cage_cleaned'], data['cage_damage'],
            data.get('damage_notes'), data.get('additional_notes'), data.get('cages_damaged_list'), current_user.username
        )
        db.execute_query(query, params)
        logger.info(f"Cage monitoring recorded for {data['cage_id']}")
        return jsonify({'success': True, 'message': 'Cage monitoring data saved successfully'}), 201
    except Exception as e:
        logger.error(f"Error saving cage monitoring data: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/facility/maintenance', methods=['POST'])
@login_required
@requires('production.write')
def create_facility_maintenance():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400
    
    data = normalize_keys(data)

    required_fields = ['date', 'moat_check', 'ants_present', 'rodents_present', 'bird_net_ok', 'trench_refilled', 'maintenance_notes']
    if any(field not in data for field in required_fields):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        query = """
            INSERT INTO facility_maintenance (
                maintenance_date, moat_check, ants_present, rodents_present, bird_net_ok, 
                trench_refilled, maintenance_notes, recorded_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            data['date'], data['moat_check'], data['ants_present'], data['rodents_present'],
            data['bird_net_ok'], data['trench_refilled'], data['maintenance_notes'], current_user.username
        )
        db.execute_query(query, params)
        logger.info(f"Facility maintenance recorded for {data['date']}")
        return jsonify({'success': True, 'message': 'Facility maintenance data saved successfully'}), 201
    except Exception as e:
        logger.error(f"Error saving facility maintenance data: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/facility/pupae-transition', methods=['POST'])
@login_required
@requires('production.write')
def create_pupae_transition():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400

    data = normalize_keys(data)
    
    required_fields = ['date', 'love_cage_id', 'pupae_weight_added_kg', 'old_pupae_removed_kg', 'dead_flies_removed', 'water_points_checked', 'new_egg_crates_installed']
    if any(field not in data for field in required_fields):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        query = """
            INSERT INTO pupae_transition (
                transition_date, love_cage_id, pupae_weight_added, old_pupae_removed, dead_flies_removed, 
                water_points_checked, new_egg_crates_installed, number_of_crates, notes, recorded_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            data['date'], data['love_cage_id'],
            data['pupae_weight_added_kg'], data['old_pupae_removed_kg'],
            data['dead_flies_removed'], data['water_points_checked'], data['new_egg_crates_installed'],
            data.get('number_of_crates'), data.get('notes'), current_user.username
        )
        db.execute_query(query, params)
        logger.info(f"Pupae transition recorded for {data['love_cage_id']}")
        return jsonify({'success': True, 'message': 'Pupae transition data saved successfully'}), 201
    except Exception as e:
        logger.error(f"Error saving pupae transition data: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/facility/egg-collection', methods=['POST'])
@login_required
@requires('production.write')
def create_egg_collection():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'Invalid JSON format'}), 400

    data = normalize_keys(data)

    required_fields = ['date', 'time', 'cage_id', 'eggs_collected', 'bait_replaced', 'eggs_intact', 'collector_name', 'collection_method']
    if any(field not in data for field in required_fields):
        return jsonify({'success': False, 'message': 'Missing required fields'}), 400

    try:
        query = """
            INSERT INTO egg_collection (
                collection_date, collection_time, cage_id, eggs_collected, bait_replaced, 
                eggs_intact, collector_name, collection_method, notes, recorded_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            data['date'], data['time'], data['cage_id'], data['eggs_collected'], data['bait_replaced'],
            data['eggs_intact'], data['collector_name'], data['collection_method'], data.get('notes'), current_user.username
        )
        db.execute_query(query, params)
        logger.info(f"Egg collection recorded for {data['cage_id']}")
        return jsonify({'success': True, 'message': 'Egg collection data saved successfully'}), 201
    except Exception as e:
        logger.error(f"Error saving egg collection data: {e}")
        return jsonify({'success': False, 'message': 'An internal error occurred.'}), 500

@app.route('/api/facility/bait-preparation', methods=['POST'])
@login_required
@requires('production.write')
def create_bait_preparation():
    data = request.get_json()
    normalized_data = normalize_keys(data)
    required_fields = ['barrel_id', 'bait_type', 'ingredients_added', 'start_date', 'ready_date']
    
    missing_fields = [field for field in required_fields if field not in normalized_data or not normalized_data.get(field)]
    if missing_fields:
        return jsonify({'success': False, 'message': f'Missing or empty required fields: {", ".join(missing_fields)}'}), 400
        
    query = """
        INSERT INTO bait_preparation (barrel_id, bait_type, ingredients_added, start_date, ready_date, used_in_cage_ids, notes, recorded_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    params = (
        normalized_data.get('barrel_id'),
        normalized_data.get('bait_type'),
        normalized_data.get('ingredients_added'),
        normalized_data.get('start_date'),
        normalized_data.get('ready_date'),
        normalized_data.get('used_in_cage_ids'),
        normalized_data.get('notes'),
        current_user.username
    )
    
    try:
        db.execute_query(query, params)
        logger.info(f"Bait preparation data saved for barrel {normalized_data.get('barrel_id')}")
        return jsonify({'success': True, 'message': 'Bait preparation record created successfully'})
    except Exception as e:
        logger.error(f"Error creating bait preparation record: {e}")
        return jsonify({'success': False, 'message': 'Failed to create bait preparation record'}), 500

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

# --- Hatchery Routes ---

@app.route('/api/hatchery/batch', methods=['POST'])
@login_required
@requires('production.write')
def create_hatchery_batch():
    try:
        data = request.get_json()
        required_fields = [
            'batch_date', 'egg_incubation_date',
            'total_eggs_grams', 'expected_hatch_date', 'supervisor_name'
        ]
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400
        
        query = '''INSERT INTO hatchery_batches (
            batch_number, batch_date, egg_incubation_date, total_eggs_grams,
            expected_hatch_date, actual_hatch_date, hatch_days, supervisor_name, notes
        ) VALUES (COALESCE(%s, ('HAT-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                                lpad(nextval('phase_one_hatchery_batch_seq')::text, 5, '0'))),
                  %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, batch_number'''
        params = (
            data.get('batch_number'), data['batch_date'], data['egg_incubation_date'],
            float(data['total_eggs_grams']), data['expected_hatch_date'],
            data.get('actual_hatch_date'), data.get('hatch_days'),
            data['supervisor_name'], data.get('notes')
        )
        record = db.execute_returning(query, params)
        return jsonify({
            'success': True,
            'message': 'Batch information saved successfully',
            'record': record,
            'id': record['id'],
            'business_id': record['batch_number'],
        }), 201
    except Exception as e:
        logger.error(f'Error saving hatchery batch: {e}')
        logger.exception('Request failed')
        return jsonify({'error': 'An internal error occurred.'}), 500

@app.route('/api/hatchery/next-batch-id', methods=['GET'])
@login_required
def get_next_hatchery_batch_id():
    try:
        record = db.execute_returning("""
            SELECT 'HAT-' || to_char(CURRENT_DATE, 'YYYY') || '-' ||
                   lpad(nextval('phase_one_hatchery_batch_seq')::text, 5, '0') AS next_batch_id
        """)
        return jsonify({'next_batch_id': record['next_batch_id']}), 200
    except Exception as e:
        logger.error(f'Error getting next hatchery batch ID: {e}')
        logger.exception('Request failed')
        return jsonify({'error': 'An internal error occurred.'}), 500

@app.route('/api/hatchery/feeding', methods=['POST'])
@login_required
@requires('production.write')
def create_hatchery_feeding():
    try:
        data = request.get_json()
        required_fields = [
            'batch_id', 'feeding_date', 'feed_per_5g_eggs_grams',
            'total_feed_used_grams', 'days_to_utilize', 'feed_type', 'distribution_method'
        ]
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        query = '''INSERT INTO hatchery_feeding (
            batch_id, feeding_date, feed_per_5g_eggs_grams, total_feed_used_grams,
            days_to_utilize, feed_type, distribution_method, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)'''
        params = (
            data['batch_id'], data['feeding_date'], float(data['feed_per_5g_eggs_grams']),
            float(data['total_feed_used_grams']), int(data['days_to_utilize']),
            data['feed_type'], data['distribution_method'], data.get('notes')
        )
        db.execute_query(query, params)
        return jsonify({'message': 'Feeding record saved successfully'}), 201
    except Exception as e:
        logger.error(f'Error saving feeding record: {e}')
        logger.exception('Request failed')
        return jsonify({'error': 'An internal error occurred.'}), 500

@app.route('/api/hatchery/monitoring', methods=['POST'])
@login_required
@requires('production.write')
def create_hatchery_monitoring():
    try:
        data = request.get_json()
        required_fields = ['monitoring_date', 'temperature_c', 'humidity_percent']
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        query = '''INSERT INTO hatchery_monitoring (
            monitoring_date, temperature_c, humidity_percent, adjustments_made
        ) VALUES (%s, %s, %s, %s)'''
        params = (
            data['monitoring_date'], float(data['temperature_c']), float(data['humidity_percent']), data.get('adjustments_made')
        )
        db.execute_query(query, params)
        return jsonify({'message': 'Monitoring record saved successfully'}), 201
    except Exception as e:
        logger.error(f'Error saving monitoring record: {e}')
        logger.exception('Request failed')
        return jsonify({'error': 'An internal error occurred.'}), 500

@app.route('/api/hatchery/cleaning', methods=['POST'])
@login_required
@requires('production.write')
def create_hatchery_cleaning():
    try:
        data = request.get_json()
        required_fields = ['cleaning_date', 'areas_cleaned', 'cleaning_materials', 'cleaning_personnel']
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        query = '''INSERT INTO hatchery_cleaning (
            cleaning_date, areas_cleaned, cleaning_materials, cleaning_personnel, remarks
        ) VALUES (%s, %s, %s, %s, %s)'''
        params = (
            data['cleaning_date'], data['areas_cleaned'], data['cleaning_materials'], data['cleaning_personnel'], data.get('remarks')
        )
        db.execute_query(query, params)
        return jsonify({'message': 'Cleaning record saved successfully'}), 201
    except Exception as e:
        logger.error(f'Error saving cleaning record: {e}')
        logger.exception('Request failed')
        return jsonify({'error': 'An internal error occurred.'}), 500

@app.route('/api/hatchery/problems', methods=['POST'])
@login_required
@requires('production.write')
def create_hatchery_problem():
    try:
        data = request.get_json()
        required_fields = ['problem_date', 'problem_identified', 'proposed_solution', 'responsible_person']
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        query = '''INSERT INTO hatchery_problems (
            problem_date, problem_identified, proposed_solution, responsible_person,
            days_to_implement, resolution_status, additional_comments
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)'''
        params = (
            data['problem_date'], data['problem_identified'], data['proposed_solution'],
            data['responsible_person'], data.get('days_to_implement'), data.get('resolution_status'), data.get('additional_comments')
        )
        db.execute_query(query, params)
        return jsonify({'message': 'Problem record saved successfully'}), 201
    except Exception as e:
        logger.error(f'Error saving problem record: {e}')
        logger.exception('Request failed')
        return jsonify({'error': 'An internal error occurred.'}), 500

# Add missing hatchery endpoints that frontend is calling
@app.route('/api/hatchery/health', methods=['POST'])
@login_required
@requires('production.write')
def create_hatchery_health():
    try:
        # Debug: Check if request has JSON content
        if not request.is_json:
            logger.error(f"Request is not JSON. Content-Type: {request.content_type}")
            return jsonify({'error': 'Request must be JSON'}), 400
        
        data = request.get_json()
        if data is None:
            logger.error("Failed to parse JSON data")
            return jsonify({'error': 'Invalid JSON data'}), 400
            
        required_fields = ['health_date', 'health_issue', 'severity', 'action_taken']
        if any(f not in data for f in required_fields):
            return jsonify({'error': 'Missing required fields'}), 400

        query = '''INSERT INTO hatchery_health_interventions (
            health_date, health_issue, severity, action_taken, follow_up_date, resolved, comments
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)'''
        params = (
            data['health_date'], data['health_issue'], data['severity'], data['action_taken'],
            data.get('follow_up_date'), data.get('resolved'), data.get('comments')
        )
        db.execute_query(query, params)
        return jsonify({'message': 'Health intervention record saved successfully'}), 201
    except Exception as e:
        logger.error(f'Error saving health intervention record: {e}')
        logger.exception('Request failed')
        return jsonify({'error': 'An internal error occurred.'}), 500

@app.route('/api/hatchery/batch-information', methods=['POST'])
@login_required
@requires('production.write')
def create_hatchery_batch_information():
    # Alias for the existing batch endpoint
    return create_hatchery_batch()

@app.route('/api/hatchery/feeding-records', methods=['POST'])
@login_required
@requires('production.write')
def create_hatchery_feeding_records():
    # Alias for the existing feeding endpoint
    return create_hatchery_feeding()

@app.route('/api/hatchery/environmental-monitoring', methods=['POST'])
@login_required
@requires('production.write')
def create_hatchery_environmental_monitoring():
    # Alias for the existing monitoring endpoint
    return create_hatchery_monitoring()

# --- Sales CRUD ---
@app.route('/api/sales', methods=['GET'])
@login_required
@requires('legacy.read')
def get_sales():
    sales = db.fetch_all("SELECT s.*, c.name as customer_name FROM sales s JOIN customers c ON s.customer_id = c.id")
    return jsonify(sales)

@app.route('/api/sales', methods=['POST'])
@login_required
@requires('legacy.write')
def add_sale():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    customer_id = data.get('customer_id') or data.get('customer')
    if not customer_id:
        return jsonify({'success': False, 'error': 'customer_id is required'}), 400
    if not data.get('date') or not data.get('amount'):
        return jsonify({'success': False, 'error': 'date and amount are required'}), 400
    query = "INSERT INTO sales (date, customer_id, product, quantity, amount) VALUES (%s, %s, %s, %s, %s) RETURNING id"
    sale_id = db.execute_returning(query, (data['date'], customer_id, data.get('product'), data.get('quantity'), data['amount']))['id']
    # Send email notification for sale
    customer = db.fetch_one("SELECT name, email, address FROM customers WHERE id=%s", (customer_id,))
    print("[DEBUG] Customer fetched from DB (sale):", customer)
    if customer and customer.get('email'):
        subject = f"Sale Confirmation for {customer['name']}"
        body = (
            f"Dear {customer['name']},\n\n"
            f"Thank you for your purchase! Here are your sale details:\n"
            f"Date: {data['date']}\n"
            f"Product/Service: {data.get('product', '')}\n"
            f"Quantity: {data.get('quantity', '')}\n"
            f"Amount: {data.get('amount', '')}\n"
            f"Delivery Address: {customer.get('address', '')}\n\n"
            f"Best regards,\nBSF Farm Manager"
        )
        send_email(subject, body, [customer['email'], ADMIN_EMAIL])
    return jsonify({'success': True, 'id': sale_id})

@app.route('/api/sales/<int:sale_id>', methods=['PUT'])
@login_required
@requires('legacy.write')
def edit_sale(sale_id):
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    customer_id = data.get('customer_id') or data.get('customer')
    if not customer_id:
        return jsonify({'success': False, 'error': 'customer_id is required'}), 400
    query = "UPDATE sales SET date=%s, customer_id=%s, product=%s, quantity=%s, amount=%s WHERE id=%s"
    db.execute_query(query, (data['date'], customer_id, data.get('product'), data.get('quantity'), data['amount'], sale_id))
    return jsonify({'success': True})

# --- Deliveries CRUD ---
@app.route('/api/deliveries', methods=['GET'])
@login_required
@requires('legacy.read')
def get_deliveries():
    deliveries = db.fetch_all("SELECT d.*, c.name as customer_name FROM deliveries d JOIN customers c ON d.customer_id = c.id")
    return jsonify(deliveries)

@app.route('/api/deliveries', methods=['POST'])
@login_required
@requires('legacy.write')
def add_delivery():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    customer_id = data.get('customer_id') or data.get('customer')
    if not customer_id:
        return jsonify({'success': False, 'error': 'customer_id is required'}), 400
    if not data.get('date') or not data.get('status'):
        return jsonify({'success': False, 'error': 'date and status are required'}), 400
    query = "INSERT INTO deliveries (date, customer_id, product, quantity, status, notes) VALUES (%s, %s, %s, %s, %s, %s) RETURNING id"
    delivery_id = db.execute_returning(query, (data['date'], customer_id, data.get('product'), data.get('quantity'), data['status'], data.get('notes')))['id']
    # Send email for any status
    customer = db.fetch_one("SELECT name, email, address FROM customers WHERE id=%s", (customer_id,))
    print("[DEBUG] Customer fetched from DB (delivery):", customer)
    if customer and customer.get('email'):
        subject = f"Delivery Update for {customer['name']}"
        body = (
            f"Dear {customer['name']},\n\n"
            f"Your delivery status is now: {data['status']}\n"
            f"Date of Delivery: {data['date']}\n"
            f"Product/Service: {data.get('product', '')}\n"
            f"Quantity: {data.get('quantity', '')}\n"
            f"Delivery Address: {customer.get('address', '')}\n\n"
            f"Best regards,\nBSF Farm Manager"
        )
        send_email(subject, body, [customer['email'], ADMIN_EMAIL])
    return jsonify({'success': True, 'id': delivery_id})

@app.route('/api/deliveries/<int:delivery_id>', methods=['PUT'])
@login_required
@requires('legacy.write')
def edit_delivery(delivery_id):
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    customer_id = data.get('customer_id') or data.get('customer')
    if not customer_id:
        return jsonify({'success': False, 'error': 'customer_id is required'}), 400
    # Fetch previous status
    prev = db.fetch_one("SELECT status FROM deliveries WHERE id=%s", (delivery_id,))
    prev_status = prev['status'] if prev else None
    query = "UPDATE deliveries SET date=%s, customer_id=%s, product=%s, quantity=%s, status=%s, notes=%s WHERE id=%s"
    db.execute_query(query, (data['date'], customer_id, data.get('product'), data.get('quantity'), data['status'], data.get('notes'), delivery_id))
    # Send email if status is Delivered and was not previously Delivered
    if data['status'].strip().lower() == 'delivered' and (not prev_status or prev_status.strip().lower() != 'delivered'):
        customer = db.fetch_one("SELECT name, email, address FROM customers WHERE id=%s", (customer_id,))
        if customer and customer.get('email'):
            subject = f"Delivery Confirmation for {customer['name']}"
            body = (
                f"Dear {customer['name']},\n\n"
                f"Your delivery has been completed. Here are your delivery details:\n"
                f"Date of Delivery: {data['date']}\n"
                f"Product/Service: {data.get('product', '')}\n"
                f"Quantity: {data.get('quantity', '')}\n"
                f"Delivery Address: {customer.get('address', '')}\n\n"
                f"Best regards,\nBSF Farm Manager"
            )
            send_email(subject, body, [customer['email'], ADMIN_EMAIL])
    return jsonify({'success': True})

# --- Customer Feedback CRUD ---
@app.route('/api/feedback', methods=['GET'])
@login_required
@requires('legacy.read')
def get_feedback():
    feedback = db.fetch_all("SELECT f.*, c.name as customer_name FROM customer_feedback f JOIN customers c ON f.customer_id = c.id")
    return jsonify(feedback)

@app.route('/api/feedback', methods=['POST'])
@login_required
@requires('legacy.write')
def add_feedback():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'error': 'No data provided'}), 400
    required = ['date', 'customer_id', 'feedback', 'rating']
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify({'success': False, 'error': f'Missing required fields: {", ".join(missing)}'}), 400
    try:
        query = "INSERT INTO customer_feedback (date, customer_id, feedback, rating) VALUES (%s, %s, %s, %s) RETURNING id"
        feedback_id = db.execute_returning(query, (data['date'], data['customer_id'], data['feedback'], data['rating']))['id']
        return jsonify({'success': True, 'id': feedback_id})
    except Exception as e:
        logger.error(f"Error saving feedback: {e}")
        return jsonify({'success': False, 'error': 'Failed to save feedback'}), 500

@app.route('/api/feedback/<int:feedback_id>', methods=['PUT'])
@login_required
@requires('legacy.write')
def edit_feedback(feedback_id):
    data = request.get_json()
    query = "UPDATE customer_feedback SET date=%s, customer_id=%s, feedback=%s, rating=%s WHERE id=%s"
    db.execute_query(query, (data['date'], data['customer_id'], data['feedback'], data['rating'], feedback_id))
    return jsonify({'success': True})

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
