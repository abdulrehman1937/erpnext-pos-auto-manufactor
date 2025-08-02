import frappe
from frappe.utils import flt, now_datetime
from frappe import _

# Import settings utility functions
from ..utils.settings import (
    is_auto_manufacturing_enabled,
    should_check_stock_before_manufacturing,
    should_create_nested_work_orders,
    should_track_manufacturing_wastage,
    get_wastage_percentage,
    should_handle_wastage_on_return,
    should_handle_wastage_on_cancel,
    get_manufacturing_return_option
)

def get_item_bom(item_code):
    """Get the default BOM for an item"""
    return frappe.db.get_value("Item", item_code, "default_bom")

def calculate_total_materials_required(bom_no, qty):
    """Calculate total materials required including nested manufacturing"""
    if not bom_no:
        return {}
    
    bom_structure = get_nested_bom_structure(bom_no)
    if not bom_structure:
        return {}
    
    materials_required = {}
    
    def process_bom_items(items, multiplier=1):
        for item in items:
            if not item or not isinstance(item, dict):
                continue
                
            item_qty = flt(item.get("qty", 0)) * multiplier
            
            if item.get("item_code") in materials_required:
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
    if not bom_no or current_depth >= max_depth:
        return []
    
    bom_items = frappe.db.get_all(
        "BOM Item",
        filters={"parent": bom_no},
        fields=["item_code", "qty", "bom_no"]
    )
    
    if not bom_items:
        return []
    
    nested_structure = []
    for item in bom_items:
        if not item or not isinstance(item, dict):
            continue
            
        item_data = {
            "item_code": item.get("item_code", ""),
            "qty": flt(item.get("qty", 0)),
            "depth": current_depth,
            "is_manufacturing": False,
            "nested_bom": None
        }
        
        # Check if this item is itself a manufacturing item
        nested_bom = frappe.db.get_value("Item", item_data["item_code"], "default_bom")
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
    
    if not materials_required or not isinstance(materials_required, dict):
        return stock_status
    
    for item_code, required_qty in materials_required.items():
        if not item_code:
            continue
            
        available_qty = flt(frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": warehouse},
            "actual_qty"
        ) or 0)
        
        stock_status[item_code] = {
            "required": flt(required_qty),
            "available": available_qty,
            "shortage": max(0, flt(required_qty) - available_qty),
            "sufficient": available_qty >= flt(required_qty)
        }
    
    return stock_status

def get_insufficient_materials(stock_status):
    """Get list of materials with insufficient stock"""
    insufficient = []
    
    if not stock_status or not isinstance(stock_status, dict):
        return insufficient
    
    for item_code, status in stock_status.items():
        if not status or not isinstance(status, dict):
            continue
            
        if not status.get("sufficient", True):
            insufficient.append({
                "item_code": item_code,
                "required": status.get("required", 0),
                "available": status.get("available", 0),
                "shortage": status.get("shortage", 0)
            })
    
    return insufficient

def is_document_being_submitted(doc):
    """Check if the document is being submitted"""
    # Simple check: if docstatus is 1, it means the document is being submitted
    if hasattr(doc, 'docstatus') and doc.docstatus == 1:
        return True
    
    # Check for explicit submission indicators
    if hasattr(doc, '_action') and doc._action == 'submit':
        return True
    
    if hasattr(doc, 'flags') and doc.flags.get('is_submitting'):
        return True
    
    return False

