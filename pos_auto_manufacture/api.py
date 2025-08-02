import frappe
from frappe import _
from frappe.utils import flt, now_datetime
from . import pos_auto_manufacture
from . import utils

@frappe.whitelist()
def create_manufacturing_for_pos_invoice(sales_invoice_name):
    """
    API endpoint to manually trigger manufacturing for a POS invoice
    
    Args:
        sales_invoice_name (str): Name of the Sales Invoice
        
    Returns:
        dict: Status and details of manufacturing entries created
    """
    try:
        sales_invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
        
        if not sales_invoice.is_pos:
            return {
                "success": False,
                "message": "This is not a POS invoice"
            }
        
        if sales_invoice.docstatus != 1:
            return {
                "success": False,
                "message": "Sales Invoice must be submitted"
            }
        
        # Trigger manufacturing (this will create entries during validation)
        pos_auto_manufacture.create_manufacture_entry_from_pos(sales_invoice, "before_validate")
        
        # Submit the manufacturing entries
        pos_auto_manufacture.submit_manufacturing_entries(sales_invoice, "on_submit")
        
        # Get created entries
        work_orders = utils.get_related_work_orders(sales_invoice_name)
        stock_entries = utils.get_related_stock_entries(sales_invoice_name)
        
        return {
            "success": True,
            "message": f"Manufacturing entries created for {sales_invoice_name}",
            "work_orders": work_orders,
            "stock_entries": stock_entries
        }
        
    except Exception as e:
        frappe.log_error(f"API Error: {str(e)}")
        return {
            "success": False,
            "message": f"Error creating manufacturing entries: {str(e)}"
        }

@frappe.whitelist()
def handle_pos_return(sales_invoice_name):
    """
    API endpoint to handle POS return
    
    Args:
        sales_invoice_name (str): Name of the Sales Invoice
        
    Returns:
        dict: Status and details of return processing
    """
    try:
        sales_invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
        
        if not sales_invoice.is_pos:
            return {
                "success": False,
                "message": "This is not a POS invoice"
            }
        
        if not sales_invoice.is_return:
            return {
                "success": False,
                "message": "This is not a return invoice"
            }
        
        # Trigger return handling
        pos_auto_manufacture.handle_pos_return_or_cancel(sales_invoice, "on_submit")
        
        return {
            "success": True,
            "message": f"Return processing completed for {sales_invoice_name}"
        }
        
    except Exception as e:
        frappe.log_error(f"API Error: {str(e)}")
        return {
            "success": False,
            "message": f"Error processing return: {str(e)}"
        }

@frappe.whitelist()
def cancel_manufacturing_entries(sales_invoice_name):
    """
    API endpoint to cancel manufacturing entries for a POS invoice
    
    Args:
        sales_invoice_name (str): Name of the Sales Invoice
        
    Returns:
        dict: Status and details of cancellation
    """
    try:
        sales_invoice = frappe.get_doc("Sales Invoice", sales_invoice_name)
        
        if not sales_invoice.is_pos:
            return {
                "success": False,
                "message": "This is not a POS invoice"
            }
        
        # Trigger cancellation handling
        pos_auto_manufacture.handle_pos_return_or_cancel(sales_invoice, "on_cancel")
        
        return {
            "success": True,
            "message": f"Manufacturing entries cancelled for {sales_invoice_name}"
        }
        
    except Exception as e:
        frappe.log_error(f"API Error: {str(e)}")
        return {
            "success": False,
            "message": f"Error cancelling manufacturing entries: {str(e)}"
        }

@frappe.whitelist()
def get_manufacturing_status(sales_invoice_name):
    """
    API endpoint to get manufacturing status for a POS invoice
    
    Args:
        sales_invoice_name (str): Name of the Sales Invoice
        
    Returns:
        dict: Manufacturing status and details
    """
    try:
        work_orders = utils.get_related_work_orders(sales_invoice_name)
        stock_entries = utils.get_related_stock_entries(sales_invoice_name)
        
        status = {
            "sales_invoice": sales_invoice_name,
            "work_orders_count": len(work_orders),
            "stock_entries_count": len(stock_entries),
            "work_orders": work_orders,
            "stock_entries": stock_entries
        }
        
        return {
            "success": True,
            "data": status
        }
        
    except Exception as e:
        frappe.log_error(f"API Error: {str(e)}")
        return {
            "success": False,
            "message": f"Error getting manufacturing status: {str(e)}"
        }

@frappe.whitelist()
def check_stock_availability(item_code, qty, warehouse=None):
    """
    API endpoint to check stock availability for manufacturing
    
    Args:
        item_code (str): Item code to check
        qty (float): Quantity required
        warehouse (str): Warehouse to check (optional)
        
    Returns:
        dict: Stock availability status
    """
    try:
        bom_no = utils.get_item_bom(item_code)
        if not bom_no:
            return {
                "success": False,
                "message": f"No BOM found for item {item_code}"
            }
        
        # Calculate total materials required
        materials_required = utils.calculate_total_materials_required(bom_no, qty)
        
        # Check stock availability
        if warehouse:
            stock_status = utils.check_stock_availability(materials_required, warehouse)
        else:
            # Use default warehouse
            default_warehouse = utils.get_warehouse_for_item(item_code)
            if default_warehouse:
                stock_status = utils.check_stock_availability(materials_required, default_warehouse)
            else:
                return {
                    "success": False,
                    "message": "No warehouse specified and no default warehouse found"
                }
        
        insufficient_materials = utils.get_insufficient_materials(stock_status)
        
        return {
            "success": True,
            "data": {
                "item_code": item_code,
                "required_qty": qty,
                "materials_required": materials_required,
                "stock_status": stock_status,
                "insufficient_materials": insufficient_materials,
                "can_manufacture": len(insufficient_materials) == 0
            }
        }
        
    except Exception as e:
        frappe.log_error(f"API Error: {str(e)}")
        return {
            "success": False,
            "message": f"Error checking stock availability: {str(e)}"
        }

