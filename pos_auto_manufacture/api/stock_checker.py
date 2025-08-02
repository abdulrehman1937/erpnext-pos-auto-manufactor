import frappe
from frappe import _
from frappe.utils import flt

@frappe.whitelist()
def check_bom_stock_levels(item_code, qty, warehouse=None):
    """
    Check BOM stock levels for an item and return low stock warnings
    
    Args:
        item_code (str): Item code to check
        qty (float): Quantity required
        warehouse (str): Warehouse to check (optional)
        
    Returns:
        list: List of items with low stock
    """
    try:
        # Get the BOM for the item
        bom_no = frappe.db.get_value("Item", item_code, "default_bom")
        if not bom_no:
            return []
        
        # Calculate total materials required
        materials_required = calculate_total_materials_required(bom_no, qty)
        
        # Get default warehouse if not specified
        if not warehouse:
            warehouse = get_warehouse_for_item(item_code)
            if not warehouse:
                return []
        
        # Check stock availability
        stock_status = check_stock_availability(materials_required, warehouse)
        insufficient_materials = get_insufficient_materials(stock_status)
        
        # Format the response for the frontend
        low_stock_items = []
        for material in insufficient_materials:
            item_doc = frappe.get_doc("Item", material["item_code"])
            low_stock_items.append({
                "item_code": material["item_code"],
                "item_name": item_doc.item_name,
                "required": material["required"],
                "available": material["available"],
                "shortage": material["shortage"],
                "uom": item_doc.stock_uom
            })
        
        return low_stock_items
        
    except Exception as e:
        frappe.log_error(f"Stock checker error: {str(e)}")
        return []

@frappe.whitelist()
def get_manufacturing_summary(item_code, qty, warehouse=None):
    """
    Get a summary of manufacturing requirements for an item
    
    Args:
        item_code (str): Item code to check
        qty (float): Quantity required
        warehouse (str): Warehouse to check (optional)
        
    Returns:
        dict: Manufacturing summary
    """
    try:
        # Get the BOM for the item
        bom_no = frappe.db.get_value("Item", item_code, "default_bom")
        if not bom_no:
            return {
                "can_manufacture": False,
                "message": "No BOM found for this item"
            }
        
        # Calculate total materials required
        materials_required = calculate_total_materials_required(bom_no, qty)
        
        # Get default warehouse if not specified
        if not warehouse:
            warehouse = get_warehouse_for_item(item_code)
            if not warehouse:
                return {
                    "can_manufacture": False,
                    "message": "No warehouse specified"
                }
        
        # Check stock availability
        stock_status = check_stock_availability(materials_required, warehouse)
        insufficient_materials = get_insufficient_materials(stock_status)
        
        # Calculate summary
        total_materials = len(materials_required)
        insufficient_count = len(insufficient_materials)
        sufficient_count = total_materials - insufficient_count
        
        return {
            "can_manufacture": True,
            "total_materials": total_materials,
            "sufficient_materials": sufficient_count,
            "insufficient_materials": insufficient_count,
            "materials_required": materials_required,
            "stock_status": stock_status,
            "insufficient_items": insufficient_materials
        }
        
    except Exception as e:
        frappe.log_error(f"Manufacturing summary error: {str(e)}")
        return {
            "can_manufacture": False,
            "message": f"Error calculating manufacturing requirements: {str(e)}"
        }

def get_warehouse_for_item(item_code, default_warehouse=None):
    """Get appropriate warehouse for an item"""
    if default_warehouse:
        return default_warehouse
    
    # Try to get from item's default warehouse
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

def calculate_total_materials_required(bom_no, qty):
    """Calculate total materials required including nested manufacturing"""
    bom_structure = get_nested_bom_structure(bom_no)
    materials_required = {}
    
    def process_bom_items(items, multiplier=1):
        for item in items:
            item_qty = flt(item["qty"]) * multiplier
            
            if item["item_code"] in materials_required:
                materials_required[item["item_code"]] += item_qty
            else:
                materials_required[item["item_code"]] = item_qty
            
            # Process nested items if this is a manufacturing item
            if item.get("is_manufacturing") and item.get("nested_items"):
                process_bom_items(item["nested_items"], item_qty)
    
    process_bom_items(bom_structure, qty)
    return materials_required

def get_nested_bom_structure(bom_no, max_depth=5, current_depth=0):
    """Get complete BOM structure including nested manufacturing items"""
    if current_depth >= max_depth:
        return []
    
    bom_items = frappe.db.get_all(
        "BOM Item",
        filters={"parent": bom_no},
        fields=["item_code", "qty", "bom_no"]
    )
    
    nested_structure = []
    for item in bom_items:
        item_data = {
            "item_code": item["item_code"],
            "qty": flt(item["qty"]),
            "depth": current_depth,
            "is_manufacturing": False,
            "nested_bom": None
        }
        
        # Check if this item is itself a manufacturing item
        nested_bom = frappe.db.get_value("Item", item["item_code"], "default_bom")
        if nested_bom:
            item_data["is_manufacturing"] = True
            item_data["nested_bom"] = nested_bom
            
            # Recursively get nested structure
            nested_items = get_nested_bom_structure(nested_bom, max_depth, current_depth + 1)
            item_data["nested_items"] = nested_items
        
        nested_structure.append(item_data)
    
    return nested_structure

def check_stock_availability(materials_required, warehouse):
    """Check if required materials are available in stock"""
    stock_status = {}
    
    for item_code, required_qty in materials_required.items():
        available_qty = flt(frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": warehouse},
            "actual_qty"
        ) or 0)
        
        stock_status[item_code] = {
            "required": required_qty,
            "available": available_qty,
            "shortage": max(0, required_qty - available_qty),
            "sufficient": available_qty >= required_qty
        }
    
    return stock_status

def get_insufficient_materials(stock_status):
    """Get list of materials with insufficient stock"""
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