def create_manufacture_entry_from_pos(doc, method):
    """
    Triggered on the 'before_validate' event of a Sales Invoice.
    For each manufacturable item, creates a Work Order and a 'Manufacture' Stock Entry.
    Handles nested BOMs and tracks manufacturing relationships.
    Creates and submits manufacturing entries before validation to ensure stock is available for accounting.
    """
    log_prefix = "🏭"
    
    try:
        # Only process POS invoices
        if not doc.is_pos:
            frappe.logger().info(f"{log_prefix} Not a POS invoice, skipping")
            return
            
        # Check if auto manufacturing is enabled
        if not is_auto_manufacturing_enabled():
            frappe.logger().info(f"{log_prefix} Auto manufacturing is disabled, skipping")
            return

        # Check if manufacturing entries already exist for this Sales Invoice
        existing_entries = check_existing_manufacturing_entries(doc)
        if existing_entries:
            frappe.logger().info(f"{log_prefix} Manufacturing entries already exist, skipping")
            return

        manufacture_items = get_manufacturable_items(doc)
        if not manufacture_items:
            frappe.logger().info(f"{log_prefix} No manufacturable items found")
            return

        frappe.logger().info(f"{log_prefix} Found {len(manufacture_items)} manufacturable items")

        # Check stock availability but don't block if low stock (just warn)
        #try:
        #    check_stock_availability_with_warning(doc, manufacture_items)
        #except Exception as e:
        #    frappe.log_error(f"Stock availability check failed: {str(e)}", "POS Auto-Manufacture Stock Check Error")

        # Only create and submit manufacturing entries when document is being submitted
        if hasattr(doc, 'docstatus') and doc.docstatus == 1:
            frappe.logger().info(f"{log_prefix} Document is being submitted, creating and submitting manufacturing entries")
            
            try:
                submitted_entries = []
                
                for item_to_mfg in manufacture_items:
                    qty = flt(item_to_mfg["qty"])
                    if not qty or qty <= 0:
                        frappe.logger().info(f"{log_prefix} Skipping item {item_to_mfg['item_code']} with qty {qty}")
                        continue

                    frappe.logger().info(f"{log_prefix} Creating and submitting manufacturing entries for {item_to_mfg['item_code']} (qty: {qty})")

                    # Create and submit manufacturing entries for this item (including nested BOMs)
                    entries = create_and_submit_manufacturing_entries_for_item(doc, item_to_mfg)
                    submitted_entries.extend(entries)
                    
                    frappe.logger().info(f"{log_prefix} Created and submitted {len(entries)} entries for {item_to_mfg['item_code']}")

                if submitted_entries:
                    frappe.msgprint(
                        f"Created and submitted {len(submitted_entries)} manufacturing entries for {len(manufacture_items)} items",
                        title="Manufacturing Entries Created and Submitted",
                        indicator="green"
                    )
                else:
                    frappe.logger().info(f"{log_prefix} No manufacturing entries were created and submitted")

            except Exception as e:
                frappe.log_error(frappe.get_traceback(), f"POS Auto-Manufacture Failed for {doc.name}")
                frappe.throw(f"Failed to create automatic Manufacture Stock Entry. Please check logs or create it manually. Error: {str(e)}")
        else:
            frappe.logger().info(f"{log_prefix} Document is in draft status, skipping manufacturing entry creation")
            
    except Exception as e:
        frappe.log_error(f"POS Auto-Manufacture general error: {str(e)}", f"POS Auto-Manufacture Error for {doc.name}")
        # Don't throw here to avoid blocking the save process

def check_existing_manufacturing_entries(doc):
    """Check if manufacturing entries already exist for this Sales Invoice"""
    pos_items = [item.item_code for item in doc.items]
    
    existing_stock_entries = frappe.db.get_all(
        "Stock Entry", 
        filters={
            "docstatus": 1,
            "purpose": "Manufacture",
            "posting_date": doc.posting_date
        },
        fields=["name", "work_order"]
    )
    
    # Check if any of these Stock Entries are for the same items
    if existing_stock_entries:
        for se in existing_stock_entries:
            se_items = frappe.db.get_all(
                "Stock Entry Detail",
                filters={"parent": se.name, "is_finished_item": 1},
                fields=["item_code"]
            )
            for se_item in se_items:
                if se_item.item_code in pos_items:
                    frappe.msgprint(
                        f"Manufacturing Stock Entry {se.name} already exists for item {se_item.item_code}",
                        title="Manufacturing Already Complete",
                        indicator="blue"
                    )
                    return True
    return False

def check_stock_availability_with_warning(doc, manufacture_items):
    """Check stock availability and show warning but don't block manufacturing"""
    if not should_check_stock_before_manufacturing():
        return
    
    insufficient_materials = []
    
    for item_to_mfg in manufacture_items:
        bom_no = item_to_mfg["bom_no"]
        qty = flt(item_to_mfg["qty"])
        warehouse = item_to_mfg["warehouse"]
        
        # Calculate total materials required including nested BOMs
        materials_required = calculate_total_materials_required(bom_no, qty)
        
        # Check if materials_required is valid
        if not materials_required or not isinstance(materials_required, dict):
            continue
        
        # Check stock availability
        stock_status = check_stock_availability(materials_required, warehouse)
        insufficient = get_insufficient_materials(stock_status)
        
        # Check if insufficient is valid
        if insufficient and isinstance(insufficient, list):
            insufficient_materials.extend([
                {
                    "item_code": item["item_code"],
                    "required": item["required"],
                    "available": item["available"],
                    "shortage": item["shortage"],
                    "for_manufacturing": item_to_mfg["item_code"]
                }
                for item in insufficient
            ])
    
    if insufficient_materials:
        warning_message = "Low stock detected for manufacturing:\n"
        for material in insufficient_materials:
            warning_message += f"- {material['item_code']}: Required {material['required']}, Available {material['available']}, Shortage {material['shortage']} (for {material['for_manufacturing']})\n"
        
        warning_message += "\nManufacturing will proceed with negative stock. Please replenish materials soon."
        
        frappe.msgprint(
            warning_message,
            title="Stock Warning",
            indicator="orange"
        )

def get_manufacturable_items(doc):
    """Get list of manufacturable items from POS invoice"""
    manufacture_items = []
    
    if not doc or not hasattr(doc, 'items') or not doc.items:
        return manufacture_items
    
    for item in doc.items:
        if not item or not hasattr(item, 'item_code'):
            continue
            
        default_bom = frappe.db.get_value("Item", item.item_code, "default_bom")
        if default_bom:
            manufacture_items.append({
                "item_code": item.item_code,
                "qty": flt(item.qty),
                "bom_no": default_bom,
                "warehouse": getattr(item, 'warehouse', ''),
                "sales_invoice_item": getattr(item, 'name', '')
            })
    return manufacture_items

