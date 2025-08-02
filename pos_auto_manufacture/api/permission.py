import frappe

def has_app_permission():
    """Check if user has permission to access the POS Auto Manufacture app"""
    # For now, allow all users with basic permissions
    # You can customize this based on your requirements
    return frappe.has_permission("Sales Invoice", "read") 