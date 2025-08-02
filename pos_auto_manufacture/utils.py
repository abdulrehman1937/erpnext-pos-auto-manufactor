import frappe
from frappe.utils import flt, now_datetime
from frappe import _

# Import settings from the new settings module
from .utils.settings import get_settings

def log_manufacturing_activity(message, level="INFO", doc_name=None):
    """Log manufacturing activity"""
    # For now, always log since we don't have logging settings in the new structure
    log_message = f"[POS Auto-Manufacture] {message}"
    if doc_name:
        log_message += f" - Document: {doc_name}"
    
    if level == "ERROR":
        frappe.log_error(log_message)
    elif level == "WARNING":
        frappe.logger().warning(log_message)
    else:
        frappe.logger().info(log_message)

def is_manufacturable_item(item_code):
    """Check if an item is manufacturable (has a default BOM)"""
    return frappe.db.get_value("Item", item_code, "default_bom") is not None

def get_item_bom(item_code):
    """Get the default BOM for an item"""
    return frappe.db.get_value("Item", item_code, "default_bom")

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

def calculate_wastage_qty(production_qty, wastage_percentage=None):
    """Calculate wastage quantity based on production quantity"""
    from .utils.settings import get_wastage_percentage
    
    if wastage_percentage is None:
        wastage_percentage = get_wastage_percentage()
    
    return flt(production_qty) * (flt(wastage_percentage) / 100.0)

def get_wastage_item(item_code):
    """Get wastage item for a manufacturing item"""
    # For now, use the default wastage_item field
    return frappe.db.get_value("Item", item_code, "wastage_item")

def validate_manufacturing_prerequisites(doc):
    """Validate prerequisites for manufacturing"""
    errors = []
    
    # Check if company is set
    if not doc.company:
        errors.append("Company is required for manufacturing")
    
    # Check if posting date is set
    if not doc.posting_date:
        errors.append("Posting date is required for manufacturing")
    
    # Check if items have warehouses
    for item in doc.items:
        if not item.warehouse:
            errors.append(f"Warehouse is required for item {item.item_code}")
    
    if errors:
        frappe.throw("<br>".join(errors))

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

def get_related_work_orders(sales_invoice):
    """Get work orders related to a sales invoice"""
    return frappe.db.get_all(
        "Work Order",
        filters={"description": ["like", f"%{sales_invoice}%"]},
        fields=["name", "production_item", "qty"]
    )

def get_related_stock_entries(sales_invoice):
    """Get stock entries related to a sales invoice"""
    work_orders = [wo.name for wo in get_related_work_orders(sales_invoice)]
    if work_orders:
        return frappe.db.get_all(
            "Stock Entry",
            filters={"work_order": ["in", work_orders]},
            fields=["name", "purpose", "fg_completed_qty"]
        )
    return [] 