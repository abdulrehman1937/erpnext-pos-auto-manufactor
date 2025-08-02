# Copyright (c) 2024, XEuroTech and contributors
# For license information, please see license.txt

import frappe
from frappe import _


def get_settings():
    """Get POS Auto Manufacture Settings"""
    return frappe.get_single("POS Auto Manufacture Settings")


def ensure_settings_exist():
    """Ensure settings exist, create if they don't"""
    try:
        settings = get_settings()
        return settings
    except frappe.DoesNotExistError:
        # Create default settings
        settings_doc = frappe.get_doc({
            "doctype": "POS Auto Manufacture Settings",
            "name": "POS Auto Manufacture Settings",
            "enable_auto_manufacturing": 1,
            "check_stock_before_manufacturing": 1,
            "create_nested_work_orders": 0,
            "track_manufacturing_wastage": 1,
            "wastage_percentage": 5.0,
            "handle_wastage_on_return": 1,
            "handle_wastage_on_cancel": 1,
            "manufacturing_return_option": "Create Return Stock Entry",
            "source_warehouse": "",
            "target_warehouse": ""
        })
        settings_doc.insert()
        frappe.db.commit()
        return settings_doc


def is_auto_manufacturing_enabled():
    """Check if auto manufacturing is enabled"""
    try:
        settings = get_settings()
        return settings.enable_auto_manufacturing if settings else False
    except:
        return False


def should_check_stock_before_manufacturing():
    """Check if stock should be verified before manufacturing"""
    try:
        settings = get_settings()
        return settings.check_stock_before_manufacturing if settings else True
    except:
        return True


def should_create_nested_work_orders():
    """Check if nested work orders should be created"""
    try:
        settings = get_settings()
        return settings.create_nested_work_orders if settings else False
    except:
        return False


def should_track_manufacturing_wastage():
    """Check if manufacturing wastage should be tracked"""
    try:
        settings = get_settings()
        return settings.track_manufacturing_wastage if settings else True
    except:
        return True


def get_wastage_percentage():
    """Get the wastage percentage setting"""
    try:
        settings = get_settings()
        return settings.wastage_percentage if settings else 5.0
    except:
        return 5.0


def should_handle_wastage_on_return():
    """Check if wastage should be handled on returns"""
    try:
        settings = get_settings()
        return settings.handle_wastage_on_return if settings else True
    except:
        return True


def should_handle_wastage_on_cancel():
    """Check if wastage should be handled on cancellations"""
    try:
        settings = get_settings()
        return settings.handle_wastage_on_cancel if settings else True
    except:
        return True


def get_manufacturing_return_option():
    """Get the manufacturing return option"""
    try:
        settings = get_settings()
        return settings.manufacturing_return_option if settings else "Create Return Stock Entry"
    except:
        return "Create Return Stock Entry"


def get_source_warehouse():
    """Get the source warehouse setting for raw materials"""
    try:
        settings = get_settings()
        return settings.source_warehouse if settings else ""
    except:
        return ""


def get_target_warehouse():
    """Get the target warehouse setting for finished products"""
    try:
        settings = get_settings()
        return settings.target_warehouse if settings else ""
    except:
        return ""


def validate_settings():
    """Validate that settings exist and are properly configured"""
    try:
        settings = get_settings()
        if not settings:
            frappe.throw(_("POS Auto Manufacture Settings not found. Please create settings first."))
        return settings
    except Exception as e:
        frappe.throw(_("Error accessing POS Auto Manufacture Settings: {0}").format(str(e))) 