def create_manufacturing_entries_for_item(doc, item_to_mfg):
    """Create manufacturing entries for an item, handling nested BOMs"""
    created_entries = []
    
    # Get the BOM structure to identify nested manufacturing items
    bom_items = get_bom_items_with_nested_manufacturing(item_to_mfg["bom_no"])
    
    # Create manufacturing entries for nested items first (bottom-up approach)
    nested_entries = create_nested_manufacturing_entries(doc, bom_items, item_to_mfg["warehouse"])
    created_entries.extend(nested_entries)
    
    # Create the main manufacturing entry
    main_entries = create_main_manufacturing_entry(doc, item_to_mfg)
    created_entries.extend(main_entries)
    
    return created_entries

def create_and_submit_manufacturing_entries_for_item(doc, item_to_mfg):
    """Create and immediately submit manufacturing entries for an item, handling nested BOMs"""
    submitted_entries = []
    
    # Get the BOM structure to identify nested manufacturing items
    bom_items = get_bom_items_with_nested_manufacturing(item_to_mfg["bom_no"])
    
    # Create and submit manufacturing entries for nested items first (bottom-up approach)
    nested_entries = create_and_submit_nested_manufacturing_entries(doc, bom_items, item_to_mfg["warehouse"])
    submitted_entries.extend(nested_entries)
    
    # Create and submit the main manufacturing entry
    main_entries = create_and_submit_main_manufacturing_entry(doc, item_to_mfg)
    submitted_entries.extend(main_entries)
    
    return submitted_entries

def get_bom_items_with_nested_manufacturing(bom_no):
    """Get BOM items and identify which ones are themselves manufacturing items"""
    bom_items = frappe.db.get_all(
        "BOM Item",
        filters={"parent": bom_no},
        fields=["item_code", "qty", "bom_no"]
    )
    
    # Check which items are manufacturing items
    for item in bom_items:
        item["is_manufacturing"] = frappe.db.get_value("Item", item["item_code"], "default_bom") is not None
        if item["is_manufacturing"]:
            item["nested_bom"] = frappe.db.get_value("Item", item["item_code"], "default_bom")
    
    return bom_items

def create_nested_manufacturing_entries(doc, bom_items, warehouse):
    """Create manufacturing entries for nested manufacturing items"""
    created_entries = []
    
    for bom_item in bom_items:
        if bom_item.get("is_manufacturing") and bom_item.get("nested_bom"):
            # Calculate required quantity based on BOM ratio
            required_qty = flt(bom_item["qty"])
            
            # Check if we have enough stock
            available_qty = get_available_stock(bom_item["item_code"], warehouse)
            if available_qty < required_qty:
                # Create manufacturing entry for this nested item - only the shortage
                nested_item = {
                    "item_code": bom_item["item_code"],
                    "qty": required_qty - available_qty,
                    "bom_no": bom_item["nested_bom"],
                    "warehouse": warehouse,
                    "is_nested": True
                }
                
                entries = create_main_manufacturing_entry(doc, nested_item)
                created_entries.extend(entries)
    
    return created_entries

def create_and_submit_nested_manufacturing_entries(doc, bom_items, warehouse):
    """Create and submit manufacturing entries for nested manufacturing items"""
    submitted_entries = []
    
    for bom_item in bom_items:
        if bom_item.get("is_manufacturing") and bom_item.get("nested_bom"):
            # Calculate required quantity based on BOM ratio
            required_qty = flt(bom_item["qty"])
            
            # Check if we have enough stock
            available_qty = get_available_stock(bom_item["item_code"], warehouse)
            if available_qty < required_qty:
                # Create and submit manufacturing entry for this nested item - only the shortage
                nested_item = {
                    "item_code": bom_item["item_code"],
                    "qty": required_qty - available_qty,
                    "bom_no": bom_item["nested_bom"],
                    "warehouse": warehouse,
                    "is_nested": True
                }
                
                entries = create_and_submit_main_manufacturing_entry(doc, nested_item)
                submitted_entries.extend(entries)
    
    return submitted_entries

def get_available_stock(item_code, warehouse):
    """Get available stock for an item in a warehouse"""
    return flt(frappe.db.get_value(
        "Bin",
        {"item_code": item_code, "warehouse": warehouse},
        "actual_qty"
    ) or 0)