@frappe.whitelist()
def get_nested_bom_structure(item_code, max_depth=5):
    """
    API endpoint to get nested BOM structure for an item
    
    Args:
        item_code (str): Item code
        max_depth (int): Maximum depth to explore (default: 5)
        
    Returns:
        dict: Nested BOM structure
    """
    try:
        bom_no = utils.get_item_bom(item_code)
        if not bom_no:
            return {
                "success": False,
                "message": f"No BOM found for item {item_code}"
            }
        
        bom_structure = utils.get_nested_bom_structure(bom_no, max_depth)
        
        return {
            "success": True,
            "data": {
                "item_code": item_code,
                "bom_no": bom_no,
                "structure": bom_structure
            }
        }
        
    except Exception as e:
        frappe.log_error(f"API Error: {str(e)}")
        return {
            "success": False,
            "message": f"Error getting BOM structure: {str(e)}"
        }

@frappe.whitelist()
def get_manufacturing_settings():
    """
    API endpoint to get current manufacturing settings
    
    Returns:
        dict: Current settings
    """
    try:
        from .utils.settings import get_settings
        
        settings = get_settings()
        
        return {
            "success": True,
            "data": settings
        }
        
    except Exception as e:
        frappe.log_error(f"API Error: {str(e)}")
        return {
            "success": False,
            "message": f"Error getting settings: {str(e)}"
        }

@frappe.whitelist()
def update_manufacturing_settings(settings_dict):
    """
    API endpoint to update manufacturing settings
    
    Args:
        settings_dict (dict): Settings to update
        
    Returns:
        dict: Update status
    """
    try:
        from .utils.settings import get_settings
        
        settings = get_settings()
        if not settings:
            frappe.throw("Settings not found. Please create settings first.")
        
        # Update settings with provided values
        for key, value in settings_dict.items():
            if hasattr(settings, key):
                setattr(settings, key, value)
        
        settings.save()
        
        return {
            "success": True,
            "message": "Settings updated successfully"
        }
        
    except Exception as e:
        frappe.log_error(f"API Error: {str(e)}")
        return {
            "success": False,
            "message": f"Error updating settings: {str(e)}"
        }

@frappe.whitelist()
def get_manufacturing_report(start_date=None, end_date=None, item_code=None):
    """
    Get manufacturing report for the specified period
    
    Args:
        start_date (str): Start date for the report
        end_date (str): End date for the report
        item_code (str): Filter by specific item
        
    Returns:
        dict: Manufacturing report data
    """
    try:
        filters = {}
        
        if start_date and end_date:
            filters["posting_date"] = ["between", [start_date, end_date]]
        
        if item_code:
            filters["production_item"] = item_code
        
        work_orders = frappe.db.get_all(
            "Work Order",
            filters=filters,
            fields=["name", "production_item", "qty", "status", "posting_date"]
        )
        
        return {
            "success": True,
            "work_orders": work_orders
        }
        
    except Exception as e:
        frappe.log_error(f"API Error: {str(e)}")
        return {
            "success": False,
            "message": f"Error generating report: {str(e)}"
        }

@frappe.whitelist()
def check_bom_stock_levels(item_code, qty, warehouse=None):
    """
    Check stock levels for BOM items
    
    Args:
        item_code (str): Item code to check
        qty (float): Quantity to manufacture
        warehouse (str): Warehouse to check stock in
        
    Returns:
        list: List of items with low stock
    """
    try:
        # Get the BOM for the item
        bom_no = frappe.db.get_value("Item", item_code, "default_bom")
        if not bom_no:
            return []
        
        # Get BOM items
        bom_items = frappe.db.get_all(
            "BOM Item",
            filters={"parent": bom_no},
            fields=["item_code", "qty", "uom"]
        )
        
        low_stock_items = []
        
        for item in bom_items:
            required_qty = flt(item.qty) * flt(qty)
            
            # Get available stock
            if warehouse:
                available_qty = flt(frappe.db.get_value(
                    "Bin",
                    {"item_code": item.item_code, "warehouse": warehouse},
                    "actual_qty"
                ) or 0)
            else:
                # Get total stock across all warehouses
                available_qty = flt(frappe.db.get_value(
                    "Bin",
                    {"item_code": item.item_code},
                    "sum(actual_qty)"
                ) or 0)
            
            # Check if stock is insufficient
            if available_qty < required_qty:
                item_name = frappe.db.get_value("Item", item.item_code, "item_name")
                low_stock_items.append({
                    "item_code": item.item_code,
                    "item_name": item_name,
                    "required": required_qty,
                    "available": available_qty,
                    "uom": item.uom,
                    "shortage": required_qty - available_qty
                })
        
        return low_stock_items
        
    except Exception as e:
        frappe.log_error(f"Stock Check Error: {str(e)}")
        return [] 