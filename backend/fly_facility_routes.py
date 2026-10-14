from flask import Blueprint, request, jsonify
from backend.database import DatabaseConnection
from datetime import datetime
import logging
from backend.config import (
    API_ENDPOINTS, TABLE_NAMES, REQUIRED_FIELDS,
    NUMERIC_FIELDS, SUCCESS_MESSAGES, ERROR_MESSAGES
)

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

fly_facility = Blueprint('fly_facility', __name__)
db = DatabaseConnection()

def validate_numeric_fields(data, form_type):
    """Validate numeric fields for a given form type."""
    if form_type not in NUMERIC_FIELDS:
        return True
    
    try:
        for field in NUMERIC_FIELDS[form_type]:
            if field in data:
                float(data[field])
        return True
    except ValueError:
        return False

def validate_required_fields(data, form_type):
    """Validate required fields for a given form type."""
    if form_type not in REQUIRED_FIELDS:
        return []
    
    return [field for field in REQUIRED_FIELDS[form_type] if not data.get(field)]

# Cage Monitoring
@fly_facility.route(API_ENDPOINTS['cage_monitoring'], methods=['POST'])
def cage_monitoring():
    print("\n=== Cage Monitoring Request ===")
    try:
        data = request.get_json()
        print(f"Received data: {data}")

        # Validate required fields
        missing_fields = validate_required_fields(data, 'cage_monitoring')
        if missing_fields:
            print(f"Missing required fields: {missing_fields}")
            return jsonify({
                "error": ERROR_MESSAGES['missing_fields'].format(', '.join(missing_fields))
            }), 400

        # Validate numeric fields
        if not validate_numeric_fields(data, 'cage_monitoring'):
            print("Invalid numeric values")
            return jsonify({
                "error": ERROR_MESSAGES['invalid_numeric'].format('Temperature, humidity, and lighting hours')
            }), 400

        # DB Interaction
        query = f"""
        INSERT INTO {TABLE_NAMES['cage_monitoring']} (
            monitoring_date, cage_id, temperature, humidity, lighting_hours,
            ventilation_ok, cage_cleaned, dead_flies_removed,
            cage_damage, damage_notes, additional_notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        params = (
            data['date'], data['cageId'],
            float(data['temperature']), int(data['humidity']),
            float(data['lightingHours']), data['ventilationOk'],
            data['cageCleaned'], data['deadFliesRemoved'],
            data['cageDamage'], data.get('damageNotes'),
            data.get('additionalNotes')
        )

        print("Executing database query...")
        db.execute_query(query, params)
        return jsonify({
            "status": "success",
            "message": SUCCESS_MESSAGES['cage_monitoring']
        }), 201
            
    except Exception as e:
        logger.exception('Error in %s', API_ENDPOINTS['cage_monitoring'])
        return jsonify({
            "status": "error",
            "message": ERROR_MESSAGES['server_error'].format('please try again')
        }), 500

# Facility Maintenance
@fly_facility.route(API_ENDPOINTS['facility_maintenance'], methods=['POST'])
def facility_maintenance():
    print("\n=== Facility Maintenance Request ===")
    try:
        data = request.get_json()
        print(f"Received data: {data}")

        # Validate required fields
        missing_fields = validate_required_fields(data, 'facility_maintenance')
        if missing_fields:
            print(f"Missing required fields: {missing_fields}")
            return jsonify({
                "error": ERROR_MESSAGES['missing_fields'].format(', '.join(missing_fields))
            }), 400

        # DB Interaction
        query = f"""
        INSERT INTO {TABLE_NAMES['facility_maintenance']} (
            maintenance_date, moat_check, ants_present, rodents_present,
            bird_net_ok, trench_refilled, maintenance_notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        params = (
            data['date'], data['moatCheck'],
            data['antsPresent'], data['rodentsPresent'],
            data['birdNetOk'], data['trenchRefilled'],
            data['maintenanceNotes']
        )

        print("Executing database query...")
        db.execute_query(query, params)
        return jsonify({
            "status": "success",
            "message": SUCCESS_MESSAGES['facility_maintenance']
        }), 201
            
    except Exception as e:
        logger.exception('Error in %s', API_ENDPOINTS['facility_maintenance'])
        return jsonify({
            "status": "error",
            "message": ERROR_MESSAGES['server_error'].format('please try again')
        }), 500

# Pupae Transition
@fly_facility.route(API_ENDPOINTS['pupae_transition'], methods=['POST'])
def pupae_transition():
    print("\n=== Pupae Transition Request ===")
    try:
        data = request.get_json()
        print(f"Received data: {data}")

        # Validate required fields
        missing_fields = validate_required_fields(data, 'pupae_transition')
        if missing_fields:
            print(f"Missing required fields: {missing_fields}")
            return jsonify({
                "error": ERROR_MESSAGES['missing_fields'].format(', '.join(missing_fields))
            }), 400

        # Validate numeric fields
        if not validate_numeric_fields(data, 'pupae_transition'):
            print("Invalid numeric values")
            return jsonify({
                "error": ERROR_MESSAGES['invalid_numeric'].format('Pupae weights and number of crates')
            }), 400

        # DB Interaction
        query = f"""
        INSERT INTO {TABLE_NAMES['pupae_transition']} (
            transition_date, love_cage_id, pupae_weight_added, old_pupae_removed,
            dead_flies_removed, water_points_checked, new_egg_crates_installed,
            number_of_crates, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        params = (
            data['date'], data['loveCageId'],
            float(data['pupaeWeightAdded']), float(data['oldPupaeRemoved']),
            data['deadFliesRemoved'], data['waterPointsChecked'],
            data['newEggCratesInstalled'], data.get('numberOfCrates'),
            data.get('notes')
        )

        print("Executing database query...")
        db.execute_query(query, params)
        return jsonify({
            "status": "success",
            "message": SUCCESS_MESSAGES['pupae_transition']
        }), 201
            
    except Exception as e:
        logger.exception('Error in %s', API_ENDPOINTS['pupae_transition'])
        return jsonify({
            "status": "error",
            "message": ERROR_MESSAGES['server_error'].format('please try again')
        }), 500

# Egg Collection
@fly_facility.route(API_ENDPOINTS['egg_collection'], methods=['POST'])
def egg_collection():
    print("\n=== Egg Collection Request ===")
    try:
        data = request.get_json()
        print(f"Received data: {data}")

        # Validate required fields
        missing_fields = validate_required_fields(data, 'egg_collection')
        if missing_fields:
            print(f"Missing required fields: {missing_fields}")
            return jsonify({
                "error": ERROR_MESSAGES['missing_fields'].format(', '.join(missing_fields))
            }), 400

        # Validate numeric fields
        if not validate_numeric_fields(data, 'egg_collection'):
            print("Invalid numeric values")
            return jsonify({
                "error": ERROR_MESSAGES['invalid_numeric'].format('Eggs collected')
            }), 400

        # DB Interaction
        query = f"""
        INSERT INTO {TABLE_NAMES['egg_collection']} (
            collection_date, collection_time, cage_id, eggs_collected, bait_replaced,
            eggs_intact, collector_name, collection_method, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        params = (
            data['date'], data['time'], data['cageId'],
            float(data['eggsCollected']), data['baitReplaced'],
            data['eggsIntact'], data['collectorName'],
            data['collectionMethod'], data.get('notes')
        )

        print("Executing database query...")
        db.execute_query(query, params)
        return jsonify({
            "status": "success",
            "message": SUCCESS_MESSAGES['egg_collection']
        }), 201
            
    except Exception as e:
        logger.exception('Error in %s', API_ENDPOINTS['egg_collection'])
        return jsonify({
            "status": "error",
            "message": ERROR_MESSAGES['server_error'].format('please try again')
        }), 500

# Bait Preparation
@fly_facility.route(API_ENDPOINTS['bait_preparation'], methods=['POST'])
def bait_preparation():
    print("\n=== Bait Preparation Request ===")
    try:
        data = request.get_json()
        print(f"Received data: {data}")

        # Validate required fields
        missing_fields = validate_required_fields(data, 'bait_preparation')
        if missing_fields:
            print(f"Missing required fields: {missing_fields}")
            return jsonify({
                "error": ERROR_MESSAGES['missing_fields'].format(', '.join(missing_fields))
            }), 400

        # DB Interaction
        query = f"""
        INSERT INTO {TABLE_NAMES['bait_preparation']} (
            barrel_id, bait_type, ingredients_added, start_date, ready_date, used_in_cage_ids, notes
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        
        params = (
            data['barrelId'], data['baitType'],
            data['ingredientsAdded'], data['startDate'],
            data['readyDate'], data.get('usedInCageIds'),
            data.get('notes')
        )

        print("Executing database query...")
        db.execute_query(query, params)
        return jsonify({
            "status": "success",
            "message": SUCCESS_MESSAGES['bait_preparation']
        }), 201
            
    except Exception as e:
        logger.exception('Error in %s', API_ENDPOINTS['bait_preparation'])
        return jsonify({
            "status": "error",
            "message": ERROR_MESSAGES['server_error'].format('please try again')
        }), 500 