def create_main_manufacturing_entry(doc, item_to_mfg):
    """Create the main manufacturing entry for an item"""
    created_entries = []
    
    qty = flt(item_to_mfg["qty"])
    if not qty or qty <= 0:
        return created_entries

    # Check if this is a nested item or if we need to calculate shortage
    if not item_to_mfg.get("is_nested"):
        # For main items, check available stock and only manufacture shortage
        available_qty = get_available_stock(item_to_mfg["item_code"], item_to_mfg["warehouse"])
        if available_qty >= qty:
            # We have enough stock, no need to manufacture
            return created_entries
        else:
            # Only manufacture the shortage
            qty = qty - available_qty
            item_to_mfg["qty"] = qty

    try:
        # Check if document is being submitted
        is_submitting = (hasattr(doc, 'docstatus') and doc.docstatus == 1)
        
        # 1. Create the Work Order
        wo = create_work_order(doc, item_to_mfg, submit=is_submitting)
        created_entries.append(("Work Order", wo.name))

        # 2. Create the Manufacturing Stock Entry
        se = create_manufacturing_stock_entry(doc, item_to_mfg, wo, submit=is_submitting)
        created_entries.append(("Stock Entry", se.name))

        # 3. Create wastage tracking entry if needed
        wastage_entry = create_wastage_tracking_entry(doc, item_to_mfg, wo, submit=is_submitting)
        if wastage_entry:
            created_entries.append(("Wastage Entry", wastage_entry.name))

        if is_submitting:
            frappe.msgprint(
                f"Created and submitted Work Order {wo.name} and Stock Entry {se.name} for {item_to_mfg['item_code']} (Qty: {qty})",
                title="Manufacturing Entry Created and Submitted",
                indicator="green"
            )
        else:
            frappe.msgprint(
                f"Prepared Work Order {wo.name} and Stock Entry {se.name} for {item_to_mfg['item_code']} (Qty: {qty})",
                title="Manufacturing Entry Prepared",
                indicator="blue"
            )

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Failed to create manufacturing entry for {item_to_mfg['item_code']}")
        frappe.throw(f"Failed to create manufacturing entry for {item_to_mfg['item_code']}: {str(e)}")
    
    return created_entries

def create_and_submit_main_manufacturing_entry(doc, item_to_mfg):
    """Create and immediately submit the main manufacturing entry for an item"""
    submitted_entries = []
    
    qty = flt(item_to_mfg["qty"])
    if not qty or qty <= 0:
        return submitted_entries

    # Check if this is a nested item or if we need to calculate shortage
    if not item_to_mfg.get("is_nested"):
        # For main items, check available stock and only manufacture shortage
        available_qty = get_available_stock(item_to_mfg["item_code"], item_to_mfg["warehouse"])
        if available_qty >= qty:
            # We have enough stock, no need to manufacture
            return submitted_entries
        else:
            # Only manufacture the shortage
            qty = qty - available_qty
            item_to_mfg["qty"] = qty

    try:
        # 1. Create and submit the Work Order
        wo = create_work_order(doc, item_to_mfg, submit=True)
        submitted_entries.append(f"Work Order: {wo.name}")

        # 2. Create and submit the Manufacturing Stock Entry
        se = create_manufacturing_stock_entry(doc, item_to_mfg, wo, submit=True)
        submitted_entries.append(f"Stock Entry: {se.name}")

        # 3. Create and submit wastage tracking entry if needed
        wastage_entry = create_wastage_tracking_entry(doc, item_to_mfg, wo, submit=True)
        if wastage_entry:
            submitted_entries.append(f"Wastage Entry: {wastage_entry.name}")

        frappe.msgprint(
            f"Created and submitted Work Order {wo.name} and Stock Entry {se.name} for {item_to_mfg['item_code']} (Qty: {qty})",
            title="Manufacturing Entry Created and Submitted",
            indicator="green"
        )

    except Exception as e:
        frappe.log_error(frappe.get_traceback(), f"Failed to create and submit manufacturing entry for {item_to_mfg['item_code']}")
        frappe.throw(f"Failed to create and submit manufacturing entry for {item_to_mfg['item_code']}: {str(e)}")
    
    return submitted_entries

def create_work_order(doc, item_to_mfg, submit=True):
    """Create a Work Order"""
    wo = frappe.new_doc("Work Order")
    wo.production_item = item_to_mfg["item_code"]
    wo.bom_no = item_to_mfg["bom_no"]
    wo.qty = flt(item_to_mfg["qty"])
    wo.company = doc.company
    wo.fg_warehouse = item_to_mfg["warehouse"]
    wo.wip_warehouse = item_to_mfg["warehouse"]
    
    # Store sales invoice reference in description for tracking
    wo.description = f"Auto-generated from Sales Invoice: {doc.name}"
    
    wo.planned_start_date = doc.posting_date
    wo.insert(ignore_permissions=True)
    
    if submit:
        wo.submit()
    
    return wo

def create_manufacturing_stock_entry(doc, item_to_mfg, work_order, submit=True):
    """Create a Manufacturing Stock Entry"""
    se = frappe.new_doc("Stock Entry")
    se.purpose = "Manufacture"
    se.work_order = work_order.name
    se.company = doc.company
    se.posting_date = doc.posting_date
    se.posting_time = doc.posting_time
    se.from_bom = 1
    se.bom_no = item_to_mfg["bom_no"]
    se.fg_completed_qty = flt(item_to_mfg["qty"])
    se.for_quantity = flt(item_to_mfg["qty"])

    # Populate items from BOM
    se.get_items()

    # Set warehouses correctly
    for se_item in se.items:
        if se_item.is_finished_item:
            se_item.t_warehouse = item_to_mfg["warehouse"]
        else:
            se_item.s_warehouse = item_to_mfg["warehouse"]

    se.from_bom = 1
    se.set_stock_entry_type()
    se.insert(ignore_permissions=True)
    
    if submit:
        se.submit()
    
    return se

