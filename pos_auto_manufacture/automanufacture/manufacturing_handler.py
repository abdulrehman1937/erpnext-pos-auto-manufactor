import frappe
from frappe.utils import flt

@frappe.whitelist()
def create_manufacture_entry_from_pos(doc, method):
    """
    This function is triggered on the 'on_submit' event of a Sales Invoice.
    It checks for manufacturable items and creates a 'Manufacture' Stock Entry.
    """
    # Proceed only if the invoice is from a Point of Sale transaction
    if not doc.is_pos:
        return

    manufacture_items =

    # Iterate through each item in the submitted Sales Invoice
    for item in doc.items:
        # Check if the item has a default Bill of Materials (BOM)
        default_bom = frappe.db.get_value("Item", item.item_code, "default_bom")
        
        if default_bom:
            # If a BOM exists, this is a manufacturable item.
            # Add its details to our list for processing.
            manufacture_items.append({
                "item_code": item.item_code,
                "qty": item.qty,
                "bom_no": default_bom,
                "warehouse": item.warehouse
            })

    # If we found any items that need to be manufactured, create the stock entry
    if manufacture_items:
        try:
            # Create a new Stock Entry document in memory
            se = frappe.new_doc("Stock Entry")
            se.purpose = "Manufacture"
            se.company = doc.company
            
            # Match the posting date and time to the original sales transaction for accurate reporting
            se.posting_date = doc.posting_date
            se.posting_time = doc.posting_time
            
            # Link back to the source Sales Invoice for traceability
            se.sales_invoice = doc.name

            # Add the finished goods (menu items) to the Stock Entry's items table
            for item_to_mfg in manufacture_items:
                se.append("items", {
                    "item_code": item_to_mfg.get("item_code"),
                    "qty": item_to_mfg.get("qty"),
                    "t_warehouse": item_to_mfg.get("warehouse"),
                    "bom_no": item_to_mfg.get("bom_no")
                })
            
            # The system will automatically add raw materials from the BOM upon submission
            # because of the 'Backflush raw materials based on BOM' setting.
            
            se.insert(ignore_permissions=True)
            se.submit()
            
            frappe.msgprint(f"Created Manufacture Stock Entry: {se.name}", title="Automation Success", indicator="green")

        except Exception as e:
            # If any part of the process fails (e.g., insufficient stock), log the error
            # and notify the user that manual intervention is required.
            frappe.log_error(frappe.get_traceback(), "POS Auto-Manufacture Script Failed")
            frappe.throw(f"Failed to create automatic Manufacture Stock Entry. Please check stock levels or create it manually. Error: {str(e)}")
