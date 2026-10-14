from flask import Blueprint, request, jsonify
from backend.database import DatabaseConnection
import json
import logging
from datetime import datetime

waste_management = Blueprint('waste_management', __name__)
db = DatabaseConnection()

@waste_management.route('/api/waste-sourcing', methods=['GET'])
def get_waste_sourcing():
    try:
        query = "SELECT * FROM waste_sourcing ORDER BY collection_date DESC"
        result = db.fetch_all(query)
        return jsonify(list(result)), 200
    except Exception as e:
        logging.getLogger(__name__).exception('Request failed')
        return jsonify({'error': 'An internal error occurred.'}), 500

@waste_management.route('/api/storage-records', methods=['GET'])
def get_storage_records():
    try:
        query = "SELECT * FROM storage_records ORDER BY storage_date DESC"
        result = db.fetch_all(query)
        return jsonify(list(result)), 200
    except Exception as e:
        logging.getLogger(__name__).exception('Request failed')
        return jsonify({'error': 'An internal error occurred.'}), 500

@waste_management.route('/api/processing-records', methods=['GET'])
def get_processing_records():
    try:
        query = "SELECT * FROM processing_records ORDER BY processing_date DESC"
        result = db.fetch_all(query)
        return jsonify(list(result)), 200
    except Exception as e:
        logging.getLogger(__name__).exception('Request failed')
        return jsonify({'error': 'An internal error occurred.'}), 500

@waste_management.route('/api/environmental-monitoring', methods=['GET'])
def get_environmental_monitoring():
    try:
        query = "SELECT * FROM waste_monitoring ORDER BY monitoring_date DESC"
        result = db.fetch_all(query)
        return jsonify(list(result)), 200
    except Exception as e:
        logging.getLogger(__name__).exception('Request failed')
        return jsonify({'error': 'An internal error occurred.'}), 500