def create_wastage_tracking_entry(doc, item_to_mfg, work_order, submit=True):
    """Create a wastage tracking entry for manufacturing"""
    # This is optional - you can customize based on your wastage tracking needs
    try:
        wastage_entry = frappe.new_doc("Stock Entry")
        wastage_entry.purpose = "Material Transfer"
        wastage_entry.company = doc.company
        wastage_entry.posting_date = doc.posting_date
        wastage_entry.posting_time = doc.posting_time
        wastage_entry.stock_entry_type = "Material Transfer"
        
        # Add wastage item if configured
        wastage_item = frappe.db.get_value("Item", item_to_mfg["item_code"], "wastage_item")
        if wastage_item:
            wastage_entry.append("items", {
                "item_code": wastage_item,
                "qty": flt(item_to_mfg["qty"]) * 0.05,  # 5% wastage assumption
                "s_warehouse": item_to_mfg["warehouse"],
                "t_warehouse": item_to_mfg["warehouse"]
            })
            wastage_entry.insert(ignore_permissions=True)
            
            if submit:
                wastage_entry.submit()
            
            return wastage_entry
    except Exception as e:
        frappe.log_error(f"Failed to create wastage entry: {str(e)}")
    
    return None

def submit_manufacturing_entries(doc, method):
    """
    Submit manufacturing entries when POS invoice is submitted.
    This ensures the manufacturing entries are submitted after the POS invoice is validated.
    """
    if not doc.is_pos:
        return
        
    if doc.docstatus != 1:
        return
    
    frappe.logger().info(f"🏭 Submitting manufacturing entries for Sales Invoice: {doc.name}")
    
    try:
        submitted_entries = []
        
        # First, try to get entries from document attributes (if available)
        manufacturing_entries = getattr(doc, 'manufacturing_entries', [])
        manufacturing_entries_data = getattr(doc, 'manufacturing_entries_data', [])
        
        # Log for debugging
        frappe.logger().info(f"Manufacturing entries from attributes: {manufacturing_entries}")
        frappe.logger().info(f"Manufacturing entries data: {manufacturing_entries_data}")
        
        # If no entries found in attributes, try to find them by searching
        if not manufacturing_entries and not manufacturing_entries_data:
            frappe.logger().info("No manufacturing entries found in attributes, searching by description...")
            manufacturing_entries = find_manufacturing_entries_for_sales_invoice(doc)
            frappe.logger().info(f"Found manufacturing entries by search: {manufacturing_entries}")
        
        # If still no entries found, try to get from comments
        if not manufacturing_entries:
            frappe.logger().info("No manufacturing entries found by search, checking comments...")
            manufacturing_entries = get_manufacturing_entries_from_comment(doc)
            frappe.logger().info(f"Found manufacturing entries from comments: {manufacturing_entries}")
        
        # Submit all found entries
        for entry_type, entry_name in manufacturing_entries:
            try:
                if entry_type == "Work Order":
                    wo = frappe.get_doc("Work Order", entry_name)
                    if wo.docstatus == 0:
                        wo.submit()
                        submitted_entries.append(f"Work Order: {entry_name}")
                        frappe.logger().info(f"Submitted Work Order: {entry_name}")
                    else:
                        frappe.logger().info(f"Work Order {entry_name} already submitted (docstatus: {wo.docstatus})")
                
                elif entry_type == "Stock Entry":
                    se = frappe.get_doc("Stock Entry", entry_name)
                    if se.docstatus == 0:
                        se.submit()
                        submitted_entries.append(f"Stock Entry: {entry_name}")
                        frappe.logger().info(f"Submitted Stock Entry: {entry_name}")
                    else:
                        frappe.logger().info(f"Stock Entry {entry_name} already submitted (docstatus: {se.docstatus})")
                
                elif entry_type == "Wastage Entry":
                    we = frappe.get_doc("Stock Entry", entry_name)
                    if we.docstatus == 0:
                        we.submit()
                        submitted_entries.append(f"Wastage Entry: {entry_name}")
                        frappe.logger().info(f"Submitted Wastage Entry: {entry_name}")
                    else:
                        frappe.logger().info(f"Wastage Entry {entry_name} already submitted (docstatus: {we.docstatus})")
                        
            except Exception as e:
                frappe.log_error(f"Failed to submit {entry_type} {entry_name}: {str(e)}")
        
        if submitted_entries:
            frappe.msgprint(
                f"Submitted {len(submitted_entries)} manufacturing entries",
                title="Manufacturing Entries Submitted",
                indicator="green"
            )
        else:
            # If no entries were submitted, check if we should create them now
            manufacture_items = get_manufacturable_items(doc)
            if manufacture_items:
                frappe.logger().info(f"No manufacturing entries found to submit. Found {len(manufacture_items)} manufacturable items. Creating entries now...")
                frappe.msgprint(
                    "No manufacturing entries found to submit. Creating entries now...",
                    title="Creating Manufacturing Entries",
                    indicator="orange"
                )
                create_and_submit_manufacturing_entries(doc, manufacture_items)
            else:
                frappe.logger().info("No manufacturable items found in the sales invoice")
        
        # Additional fallback: Find and submit any work orders that are still in draft for this sales invoice
        try:
            work_orders = frappe.db.get_all(
                "Work Order",
                filters={
                    "description": ["like", f"%{doc.name}%"],
                    "docstatus": 0
                },
                fields=["name"]
            )
            
            if work_orders:
                frappe.logger().info(f"Found {len(work_orders)} work orders in draft status for {doc.name}, submitting them...")
                for wo in work_orders:
                    try:
                        wo_doc = frappe.get_doc("Work Order", wo.name)
                        wo_doc.submit()
                        frappe.logger().info(f"Submitted Work Order: {wo.name}")
                    except Exception as e:
                        frappe.log_error(f"Failed to submit Work Order {wo.name}: {str(e)}")
                
                frappe.msgprint(
                    f"Submitted {len(work_orders)} additional work orders",
                    title="Additional Work Orders Submitted",
                    indicator="green"
                )
        except Exception as e:
            frappe.log_error(f"Failed to submit additional work orders: {str(e)}")
                
    except Exception as e:
        frappe.log_error(f"Failed to submit manufacturing entries for {doc.name}: {str(e)}")
        frappe.throw(f"Failed to submit manufacturing entries: {str(e)}")

