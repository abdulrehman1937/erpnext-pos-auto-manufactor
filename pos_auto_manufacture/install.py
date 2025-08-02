import frappe
import json
import os

def after_install():
    """Create POS Auto Manufacture Settings DocType after app installation"""
    print("Running after_install hook for pos_auto_manufacture...")
    
    # Step 1: Create custom fields
    create_custom_fields()
    
    # Step 2: Create settings DocType and document
    create_pos_auto_manufacture_settings()
    
    print("After_install hook completed successfully")

def create_custom_fields():
    """Create custom fields for Sales Invoice"""
    try:
        print("Creating custom fields for Sales Invoice...")
        
        # Define custom fields
        custom_fields = [
            {
                "fieldname": "manufacturing_return_option",
                "label": "Manufacturing Return Option",
                "fieldtype": "Select",
                "options": "Create Return Stock Entry\nReverse Manufacturing Entry\nBoth",
                "default": "Create Return Stock Entry",
                "insert_after": "is_internal_customer"
            },
            {
                "fieldname": "check_stock_before_manufacturing",
                "label": "Check Stock Before Manufacturing",
                "fieldtype": "Check",
                "default": "1",
                "insert_after": "manufacturing_return_option"
            },
            {
                "fieldname": "create_nested_work_orders",
                "label": "Create Nested Work Orders",
                "fieldtype": "Check",
                "default": "0",
                "insert_after": "check_stock_before_manufacturing"
            },
            {
                "fieldname": "track_manufacturing_wastage",
                "label": "Track Manufacturing Wastage",
                "fieldtype": "Check",
                "default": "1",
                "insert_after": "create_nested_work_orders"
            },
            {
                "fieldname": "wastage_percentage",
                "label": "Wastage Percentage",
                "fieldtype": "Percent",
                "default": "5.0",
                "depends_on": "eval:doc.track_manufacturing_wastage",
                "insert_after": "track_manufacturing_wastage"
            },
            {
                "fieldname": "handle_wastage_on_return",
                "label": "Handle Wastage on Return",
                "fieldtype": "Check",
                "default": "1",
                "depends_on": "eval:doc.track_manufacturing_wastage",
                "insert_after": "wastage_percentage"
            },
            {
                "fieldname": "handle_wastage_on_cancel",
                "label": "Handle Wastage on Cancel",
                "fieldtype": "Check",
                "default": "1",
                "depends_on": "eval:doc.track_manufacturing_wastage",
                "insert_after": "handle_wastage_on_return"
            }
        ]
        
        for field_data in custom_fields:
            field_name = f"Sales Invoice-{field_data['fieldname']}"
            
            # Check if custom field already exists
            if not frappe.db.exists("Custom Field", field_name):
                custom_field = frappe.get_doc({
                    "doctype": "Custom Field",
                    "dt": "Sales Invoice",
                    "fieldname": field_data["fieldname"],
                    "label": field_data["label"],
                    "fieldtype": field_data["fieldtype"],
                    "default": field_data["default"],
                    "insert_after": field_data["insert_after"]
                })
                
                # Add optional properties
                if "options" in field_data:
                    custom_field.options = field_data["options"]
                if "depends_on" in field_data:
                    custom_field.depends_on = field_data["depends_on"]
                
                custom_field.insert()
                print(f"Created custom field: {field_name}")
            else:
                print(f"Custom field already exists: {field_name}")
        
        frappe.db.commit()
        print("Custom fields created successfully")
        
    except Exception as e:
        frappe.log_error(f"Error creating custom fields: {str(e)}")
        print(f"Failed to create custom fields: {str(e)}")

def before_uninstall():
    """Remove POS Auto Manufacture Settings DocType before app uninstallation"""
    print("Starting POS Auto Manufacture uninstall process...")
    
    # Step 1: Remove custom fields first
    remove_custom_fields()
    
    # Step 2: Remove settings documents and DocType
    remove_pos_auto_manufacture_settings()
    
    print("POS Auto Manufacture uninstall process completed")

