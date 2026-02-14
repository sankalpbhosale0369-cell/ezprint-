"""
Shop Configuration API endpoints
"""
from flask import Blueprint, request
import sys
import os
import logging

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shared.database import SessionLocal, Shopkeeper, ShopPricing, Printer
from utils.response_builder import success_response, error_response
from api.middleware import require_auth

# Setup logging
logger = logging.getLogger(__name__)

config_bp = Blueprint('config_api', __name__, url_prefix='/api/shop')

@config_bp.route('/<shop_id>/config', methods=['GET'])
@require_auth
def get_config(shop_id):
    """
    GET /api/shop/<shop_id>/config
    
    Returns:
        {
            "success": true,
            "data": {
                "shop_info": {
                    "shop_id": "uuid",
                    "shop_name": "string",
                    "shop_address": "string|null",
                    "contact_number": "string|null",
                    "shopkeeper_name": "string|null",
                    "email": "string",
                    "qr_code_path": "string"
                },
                "pricing": {
                    "bw_single": 2.0,
                    "bw_double": 1.5,
                    "color_single": 10.0,
                    "color_double": 8.0
                },
                "printers": [
                    {
                        "printer_id": "string",
                        "printer_name": "string",
                        "is_default": true,
                        "is_active": true
                    }
                ]
            }
        }
    """
    try:
        # Validate shop_id matches authenticated user
        if shop_id != request.shop_id:
            logger.warning(f"Unauthorized config access attempt: {request.shop_id} tried to access {shop_id}")
            return error_response("Unauthorized access to shop data", 403)
        
        # Database queries
        db = SessionLocal()
        try:
            # Fetch shop info
            shopkeeper = db.query(Shopkeeper).filter(
                Shopkeeper.shop_id == shop_id
            ).first()
            
            if not shopkeeper:
                return error_response("Shop not found", 404)
            
            shop_info = {
                'shop_id': shopkeeper.shop_id,
                'shop_name': shopkeeper.shop_name,
                'shop_address': shopkeeper.shop_address,
                'contact_number': shopkeeper.contact_number,
                'shopkeeper_name': shopkeeper.shopkeeper_name,
                'email': shopkeeper.email,
                'qr_code_path': shopkeeper.qr_code_path
            }
            
            # Fetch pricing
            pricing_config = db.query(ShopPricing).filter(
                ShopPricing.shop_id == shop_id
            ).first()
            
            if pricing_config:
                pricing = {
                    'bw_single': float(pricing_config.bw_single),
                    'bw_double': float(pricing_config.bw_double),
                    'color_single': float(pricing_config.color_single),
                    'color_double': float(pricing_config.color_double)
                }
            else:
                # Default pricing if not set
                pricing = {
                    'bw_single': 2.0,
                    'bw_double': 1.5,
                    'color_single': 10.0,
                    'color_double': 8.0
                }
            
            # Fetch printers
            printers_list = db.query(Printer).filter(
                Printer.shop_id == shop_id,
                Printer.is_active == True
            ).all()
            
            printers = []
            for printer in printers_list:
                printers.append({
                    'printer_id': printer.printer_id,
                    'printer_name': printer.printer_name,
                    'is_default': printer.is_default,
                    'is_active': printer.is_active
                })
            
            response_data = {
                "shop_info": shop_info,
                "pricing": pricing,
                "printers": printers
            }
            
            logger.info(f"Config data fetched for shop_id: {shop_id}")
            return success_response(response_data, "Configuration fetched successfully", 200)
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Config fetch error: {str(e)}", exc_info=True)
        return error_response(f"Failed to fetch configuration: {str(e)}", 500)