def find_manufacturing_entries_for_sales_invoice(doc):
    """Find manufacturing entries related to this sales invoice"""
    manufacturing_entries = []
    
    try:
        # Find work orders by description
        work_orders = frappe.db.get_all(
            "Work Order",
            filters={
                "description": ["like", f"%{doc.name}%"],
                "docstatus": 0
            },
            fields=["name"]
        )
        
        for wo in work_orders:
            manufacturing_entries.append(("Work Order", wo.name))
        
        # Find stock entries by work order
        if work_orders:
            wo_names = [wo.name for wo in work_orders]
            stock_entries = frappe.db.get_all(
                "Stock Entry",
                filters={
                    "work_order": ["in", wo_names],
                    "docstatus": 0
                },
                fields=["name"]
            )
            
            for se in stock_entries:
                manufacturing_entries.append(("Stock Entry", se.name))
                
    except Exception as e:
        frappe.log_error(f"Failed to find manufacturing entries: {str(e)}")
    
    return manufacturing_entries

def create_and_submit_manufacturing_entries(doc, manufacture_items):
    """Create and immediately submit manufacturing entries"""
    try:
        submitted_entries = []
        
        for item_to_mfg in manufacture_items:
            qty = flt(item_to_mfg["qty"])
            if not qty or qty <= 0:
                continue

            # Create manufacturing entries for this item (including nested BOMs)
            entries = create_manufacturing_entries_for_item(doc, item_to_mfg)
            
            # Submit each entry immediately
            for entry_type, entry_name in entries:
                try:
                    if entry_type == "Work Order":
                        wo = frappe.get_doc("Work Order", entry_name)
                        if wo.docstatus == 0:
                            wo.submit()
                            submitted_entries.append(f"Work Order: {entry_name}")
                    
                    elif entry_type == "Stock Entry":
                        se = frappe.get_doc("Stock Entry", entry_name)
                        if se.docstatus == 0:
                            se.submit()
                            submitted_entries.append(f"Stock Entry: {entry_name}")
                    
                    elif entry_type == "Wastage Entry":
                        we = frappe.get_doc("Stock Entry", entry_name)
                        if we.docstatus == 0:
                            we.submit()
                            submitted_entries.append(f"Wastage Entry: {entry_name}")
                            
                except Exception as e:
                    frappe.log_error(f"Failed to submit {entry_type} {entry_name}: {str(e)}")
        
        if submitted_entries:
            frappe.msgprint(
                f"Created and submitted {len(submitted_entries)} manufacturing entries",
                title="Manufacturing Entries Created and Submitted",
                indicator="green"
            )
            
    except Exception as e:
        frappe.log_error(f"Failed to create and submit manufacturing entries: {str(e)}")
        frappe.throw(f"Failed to create and submit manufacturing entries: {str(e)}")

def store_manufacturing_entries_info(doc, created_entries):
    """Store manufacturing entries information in a persistent way"""
    try:
        # Store in a comment for persistence
        if created_entries:
            entries_info = []
            for entry_type, entry_name in created_entries:
                entries_info.append(f"{entry_type}:{entry_name}")
            
            comment_text = f"Manufacturing Entries: {','.join(entries_info)}"
            
            # Add comment to the document
            doc.add_comment("Info", comment_text)
            
            frappe.logger().info(f"Stored manufacturing entries info in comment: {comment_text}")
            
    except Exception as e:
        frappe.logger().error(f"Failed to store manufacturing entries info: {str(e)}")