def remove_custom_fields():
    """Remove custom fields created by this app"""
    try:
        print("Removing custom fields...")
        
        # List of custom fields to remove
        custom_fields = [
            "Sales Invoice-manufacturing_return_option",
            "Sales Invoice-check_stock_before_manufacturing", 
            "Sales Invoice-create_nested_work_orders",
            "Sales Invoice-track_manufacturing_wastage",
            "Sales Invoice-wastage_percentage",
            "Sales Invoice-handle_wastage_on_return",
            "Sales Invoice-handle_wastage_on_cancel"
        ]
        
        for field_name in custom_fields:
            try:
                if frappe.db.exists("Custom Field", field_name):
                    frappe.delete_doc("Custom Field", field_name, force=True)
                    print(f"Deleted custom field: {field_name}")
                else:
                    print(f"Custom field not found: {field_name}")
            except Exception as e:
                print(f"Error deleting custom field {field_name}: {str(e)}")
                
    except Exception as e:
        frappe.log_error(f"Error removing custom fields: {str(e)}")
        print(f"Failed to remove custom fields: {str(e)}")

def create_pos_auto_manufacture_settings():
    """Create the POS Auto Manufacture Settings DocType and default settings"""
    try:
        # Check if DocType already exists
        if frappe.db.exists("DocType", "POS Auto Manufacture Settings"):
            print("POS Auto Manufacture Settings DocType already exists")
        else:
            # Create the DocType using frappe.get_doc
            doc = frappe.get_doc({
                "doctype": "DocType",
                "name": "POS Auto Manufacture Settings",
                "module": "POS Auto Manufacture",
                "custom": 1,
                "issingle": 1,
                "istable": 0,
                "is_submittable": 0,
                "allow_rename": 1,
                "editable_grid": 1,
                "track_changes": 1,
                "track_seen": 1,
                "track_views": 1,
                "default_view": "Form",
                "engine": "InnoDB",
                "field_order": [
                    "general_settings_section",
                    "enable_auto_manufacturing",
                    "check_stock_before_manufacturing",
                    "create_nested_work_orders",
                    "manufacturing_settings_section",
                    "track_manufacturing_wastage",
                    "wastage_percentage",
                    "handle_wastage_on_return",
                    "handle_wastage_on_cancel",
                    "return_settings_section",
                    "manufacturing_return_option"
                ],
                "fields": [
                    {
                        "fieldname": "general_settings_section",
                        "fieldtype": "Section Break",
                        "label": "General Settings"
                    },
                    {
                        "default": "1",
                        "description": "Enable automatic manufacturing when POS orders are submitted",
                        "fieldname": "enable_auto_manufacturing",
                        "fieldtype": "Check",
                        "label": "Enable Auto Manufacturing"
                    },
                    {
                        "default": "1",
                        "description": "Check stock availability before creating manufacturing orders",
                        "fieldname": "check_stock_before_manufacturing",
                        "fieldtype": "Check",
                        "label": "Check Stock Before Manufacturing"
                    },
                    {
                        "default": "0",
                        "description": "Create nested work orders for complex BOM structures",
                        "fieldname": "create_nested_work_orders",
                        "fieldtype": "Check",
                        "label": "Create Nested Work Orders"
                    },
                    {
                        "fieldname": "manufacturing_settings_section",
                        "fieldtype": "Section Break",
                        "label": "Manufacturing Settings"
                    },
                    {
                        "default": "1",
                        "description": "Track manufacturing wastage in stock entries",
                        "fieldname": "track_manufacturing_wastage",
                        "fieldtype": "Check",
                        "label": "Track Manufacturing Wastage"
                    },
                    {
                        "default": "5.0",
                        "description": "Default wastage percentage for manufacturing",
                        "fieldname": "wastage_percentage",
                        "fieldtype": "Percent",
                        "label": "Wastage Percentage",
                        "depends_on": "eval:doc.track_manufacturing_wastage"
                    },
                    {
                        "default": "1",
                        "description": "Handle wastage when processing returns",
                        "fieldname": "handle_wastage_on_return",
                        "fieldtype": "Check",
                        "label": "Handle Wastage on Return",
                        "depends_on": "eval:doc.track_manufacturing_wastage"
                    },
                    {
                        "default": "1",
                        "description": "Handle wastage when canceling orders",
                        "fieldname": "handle_wastage_on_cancel",
                        "fieldtype": "Check",
                        "label": "Handle Wastage on Cancel",
                        "depends_on": "eval:doc.track_manufacturing_wastage"
                    },
                    {
                        "fieldname": "return_settings_section",
                        "fieldtype": "Section Break",
                        "label": "Return Settings"
                    },
                    {
                        "default": "Create Return Stock Entry",
                        "fieldname": "manufacturing_return_option",
                        "fieldtype": "Select",
                        "label": "Manufacturing Return Option",
                        "options": "Create Return Stock Entry\nReverse Manufacturing Entry\nBoth"
                    }
                ],
                "permissions": [
                    {
                        "create": 1,
                        "delete": 1,
                        "email": 1,
                        "export": 1,
                        "print": 1,
                        "read": 1,
                        "report": 1,
                        "role": "System Manager",
                        "share": 1,
                        "write": 1
                    }
                ]
            })
            doc.insert()
            frappe.db.commit()
            print("POS Auto Manufacture Settings DocType created successfully")
        
        # Create default settings document if it doesn't exist
        try:
            # Try to get the settings document
            settings_doc = frappe.get_doc("POS Auto Manufacture Settings", "POS Auto Manufacture Settings")
            print("Default POS Auto Manufacture Settings document already exists")
        except frappe.DoesNotExistError:
            print("Creating default POS Auto Manufacture Settings document...")
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
                "manufacturing_return_option": "Create Return Stock Entry"
            })
            settings_doc.insert()
            frappe.db.commit()
            print("Default POS Auto Manufacture Settings document created successfully")
            
            # Verify the document was created successfully
            try:
                frappe.get_doc("POS Auto Manufacture Settings", "POS Auto Manufacture Settings")
                print("Verified: Default POS Auto Manufacture Settings document saved successfully")
            except Exception as e:
                print(f"Warning: Could not verify settings document creation: {str(e)}")
        
    except Exception as e:
        frappe.log_error(f"Error creating POS Auto Manufacture Settings DocType: {str(e)}")
        print(f"Failed to create POS Auto Manufacture Settings DocType: {str(e)}")
        # Don't throw here to avoid breaking the installation

