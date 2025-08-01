import frappe
from frappe.utils import flt

@frappe.whitelist()
def check_bom_stock_levels(item_code, qty, warehouse):
    """
    This whitelisted function is called from the client-side POS script.
    It explodes the BOM for a given item and checks the available quantity
    of each raw material against the required quantity.
    
    Returns a list of ingredients with insufficient stock.
    """
    if not item_code or not qty or not warehouse:
        return

    # Get the default Bill of Materials for the finished good item
    default_bom = frappe.db.get_value("Item", item_code, "default_bom")
    if not default_bom:
        return # Not a manufacturable item

    low_stock_items =
    try:
        bom = frappe.get_doc("BOM", default_bom)
        
        # Iterate through each raw material in the BOM
        for bom_item in bom.get("items",):
            required_qty = flt(bom_item.stock_qty) * flt(qty)
            
            # Get the current actual quantity of the raw material in the specified warehouse
            available_qty = frappe.db.get_value("Bin", 
                {"item_code": bom_item.item_code, "warehouse": warehouse}, 
                "actual_qty") or 0
            
            if flt(available_qty) < required_qty:
                low_stock_items.append({
                    "item_name": bom_item.item_name,
                    "required": required_qty,
                    "available": flt(available_qty),
                    "uom": bom_item.stock_uom
                })
                
    except frappe.DoesNotExistError:
        # BOM not found, log it but don't stop the transaction
        frappe.log_error(f"BOM {default_bom} not found for item {item_code}", "POS Stock Check")
        return

    return low_stock_items