def get_manufacturing_entries_from_comment(doc):
    """Retrieve manufacturing entries information from comments"""
    try:
        # Get the latest comment with manufacturing entries info
        comments = frappe.db.get_all(
            "Comment",
            filters={
                "reference_doctype": "Sales Invoice",
                "reference_name": doc.name,
                "comment_type": "Info",
                "comment": ["like", "Manufacturing Entries:%"]
            },
            fields=["comment"],
            order_by="creation desc",
            limit=1
        )
        
        if comments:
            comment_text = comments[0].comment
            # Extract entries from comment
            if "Manufacturing Entries:" in comment_text:
                entries_text = comment_text.split("Manufacturing Entries:")[1]
                entries = []
                for entry_info in entries_text.split(","):
                    if ":" in entry_info:
                        entry_type, entry_name = entry_info.strip().split(":", 1)
                        entries.append((entry_type, entry_name))
                return entries
        
        return []
        
    except Exception as e:
        frappe.logger().error(f"Failed to get manufacturing entries from comment: {str(e)}")
        return []

# Handle returns and cancellations
def handle_pos_return_or_cancel(doc, method):
    """
    Handle returns and cancellations of POS invoices
    Cancels related manufacturing entries and creates return entries
    """
    if not doc.is_pos:
        return
    
    if doc.docstatus == 2:  # Cancelled
        cancel_related_manufacturing_entries(doc)
    elif doc.is_return:
        handle_pos_return(doc)

def cancel_related_manufacturing_entries(doc):
    """Cancel all manufacturing entries related to this POS invoice"""
    try:
        # Get the user's choice for handling manufacturing returns
        return_option = doc.get("manufacturing_return_option", "Convert to Raw Materials")
        
        # Find related Work Orders by searching in description
        work_orders = frappe.db.get_all(
            "Work Order",
            filters={"description": ["like", f"%{doc.name}%"], "docstatus": 1},
            fields=["name", "production_item", "qty"]
        )
        
        if return_option == "Convert to Raw Materials":
            # Cancel work orders and create reverse entries
            for wo in work_orders:
                try:
                    wo_doc = frappe.get_doc("Work Order", wo.name)
                    wo_doc.cancel()
                    frappe.msgprint(f"Cancelled Work Order: {wo.name}")
                    
                    # Create reverse manufacturing entry for the cancelled work order
                    create_reverse_manufacturing_for_cancelled_work_order(doc, wo_doc)
                    
                except Exception as e:
                    frappe.log_error(f"Failed to cancel Work Order {wo.name}: {str(e)}")
        else:
            # Just cancel the work orders without creating reverse entries
            for wo in work_orders:
                try:
                    wo_doc = frappe.get_doc("Work Order", wo.name)
                    wo_doc.cancel()
                    frappe.msgprint(f"Cancelled Work Order: {wo.name}")
                except Exception as e:
                    frappe.log_error(f"Failed to cancel Work Order {wo.name}: {str(e)}")
        
        # Find related Stock Entries
        stock_entries = frappe.db.get_all(
            "Stock Entry",
            filters={"work_order": ["in", [wo.name for wo in work_orders]], "docstatus": 1},
            fields=["name"]
        )
        
        for se in stock_entries:
            try:
                se_doc = frappe.get_doc("Stock Entry", se.name)
                se_doc.cancel()
                frappe.msgprint(f"Cancelled Stock Entry: {se.name}")
            except Exception as e:
                frappe.log_error(f"Failed to cancel Stock Entry {se.name}: {str(e)}")
                
    except Exception as e:
        frappe.log_error(f"Failed to cancel manufacturing entries for {doc.name}: {str(e)}")
        frappe.throw(f"Failed to cancel related manufacturing entries: {str(e)}")

def handle_pos_return(doc):
    """Handle POS return by creating reverse manufacturing entries"""
    try:
        # Get the user's choice for handling manufacturing returns
        return_option = doc.get("manufacturing_return_option", "Convert to Raw Materials")
        
        for item in doc.items:
            if item.qty < 0:  # Return item
                default_bom = frappe.db.get_value("Item", item.item_code, "default_bom")
                if default_bom:
                    if return_option == "Convert to Raw Materials":
                        create_return_manufacturing_entry(doc, item)
                    else:
                        # Keep manufactured product - just return the finished goods
                        create_return_finished_goods_entry(doc, item)
                    
    except Exception as e:
        frappe.log_error(f"Failed to handle POS return for {doc.name}: {str(e)}")
        frappe.throw(f"Failed to handle POS return: {str(e)}")

def create_return_manufacturing_entry(doc, return_item):
    """Create reverse manufacturing entry for returned items"""
    try:
        # Create reverse stock entry to return materials
        se = frappe.new_doc("Stock Entry")
        se.purpose = "Material Transfer"
        se.company = doc.company
        se.posting_date = doc.posting_date
        se.posting_time = doc.posting_time
        se.stock_entry_type = "Material Transfer"
        
        # Get BOM items to reverse
        bom_items = frappe.db.get_all(
            "BOM Item",
            filters={"parent": frappe.db.get_value("Item", return_item.item_code, "default_bom")},
            fields=["item_code", "qty"]
        )
        
        return_qty = abs(flt(return_item.qty))
        
        for bom_item in bom_items:
            # Calculate return quantity based on BOM ratio
            return_material_qty = flt(bom_item.qty) * return_qty
            
            se.append("items", {
                "item_code": bom_item.item_code,
                "qty": return_material_qty,
                "s_warehouse": return_item.warehouse,
                "t_warehouse": return_item.warehouse
            })
        
        se.insert(ignore_permissions=True)
        se.submit()
        
        frappe.msgprint(f"Created return entry {se.name} for {return_item.item_code}")
        
    except Exception as e:
        frappe.log_error(f"Failed to create return manufacturing entry: {str(e)}")
        frappe.throw(f"Failed to create return manufacturing entry: {str(e)}")

