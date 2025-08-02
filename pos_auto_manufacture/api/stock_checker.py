import frappe
from frappe import _
from frappe.utils import flt


@frappe.whitelist()
def check_bom_stock_levels(item_code, qty, warehouse=None):
    """
    Check BOM stock levels for an item and return low stock warnings
    
    Args:
        item_code (str): Item code to check
        qty (float/str): Quantity required
        warehouse (str): Warehouse to check (optional)
        
    Returns:
        list: List of items with low stock (only basic raw materials)
    """
    try:
        # Convert qty to float
        qty = flt(qty)
        if qty <= 0:
            return []
        
        # Validate item exists
        if not frappe.db.exists("Item", item_code):
            return []
        
        # Get the BOM for the item
        bom_no = frappe.db.get_value("Item", item_code, "default_bom")
        if not bom_no:
            return []
        
        # Get source warehouse from settings if not specified
        if not warehouse:
            warehouse = get_source_warehouse_from_settings()
            if not warehouse:
                return []
        
        # Calculate total materials required with recursive optimization
        materials_required = calculate_optimized_materials_required(bom_no, qty, warehouse)
        if not materials_required:
            return []
        
        # Check stock availability
        stock_status = check_stock_availability(materials_required, warehouse)
        insufficient_materials = get_insufficient_materials(stock_status)
        
        # Format the response for the frontend
        return format_low_stock_response(insufficient_materials)
        
    except Exception as e:
        frappe.log_error(f"Stock checker error for item {item_code}: {str(e)}")
        return []


def get_source_warehouse_from_settings():
    """Get source warehouse from POS Auto Manufacture Settings"""
    try:
        from ..utils.settings import get_source_warehouse
        return get_source_warehouse()
    except ImportError:
        # Fallback to default warehouse logic
        return get_default_warehouse()


def get_default_warehouse(item_code=None):
    """Get appropriate warehouse for an item"""
    # Try to get from item's default warehouse
    if item_code:
        item_warehouse = frappe.db.get_value("Item", item_code, "default_warehouse")
        if item_warehouse:
            return item_warehouse
    
    # Get from company's default warehouse
    company = frappe.defaults.get_global_default("company")
    if company:
        company_warehouse = frappe.db.get_value("Company", company, "default_warehouse")
        if company_warehouse:
            return company_warehouse
    
    return None


def calculate_optimized_materials_required(bom_no, qty, warehouse, max_depth=5, current_depth=0):
    """
    Calculate total materials required with recursive optimization
    Only includes basic raw materials, excludes intermediate products that can be manufactured
    
    Args:
        bom_no (str): BOM number
        qty (float): Quantity to manufacture
        warehouse (str): Warehouse to check stock
        max_depth (int): Maximum recursion depth
        current_depth (int): Current recursion depth
        
    Returns:
        dict: Dictionary with item_code as key and required quantity as value (only basic materials)
    """
    if current_depth >= max_depth:
        return {}
    
    try:
        # Get BOM items
        bom_items = frappe.db.get_all(
            "BOM Item",
            filters={"parent": bom_no},
            fields=["item_code", "qty"]
        )
        
        if not bom_items:
            return {}
        
        materials_required = {}
        
        for item in bom_items:
            item_code = item["item_code"]
            required_qty = flt(item["qty"]) * qty
            
            # Check current stock of this item in source warehouse
            current_stock = get_item_stock_in_source_warehouse(item_code, warehouse)
            
            # Check if this item is a manufacturing item
            nested_bom = frappe.db.get_value("Item", item_code, "default_bom")
            
            if nested_bom and current_stock < required_qty:
                # This is a manufacturing item with insufficient stock
                # Calculate how much more we need to manufacture
                additional_needed = required_qty - current_stock
                
                # Recursively get materials needed for the additional quantity
                nested_materials = calculate_optimized_materials_required(
                    nested_bom, additional_needed, warehouse, max_depth, current_depth + 1
                )
                
                # Add nested materials to our requirements
                for nested_item_code, nested_qty in nested_materials.items():
                    if nested_item_code in materials_required:
                        materials_required[nested_item_code] += nested_qty
                    else:
                        materials_required[nested_item_code] = nested_qty
                        
            elif not nested_bom:
                # This is a basic raw material, add to requirements
                if item_code in materials_required:
                    materials_required[item_code] += required_qty
                else:
                    materials_required[item_code] = required_qty
        
        return materials_required
        
    except Exception as e:
        frappe.log_error(f"Error calculating optimized materials for BOM {bom_no}: {str(e)}")
        return {}