def remove_pos_auto_manufacture_settings():
    """Remove the POS Auto Manufacture Settings DocType and all related documents"""
    try:
        print("Removing POS Auto Manufacture Settings...")
        
        # Step 1: Remove all settings documents first
        print("Step 1: Removing all settings documents...")
        try:
            settings_docs = frappe.get_all("POS Auto Manufacture Settings")
            for doc in settings_docs:
                try:
                    frappe.delete_doc("POS Auto Manufacture Settings", doc.name, force=True)
                    print(f"Deleted settings document: {doc.name}")
                except Exception as e:
                    print(f"Error deleting settings document {doc.name}: {str(e)}")
        except Exception as e:
            print(f"Error accessing settings documents: {str(e)}")
        
        # Step 2: Remove the DocType itself
        print("Step 2: Removing DocType...")
        try:
            if frappe.db.exists("DocType", "POS Auto Manufacture Settings"):
                frappe.delete_doc("DocType", "POS Auto Manufacture Settings", force=True)
                frappe.db.commit()
                print("POS Auto Manufacture Settings DocType and all documents removed successfully")
            else:
                print("POS Auto Manufacture Settings DocType not found")
        except Exception as e:
            print(f"Error removing DocType: {str(e)}")
            
    except Exception as e:
        frappe.log_error(f"Error removing POS Auto Manufacture Settings DocType: {str(e)}")
        print(f"Failed to remove POS Auto Manufacture Settings DocType: {str(e)}")
        # Don't throw here to avoid breaking the uninstallation 