def create_return_finished_goods_entry(doc, return_item):
    """Create return entry for finished goods (keep manufactured product)"""
    try:
        # Create stock entry to return finished goods to warehouse
        se = frappe.new_doc("Stock Entry")
        se.purpose = "Material Transfer"
        se.company = doc.company
        se.posting_date = doc.posting_date
        se.posting_time = doc.posting_time
        se.stock_entry_type = "Material Transfer"
        
        return_qty = abs(flt(return_item.qty))
        
        # Add finished goods return
        se.append("items", {
            "item_code": return_item.item_code,
            "qty": return_qty,
            "s_warehouse": return_item.warehouse,
            "t_warehouse": return_item.warehouse
        })
        
        se.insert(ignore_permissions=True)
        se.submit()
        
        frappe.msgprint(f"Created finished goods return entry {se.name} for {return_item.item_code}")
        
    except Exception as e:
        frappe.log_error(f"Failed to create finished goods return entry: {str(e)}")
        frappe.throw(f"Failed to create finished goods return entry: {str(e)}")

def create_reverse_manufacturing_for_cancelled_work_order(doc, work_order):
    """Create reverse manufacturing entry for a cancelled work order"""
    try:
        # Get BOM items to reverse
        bom_items = frappe.db.get_all(
            "BOM Item",
            filters={"parent": work_order.bom_no},
            fields=["item_code", "qty"]
        )
        
        if not bom_items:
            return
        
        # Create reverse stock entry to return materials
        se = frappe.new_doc("Stock Entry")
        se.purpose = "Material Transfer"
        se.company = doc.company
        se.posting_date = doc.posting_date
        se.posting_time = doc.posting_time
        se.stock_entry_type = "Material Transfer"
        
        # Calculate return quantity based on work order quantity
        return_qty = flt(work_order.qty)
        
        for bom_item in bom_items:
            # Calculate return quantity based on BOM ratio
            return_material_qty = flt(bom_item.qty) * return_qty
            
            se.append("items", {
                "item_code": bom_item.item_code,
                "qty": return_material_qty,
                "s_warehouse": work_order.fg_warehouse,
                "t_warehouse": work_order.fg_warehouse
            })
        
        se.insert(ignore_permissions=True)
        se.submit()
        
        frappe.msgprint(f"Created reverse manufacturing entry {se.name} for cancelled work order {work_order.name}")
        
    except Exception as e:
        frappe.log_error(f"Failed to create reverse manufacturing entry for cancelled work order: {str(e)}")
        frappe.throw(f"Failed to create reverse manufacturing entry for cancelled work order: {str(e)}")

# Handle wastage tracking
def track_manufacturing_wastage(doc, method):
    """Track wastage during manufacturing process"""
    if doc.purpose != "Manufacture":
        return
    
    # Check if wastage tracking is enabled
    if not should_track_manufacturing_wastage():
        return
    
    try:
        # Calculate wastage based on BOM vs actual consumption
        bom_qty = flt(doc.fg_completed_qty)
        actual_consumption = sum([flt(item.qty) for item in doc.items if not item.is_finished_item])
        
        # Get expected consumption from BOM
        bom_items = frappe.db.get_all(
            "BOM Item",
            filters={"parent": doc.bom_no},
            fields=["item_code", "qty"]
        )
        expected_consumption = sum([flt(item.qty) * bom_qty for item in bom_items])
        
        wastage = actual_consumption - expected_consumption
        
        if wastage > 0:
            # Create wastage tracking entry
            create_wastage_entry(doc, wastage)
            
    except Exception as e:
        frappe.log_error(f"Failed to track manufacturing wastage: {str(e)}")

def create_wastage_entry(doc, wastage_qty):
    """Create a wastage tracking entry"""
    try:
        wastage_entry = frappe.new_doc("Stock Entry")
        wastage_entry.purpose = "Material Transfer"
        wastage_entry.company = doc.company
        wastage_entry.posting_date = doc.posting_date
        wastage_entry.posting_time = doc.posting_time
        wastage_entry.stock_entry_type = "Material Transfer"
        
        # Add wastage item
        wastage_item = frappe.db.get_value("Item", doc.production_item, "wastage_item")
        if wastage_item:
            wastage_entry.append("items", {
                "item_code": wastage_item,
                "qty": wastage_qty,
                "s_warehouse": doc.fg_warehouse,
                "t_warehouse": doc.fg_warehouse
            })
            wastage_entry.insert(ignore_permissions=True)
            wastage_entry.submit()
            
    except Exception as e:
        frappe.log_error(f"Failed to create wastage entry: {str(e)}")