@config_bp.route('/<shop_id>/pricing', methods=['GET'])
@require_auth
def get_pricing(shop_id):
    """
    GET /api/shop/<shop_id>/pricing
    
    Returns:
        {
            "success": true,
            "data": {
                "shop_id": "uuid",
                "bw_single": 2.0,
                "bw_double": 1.5,
                "color_single": 10.0,
                "color_double": 8.0
            }
        }
    """
    try:
        # Validate shop_id matches authenticated user
        if shop_id != request.shop_id:
            logger.warning(f"Unauthorized pricing access attempt: {request.shop_id} tried to access {shop_id}")
            return error_response("Unauthorized access to shop data", 403)
        
        # Database query
        db = SessionLocal()
        try:
            pricing_config = db.query(ShopPricing).filter(
                ShopPricing.shop_id == shop_id
            ).first()
            
            if pricing_config:
                response_data = {
                    'shop_id': pricing_config.shop_id,
                    'bw_single': float(pricing_config.bw_single),
                    'bw_double': float(pricing_config.bw_double),
                    'color_single': float(pricing_config.color_single),
                    'color_double': float(pricing_config.color_double)
                }
            else:
                # Return default pricing if not set
                response_data = {
                    'shop_id': shop_id,
                    'bw_single': 2.0,
                    'bw_double': 1.5,
                    'color_single': 10.0,
                    'color_double': 8.0
                }
            
            logger.info(f"Pricing data fetched for shop_id: {shop_id}")
            return success_response(response_data, "Pricing fetched successfully", 200)
            
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Pricing fetch error: {str(e)}", exc_info=True)
        return error_response(f"Failed to fetch pricing: {str(e)}", 500)

@config_bp.route('/<shop_id>/pricing', methods=['PUT'])
@require_auth
def update_pricing(shop_id):
    """
    PUT /api/shop/<shop_id>/pricing
    
    Request:
        {
            "bw_single": 2.0,
            "bw_double": 1.5,
            "color_single": 10.0,
            "color_double": 8.0
        }
    
    Response:
        {
            "success": true,
            "message": "Pricing updated successfully",
            "data": {
                "shop_id": "uuid",
                "bw_single": 2.0,
                "bw_double": 1.5,
                "color_single": 10.0,
                "color_double": 8.0
            }
        }
    """
    try:
        # Validate shop_id matches authenticated user
        if shop_id != request.shop_id:
            logger.warning(f"Unauthorized pricing update attempt: {request.shop_id} tried to update {shop_id}")
            return error_response("Unauthorized access to shop data", 403)
        
        data = request.get_json()
        
        # Validate request
        if not data:
            return error_response("Missing request body", 400)
        
        # Database update
        db = SessionLocal()
        try:
            pricing_config = db.query(ShopPricing).filter(
                ShopPricing.shop_id == shop_id
            ).first()
            
            if not pricing_config:
                # Create new pricing config
                pricing_config = ShopPricing(
                    shop_id=shop_id,
                    bw_single=data.get('bw_single', 2.0),
                    bw_double=data.get('bw_double', 1.5),
                    color_single=data.get('color_single', 10.0),
                    color_double=data.get('color_double', 8.0)
                )
                db.add(pricing_config)
            else:
                # Update existing pricing
                if 'bw_single' in data:
                    pricing_config.bw_single = data['bw_single']
                if 'bw_double' in data:
                    pricing_config.bw_double = data['bw_double']
                if 'color_single' in data:
                    pricing_config.color_single = data['color_single']
                if 'color_double' in data:
                    pricing_config.color_double = data['color_double']
            
            db.commit()
            
            response_data = {
                'shop_id': pricing_config.shop_id,
                'bw_single': float(pricing_config.bw_single),
                'bw_double': float(pricing_config.bw_double),
                'color_single': float(pricing_config.color_single),
                'color_double': float(pricing_config.color_double)
            }
            
            logger.info(f"Pricing updated for shop_id: {shop_id}")
            return success_response(response_data, "Pricing updated successfully", 200)
            
        except Exception as e:
            db.rollback()
            raise e
        finally:
            db.close()
            
    except Exception as e:
        logger.error(f"Pricing update error: {str(e)}", exc_info=True)
        return error_response(f"Failed to update pricing: {str(e)}", 500)