def get_item_stock_in_source_warehouse(item_code, warehouse):
    """
    Get current stock of an item in the source warehouse
    
    Args:
        item_code (str): Item code
        warehouse (str): Source warehouse
        
    Returns:
        float: Available quantity
    """
    # Use source warehouse from settings if available
    source_warehouse = get_source_warehouse_from_settings()
    if source_warehouse:
        warehouse = source_warehouse
    
    return flt(frappe.db.get_value(
        "Bin",
        {"item_code": item_code, "warehouse": warehouse},
        "actual_qty"
    ) or 0)


def check_stock_availability(materials_required, warehouse):
    """
    Check if required materials are available in stock
    
    Args:
        materials_required (dict): Dictionary with item_code as key and required quantity as value
        warehouse (str): Warehouse to check
        
    Returns:
        dict: Stock status for each item
    """
    if not materials_required:
        return {}
    
    # Get all item codes
    item_codes = list(materials_required.keys())
    
    # Use source warehouse from settings
    source_warehouse = get_source_warehouse_from_settings()
    if source_warehouse:
        warehouse = source_warehouse
    
    # Batch query for stock levels
    stock_data = frappe.db.get_all(
        "Bin",
        filters={
            "item_code": ["in", item_codes],
            "warehouse": warehouse
        },
        fields=["item_code", "actual_qty"]
    )
    
    # Create lookup dictionary
    stock_lookup = {item["item_code"]: flt(item["actual_qty"]) for item in stock_data}
    
    stock_status = {}
    for item_code, required_qty in materials_required.items():
        available_qty = stock_lookup.get(item_code, 0)
        
        stock_status[item_code] = {
            "required": required_qty,
            "available": available_qty,
            "shortage": max(0, required_qty - available_qty),
            "sufficient": available_qty >= required_qty
        }
    
    return stock_status


def get_insufficient_materials(stock_status):
    """
    Get list of materials with insufficient stock
    
    Args:
        stock_status (dict): Stock status dictionary
        
    Returns:
        list: List of insufficient materials
    """
    insufficient = []
    
    for item_code, status in stock_status.items():
        if not status["sufficient"]:
            insufficient.append({
                "item_code": item_code,
                "required": status["required"],
                "available": status["available"],
                "shortage": status["shortage"]
            })
    
    return insufficient


def format_low_stock_response(insufficient_materials):
    """
    Format the response for the frontend
    
    Args:
        insufficient_materials (list): List of insufficient materials
        
    Returns:
        list: Formatted response for frontend
    """
    if not insufficient_materials:
        return []
    
    # Get all item codes for batch query
    item_codes = [item["item_code"] for item in insufficient_materials]
    
    # Batch query for item details
    item_details = frappe.db.get_all(
        "Item",
        filters={"name": ["in", item_codes]},
        fields=["name", "item_name", "stock_uom"]
    )
    
    # Create lookup dictionary
    item_lookup = {item["name"]: item for item in item_details}
    
    low_stock_items = []
    for material in insufficient_materials:
        item_code = material["item_code"]
        item_detail = item_lookup.get(item_code, {})
        
        low_stock_items.append({
            "item_code": item_code,
            "item_name": item_detail.get("item_name", item_code),
            "required": material["required"],
            "available": material["available"],
            "shortage": material["shortage"],
            "uom": item_detail.get("stock_uom", "")
        })
    
    return low_stock_items