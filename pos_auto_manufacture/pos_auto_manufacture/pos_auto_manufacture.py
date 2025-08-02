"""
POS Auto-Manufacture with Product Bundle Support

This module extends the POS auto-manufacture functionality to support product bundles.
When a product bundle is sold in POS, the system will:

1. Expand the bundle to get all constituent items
2. Identify which items are manufacturable (have BOMs)
3. Create manufacturing entries for each manufacturable item
4. Handle nested bundles recursively
5. Support returns and cancellations for bundle items

Key Features:
- Recursive bundle expansion with depth limits
- Circular reference detection
- Stock availability checking for bundle materials
- Manufacturing entry creation for bundle items
- Return and cancellation handling for bundles
- Comprehensive logging for debugging

Usage:
- Bundle items are automatically detected and processed
- Manufacturing entries are created for each manufacturable item in the bundle
- Stock entries include both BOM materials and bundle stock items
- Returns and cancellations handle all bundle constituents
"""

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

# Import product bundle functions from ERPNext
from erpnext.stock.doctype.packed_item.packed_item import (
    is_product_bundle,
    get_product_bundle_items
)

def expand_product_bundle(item_code, qty=1, max_depth=5, current_depth=0):
    """
    Recursively expand a product bundle to get all constituent items.
    Returns a list of items with their quantities.
    """
    if current_depth >= max_depth:
        frappe.logger().warning(f"Maximum bundle depth ({max_depth}) reached for item {item_code}")
        return []
    
    # Validate bundle structure to prevent circular references
    if not validate_bundle_structure(item_code):
        frappe.logger().error(f"Invalid bundle structure detected for item {item_code}")
        return []
    
    expanded_items = []
    
    # Check if this item is a product bundle
    if is_product_bundle(item_code):
        bundle_items = get_product_bundle_items(item_code)
        
        for bundle_item in bundle_items:
            bundle_item_qty = flt(bundle_item.get("qty", 0)) * qty
            
            # Recursively expand nested bundles
            nested_items = expand_product_bundle(
                bundle_item["item_code"], 
                bundle_item_qty, 
                max_depth, 
                current_depth + 1
            )
            
            if nested_items:
                # If nested items were found, add them
                expanded_items.extend(nested_items)
            else:
                # If no nested items, add this item directly
                expanded_items.append({
                    "item_code": bundle_item["item_code"],
                    "qty": bundle_item_qty,
                    "uom": bundle_item.get("uom"),
                    "description": bundle_item.get("description"),
                    "is_from_bundle": True,
                    "bundle_parent": item_code
                })
    else:
        # Not a bundle, return the item as is
        expanded_items.append({
            "item_code": item_code,
            "qty": qty,
            "is_from_bundle": False
        })
    
    return expanded_items

def get_bundle_manufacturable_items(bundle_items):
    """
    Extract manufacturable items from a list of bundle items.
    Returns items that have a default BOM.
    """
    manufacturable_items = []
    
    for bundle_item in bundle_items:
        item_code = bundle_item["item_code"]
        qty = flt(bundle_item["qty"])
        
        if not qty or qty <= 0:
            continue
            
        # Check if this item has a default BOM
        default_bom = frappe.db.get_value("Item", item_code, "default_bom")
        if default_bom:
            manufacturable_items.append({
                "item_code": item_code,
                "qty": qty,
                "bom_no": default_bom,
                "warehouse": bundle_item.get("warehouse", ""),
                "is_from_bundle": bundle_item.get("is_from_bundle", False),
                "bundle_parent": bundle_item.get("bundle_parent"),
                "uom": bundle_item.get("uom"),
                "description": bundle_item.get("description")
            })
    
    return manufacturable_items

def validate_bundle_structure(item_code, visited=None, max_depth=10):
    """
    Validate bundle structure to prevent circular references.
    Returns True if valid, False if circular reference detected.
    """
    if visited is None:
        visited = set()
    
    if len(visited) > max_depth:
        frappe.logger().error(f"Bundle depth exceeded maximum ({max_depth}) for item {item_code}")
        return False
    
    if item_code in visited:
        frappe.logger().error(f"Circular reference detected in bundle structure for item {item_code}")
        return False
    
    visited.add(item_code)
    
    if is_product_bundle(item_code):
        bundle_items = get_product_bundle_items(item_code)
        for bundle_item in bundle_items:
            if not validate_bundle_structure(bundle_item["item_code"], visited.copy(), max_depth):
                return False
    
    return True

def get_item_bom(item_code):
    """Get the default BOM for an item"""
    return frappe.db.get_value("Item", item_code, "default_bom")

def calculate_total_materials_required(bom_no, qty, item_code=None):
    """Calculate total materials required including nested manufacturing and bundle items"""
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
    
    # If this is a bundle item, also check for bundle materials
    if item_code and is_product_bundle(item_code):
        bundle_materials = calculate_bundle_materials_required(item_code, qty)
        for material_code, material_qty in bundle_materials.items():
            if material_code in materials_required:
                materials_required[material_code] += material_qty
            else:
                materials_required[material_code] = material_qty
    
    return materials_required

def calculate_bundle_materials_required(bundle_item_code, qty):
    """Calculate materials required for bundle items that are not manufacturing items"""
    materials_required = {}
    
    if not is_product_bundle(bundle_item_code):
        return materials_required
    
    bundle_items = expand_product_bundle(bundle_item_code, qty)
    
    for bundle_item in bundle_items:
        item_code = bundle_item["item_code"]
        item_qty = flt(bundle_item["qty"])
        
        # Skip if this item is a manufacturing item (already handled by BOM)
        default_bom = frappe.db.get_value("Item", item_code, "default_bom")
        if default_bom:
            continue
        
        # This is a stock item that needs to be available
        if item_code in materials_required:
            materials_required[item_code] += item_qty
        else:
            materials_required[item_code] = item_qty
    
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
            
        # Use source warehouse for stock checks
        source_warehouse = get_source_warehouse_for_item(item_code, warehouse)
        available_qty = flt(frappe.db.get_value(
            "Bin",
            {"item_code": item_code, "warehouse": source_warehouse},
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
        
        # Log bundle items specifically
        bundle_items = [item for item in manufacture_items if item.get("is_from_bundle")]
        if bundle_items:
            frappe.logger().info(f"{log_prefix} Found {len(bundle_items)} manufacturable items from bundles")
            for bundle_item in bundle_items:
                frappe.logger().info(f"{log_prefix} Bundle item: {bundle_item['item_code']} (qty: {bundle_item['qty']}) from bundle: {bundle_item.get('bundle_parent', 'N/A')}")

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
        item_code = item_to_mfg["item_code"]
        
        # Calculate total materials required including nested BOMs and bundle items
        materials_required = calculate_total_materials_required(bom_no, qty, item_code)
        
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
    """Get list of manufacturable items from POS invoice, including bundle items"""
    manufacture_items = []
    
    if not doc or not hasattr(doc, 'items') or not doc.items:
        return manufacture_items
    
    for item in doc.items:
        if not item or not hasattr(item, 'item_code'):
            continue
            
        item_code = item.item_code
        item_qty = flt(item.qty)
        warehouse = getattr(item, 'warehouse', '')
        sales_invoice_item = getattr(item, 'name', '')
        
        # Check if this item is a product bundle
        if is_product_bundle(item_code):
            frappe.logger().info(f"🏭 Found product bundle: {item_code} (qty: {item_qty})")
            
            # Expand the bundle to get all constituent items
            bundle_items = expand_product_bundle(item_code, item_qty)
            
            # Get manufacturable items from the bundle
            bundle_manufacturable_items = get_bundle_manufacturable_items(bundle_items)
            
            if bundle_manufacturable_items:
                frappe.logger().info(f"🏭 Found {len(bundle_manufacturable_items)} manufacturable items in bundle {item_code}")
                # Ensure warehouse is set for bundle items
                for bundle_mfg_item in bundle_manufacturable_items:
                    if not bundle_mfg_item.get("warehouse"):
                        bundle_mfg_item["warehouse"] = warehouse
                manufacture_items.extend(bundle_manufacturable_items)
            else:
                frappe.logger().info(f"🏭 No manufacturable items found in bundle {item_code}")
        else:
            # Regular item - check if it has a default BOM
            default_bom = frappe.db.get_value("Item", item_code, "default_bom")
            if default_bom:
                manufacture_items.append({
                    "item_code": item_code,
                    "qty": item_qty,
                    "bom_no": default_bom,
                    "warehouse": warehouse,
                    "sales_invoice_item": sales_invoice_item,
                    "is_from_bundle": False
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
    # This ensures manufactured items are available for the main manufacturing step
    manufactured_items = create_and_submit_nested_manufacturing_entries_sequential(doc, bom_items, item_to_mfg["warehouse"])
    submitted_entries.extend(manufactured_items["entries"])
    
    # Create and submit the main manufacturing entry using manufactured items from previous steps
    main_entries = create_and_submit_main_manufacturing_entry_with_manufactured_items(doc, item_to_mfg, manufactured_items["items"])
    submitted_entries.extend(main_entries)
    
    return submitted_entries

def create_and_submit_nested_manufacturing_entries_sequential(doc, bom_items, warehouse):
    """Create and submit manufacturing entries for nested manufacturing items in sequential order"""
    submitted_entries = []
    manufactured_items = {}  # Track manufactured items and their quantities
    
    # Sort nested items by dependency level (items with no nested dependencies first)
    nested_items = []
    for bom_item in bom_items:
        if bom_item.get("is_manufacturing") and bom_item.get("nested_bom"):
            nested_items.append(bom_item)
    
    # Process nested items in dependency order
    processed_items = set()
    
    while nested_items:
        items_to_process = []
        remaining_items = []
        
        for bom_item in nested_items:
            # Check if this item's dependencies are already processed
            if are_dependencies_processed(bom_item, processed_items, warehouse):
                items_to_process.append(bom_item)
            else:
                remaining_items.append(bom_item)
        
        # Process items that have no remaining dependencies
        for bom_item in items_to_process:
            required_qty = flt(bom_item["qty"])
            
            # Check if we have enough stock using source warehouse
            source_warehouse = get_source_warehouse_for_item(bom_item["item_code"], warehouse)
            available_qty = get_available_stock(bom_item["item_code"], source_warehouse)
            
            if available_qty < required_qty:
                # Create and submit manufacturing entry for this nested item - only the shortage
                nested_item = {
                    "item_code": bom_item["item_code"],
                    "qty": required_qty - available_qty,
                    "bom_no": bom_item["nested_bom"],
                    "warehouse": warehouse,
                    "is_nested": True,
                    "parent_item": bom_item.get("parent_item", "")
                }
                
                # Use the function that can handle manufactured items from previous steps
                entries = create_and_submit_main_manufacturing_entry_with_manufactured_items(doc, nested_item, manufactured_items)
                submitted_entries.extend(entries)
                
                # Track the manufactured item
                manufactured_items[bom_item["item_code"]] = {
                    "qty": required_qty - available_qty,
                    "warehouse": warehouse,
                    "source_warehouse": source_warehouse
                }
                
                # Mark this item as processed
                processed_items.add(bom_item["item_code"])
            
            # Remove from nested_items list
            nested_items.remove(bom_item)
        
        # If no items were processed in this iteration, we have a circular dependency
        if not items_to_process and nested_items:
            frappe.logger().warning(f"🏭 Circular dependency detected in nested manufacturing items: {[item['item_code'] for item in nested_items]}")
            # Process remaining items anyway to avoid infinite loop
            for bom_item in nested_items:
                required_qty = flt(bom_item["qty"])
                source_warehouse = get_source_warehouse_for_item(bom_item["item_code"], warehouse)
                available_qty = get_available_stock(bom_item["item_code"], source_warehouse)
                
                if available_qty < required_qty:
                    nested_item = {
                        "item_code": bom_item["item_code"],
                        "qty": required_qty - available_qty,
                        "bom_no": bom_item["nested_bom"],
                        "warehouse": warehouse,
                        "is_nested": True,
                        "parent_item": bom_item.get("parent_item", "")
                    }
                    
                    # Use the function that can handle manufactured items from previous steps
                    entries = create_and_submit_main_manufacturing_entry_with_manufactured_items(doc, nested_item, manufactured_items)
                    submitted_entries.extend(entries)
                    
                    # Track the manufactured item
                    manufactured_items[bom_item["item_code"]] = {
                        "qty": required_qty - available_qty,
                        "warehouse": warehouse,
                        "source_warehouse": source_warehouse
                    }
            
            break
    
    return {"entries": submitted_entries, "items": manufactured_items}

def create_and_submit_main_manufacturing_entry_with_manufactured_items(doc, item_to_mfg, manufactured_items):
    """Create and immediately submit the main manufacturing entry for an item using manufactured items from previous steps"""
    submitted_entries = []
    
    qty = flt(item_to_mfg["qty"])
    if not qty or qty <= 0:
        return submitted_entries

    # Get appropriate warehouses using new configuration
    target_warehouse = get_target_warehouse_for_item(item_to_mfg["item_code"], item_to_mfg.get("warehouse"))
    source_warehouse = get_source_warehouse_for_item(item_to_mfg["item_code"], item_to_mfg.get("warehouse"))
    
    # Ensure warehouse is set
    if not target_warehouse:
        frappe.logger().error(f"🏭 No target warehouse set for item {item_to_mfg['item_code']}")
        frappe.throw(f"No target warehouse set for item {item_to_mfg['item_code']}. Please set a default warehouse.")

    # Check if this is a nested item or if we need to calculate shortage
    if not item_to_mfg.get("is_nested"):
        # For main items, check available stock and only manufacture shortage
        source_warehouse = get_source_warehouse_for_item(item_to_mfg["item_code"], item_to_mfg.get("warehouse"))
        available_qty = get_available_stock(item_to_mfg["item_code"], source_warehouse)
        if available_qty >= qty:
            # We have enough stock, no need to manufacture
            return submitted_entries
        else:
            # Only manufacture the shortage
            qty = qty - available_qty
            item_to_mfg["qty"] = qty

    try:
        frappe.logger().info(f"🏭 Creating manufacturing entry for {item_to_mfg['item_code']} (qty: {qty}, source warehouse: {source_warehouse}, target warehouse: {target_warehouse})")
        
        # 1. Create and submit the Work Order
        wo = create_work_order(doc, item_to_mfg, submit=True)
        submitted_entries.append(f"Work Order: {wo.name}")

        # 2. Create and submit the Manufacturing Stock Entry with manufactured items
        se = create_manufacturing_stock_entry_with_manufactured_items(doc, item_to_mfg, wo, manufactured_items, submit=True)
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

def create_manufacturing_stock_entry_with_manufactured_items(doc, item_to_mfg, work_order, manufactured_items, submit=True):
    """Create a Manufacturing Stock Entry that uses manufactured items from previous steps"""
    se = frappe.new_doc("Stock Entry")
    se.purpose = "Manufacture"
    # Prevent multi-level BOM explosion to avoid double consumption of nested raw materials
    se.use_multi_level_bom = 0
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

    # Log the manufacturing process
    frappe.logger().info(f"🏭 Creating stock entry for {item_to_mfg['item_code']} with {len(manufactured_items)} manufactured items available")
    frappe.logger().info(f"🏭 Available manufactured items: {list(manufactured_items.keys())}")

    # Modify the stock entry to use manufactured items instead of raw materials
    modified_items = []
    
    for se_item in se.items:
        if se_item.is_finished_item:
            # For finished items, use the target warehouse
            target_warehouse = get_target_warehouse_for_item(se_item.item_code, item_to_mfg["warehouse"])
            se_item.t_warehouse = target_warehouse
            frappe.logger().info(f"🏭 Set target warehouse for finished item {se_item.item_code}: {target_warehouse}")
            modified_items.append(se_item)
        else:
            # Check if this item is a manufactured item from previous steps
            if se_item.item_code in manufactured_items:
                manufactured_item_info = manufactured_items[se_item.item_code]
                
                # Use the manufactured item from the target warehouse where it was produced
                se_item.s_warehouse = manufactured_item_info["warehouse"]
                se_item.qty = manufactured_item_info["qty"]
                
                frappe.logger().info(f"🏭 ✅ Using manufactured item {se_item.item_code} from warehouse {manufactured_item_info['warehouse']} (qty: {manufactured_item_info['qty']})")
                modified_items.append(se_item)
            else:
                # This is a raw material, use source warehouse
                source_warehouse = get_source_warehouse_for_item(se_item.item_code, item_to_mfg["warehouse"])
                se_item.s_warehouse = source_warehouse
                frappe.logger().info(f"🏭 Set source warehouse for raw material {se_item.item_code}: {source_warehouse}")
                modified_items.append(se_item)

    # Replace the items list with modified items
    se.items = modified_items

    # If this is a bundle item, add bundle materials that are not manufacturing items
    if item_to_mfg.get("is_from_bundle") and item_to_mfg.get("bundle_parent"):
        add_bundle_materials_to_stock_entry(se, item_to_mfg)

    # Validate that all items have proper warehouses set
    validate_stock_entry_warehouses(se, item_to_mfg)

    se.from_bom = 1
    se.set_stock_entry_type()
    se.insert(ignore_permissions=True)
    
    if submit:
        se.submit()
    
    return se

def create_work_order(doc, item_to_mfg, submit=True):
    """Create a Work Order"""
    # Get appropriate warehouses using new configuration
    target_warehouse = get_target_warehouse_for_item(item_to_mfg["item_code"], item_to_mfg.get("warehouse"))
    source_warehouse = get_source_warehouse_for_item(item_to_mfg["item_code"], item_to_mfg.get("warehouse"))
    
    # Ensure warehouse is set
    if not target_warehouse:
        frappe.logger().error(f"🏭 No target warehouse set for work order item {item_to_mfg['item_code']}")
        frappe.throw(f"No target warehouse set for work order item {item_to_mfg['item_code']}. Please set a default warehouse.")
    
    wo = frappe.new_doc("Work Order")
    wo.production_item = item_to_mfg["item_code"]
    wo.bom_no = item_to_mfg["bom_no"]
    wo.qty = flt(item_to_mfg["qty"])
    wo.company = doc.company
    wo.fg_warehouse = target_warehouse
    wo.wip_warehouse = source_warehouse
    
    frappe.logger().info(f"🏭 Creating work order for {item_to_mfg['item_code']} with target warehouse: {target_warehouse}, source warehouse: {source_warehouse}")
    
    # Store sales invoice reference and bundle info in description for tracking
    description = f"Auto-generated from Sales Invoice: {doc.name}"
    if item_to_mfg.get("is_from_bundle") and item_to_mfg.get("bundle_parent"):
        description += f" (Bundle: {item_to_mfg['bundle_parent']})"
    wo.description = description
    
    wo.planned_start_date = doc.posting_date
    wo.insert(ignore_permissions=True)
    
    if submit:
        wo.submit()
    
    return wo

def create_manufacturing_stock_entry(doc, item_to_mfg, work_order, submit=True):
    """Create a Manufacturing Stock Entry"""
    se = frappe.new_doc("Stock Entry")
    se.purpose = "Manufacture"
    # Prevent multi-level BOM explosion to avoid double consumption of nested raw materials
    se.use_multi_level_bom = 0
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

    # Set warehouses correctly for all items
    for se_item in se.items:
        if se_item.is_finished_item:
            # For finished items, use the target warehouse
            target_warehouse = get_target_warehouse_for_item(se_item.item_code, item_to_mfg["warehouse"])
            se_item.t_warehouse = target_warehouse
            frappe.logger().info(f"🏭 Set target warehouse for finished item {se_item.item_code}: {target_warehouse}")
        else:
            # For source items, get the appropriate warehouse
            source_warehouse = get_source_warehouse_for_item(se_item.item_code, item_to_mfg["warehouse"])
            se_item.s_warehouse = source_warehouse
            frappe.logger().info(f"🏭 Set source warehouse for {se_item.item_code}: {source_warehouse}")

    # If this is a bundle item, add bundle materials that are not manufacturing items
    if item_to_mfg.get("is_from_bundle") and item_to_mfg.get("bundle_parent"):
        add_bundle_materials_to_stock_entry(se, item_to_mfg)

    # Validate that all items have proper warehouses set
    validate_stock_entry_warehouses(se, item_to_mfg)

    se.from_bom = 1
    se.set_stock_entry_type()
    se.insert(ignore_permissions=True)
    
    if submit:
        se.submit()
    
    return se

def validate_stock_entry_warehouses(stock_entry, item_to_mfg):
    """Validate that all stock entry items have proper warehouses set"""
    try:
        frappe.logger().info(f"🏭 Validating warehouses for stock entry with {len(stock_entry.items)} items")
        
        for idx, se_item in enumerate(stock_entry.items):
            frappe.logger().info(f"🏭 Row {idx + 1}: {se_item.item_code} (finished: {se_item.is_finished_item})")
            
            if not se_item.is_finished_item:
                if not se_item.s_warehouse:
                    frappe.logger().error(f"🏭 Missing source warehouse for item {se_item.item_code} in row {idx + 1}")
                    frappe.throw(f"Source warehouse is mandatory for row {idx + 1} (Item: {se_item.item_code})")
                else:
                    frappe.logger().info(f"🏭 Source warehouse for {se_item.item_code}: {se_item.s_warehouse}")
            
            if se_item.is_finished_item:
                if not se_item.t_warehouse:
                    frappe.logger().error(f"🏭 Missing target warehouse for finished item {se_item.item_code} in row {idx + 1}")
                    frappe.throw(f"Target warehouse is mandatory for finished item in row {idx + 1} (Item: {se_item.item_code})")
                else:
                    frappe.logger().info(f"🏭 Target warehouse for {se_item.item_code}: {se_item.t_warehouse}")
        
        frappe.logger().info(f"🏭 Warehouse validation passed for stock entry")
        
    except Exception as e:
        frappe.logger().error(f"🏭 Warehouse validation failed: {str(e)}")
        raise e

def add_bundle_materials_to_stock_entry(stock_entry, item_to_mfg):
    """Add bundle materials that are not manufacturing items to the stock entry"""
    try:
        bundle_parent = item_to_mfg.get("bundle_parent")
        if not bundle_parent or not is_product_bundle(bundle_parent):
            return
        
        # Get bundle items for this specific manufacturing item
        bundle_items = get_product_bundle_items(bundle_parent)
        
        for bundle_item in bundle_items:
            bundle_item_code = bundle_item["item_code"]
            bundle_item_qty = flt(bundle_item["qty"])
            
            # Skip if this is the manufacturing item itself
            if bundle_item_code == item_to_mfg["item_code"]:
                continue
            
            # Skip if this item is a manufacturing item (handled by BOM)
            default_bom = frappe.db.get_value("Item", bundle_item_code, "default_bom")
            if default_bom:
                continue
            
            # Get warehouse for this bundle item
            warehouse = get_source_warehouse_for_item(bundle_item_code, item_to_mfg["warehouse"])
            
            # Add this bundle item as a source material
            stock_entry.append("items", {
                "item_code": bundle_item_code,
                "qty": bundle_item_qty * flt(item_to_mfg["qty"]),
                "s_warehouse": warehouse,
                "t_warehouse": warehouse,
                "is_finished_item": 0
            })
            
            frappe.logger().info(f"🏭 Added bundle material: {bundle_item_code} (qty: {bundle_item_qty * flt(item_to_mfg['qty'])}) from warehouse: {warehouse}")
            
    except Exception as e:
        frappe.log_error(f"Failed to add bundle materials to stock entry: {str(e)}")

def get_bundle_item_warehouse(item_code, default_warehouse):
    """Get the appropriate warehouse for a bundle item"""
    try:
        frappe.logger().info(f"🏭 Getting warehouse for item {item_code} (default: {default_warehouse})")
        
        # Use the new warehouse configuration system
        source_warehouse = get_source_warehouse_for_item(item_code, default_warehouse)
        
        if source_warehouse:
            frappe.logger().info(f"🏭 Using source warehouse for {item_code}: {source_warehouse}")
            return source_warehouse
        
        # If still no warehouse found, raise an error
        error_msg = f"No warehouse found for item {item_code}. Please set a default warehouse."
        frappe.logger().error(f"🏭 {error_msg}")
        frappe.throw(error_msg)
        
    except Exception as e:
        frappe.log_error(f"🏭 Failed to get warehouse for bundle item {item_code}: {str(e)}")
        # Return the default warehouse as fallback
        if default_warehouse:
            frappe.logger().info(f"🏭 Using fallback default warehouse for {item_code}: {default_warehouse}")
            return default_warehouse
        else:
            frappe.throw(f"Failed to get warehouse for item {item_code}: {str(e)}")

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
        
        # Handle bundle items in the POS invoice
        handle_bundle_cancellation(doc, return_option)
                
    except Exception as e:
        frappe.log_error(f"Failed to cancel manufacturing entries for {doc.name}: {str(e)}")
        frappe.throw(f"Failed to cancel related manufacturing entries: {str(e)}")

def handle_bundle_cancellation(doc, return_option):
    """Handle cancellation for bundle items in the POS invoice"""
    try:
        for item in doc.items:
            item_code = item.item_code
            item_qty = flt(item.qty)
            
            # Check if this is a product bundle
            if is_product_bundle(item_code):
                frappe.logger().info(f"🏭 Handling cancellation for bundle item: {item_code}")
                
                # Expand the bundle to get all constituent items
                bundle_items = expand_product_bundle(item_code, item_qty)
                
                for bundle_item in bundle_items:
                    bundle_item_code = bundle_item["item_code"]
                    bundle_item_qty = flt(bundle_item["qty"])
                    
                    # Check if this bundle item is a manufacturing item
                    default_bom = frappe.db.get_value("Item", bundle_item_code, "default_bom")
                    if default_bom:
                        # Create cancellation entry for manufacturing item
                        if return_option == "Convert to Raw Materials":
                            create_cancellation_manufacturing_entry_for_bundle_item(doc, bundle_item, item)
                        else:
                            create_cancellation_finished_goods_entry_for_bundle_item(doc, bundle_item, item)
                    else:
                        # Create cancellation entry for stock item
                        create_cancellation_stock_item_entry_for_bundle(doc, bundle_item, item)
                        
    except Exception as e:
        frappe.log_error(f"Failed to handle bundle cancellation: {str(e)}")
        frappe.throw(f"Failed to handle bundle cancellation: {str(e)}")

def create_cancellation_manufacturing_entry_for_bundle_item(doc, bundle_item, pos_item):
    """Create cancellation entry for bundle manufacturing items"""
    try:
        item_code = bundle_item["item_code"]
        cancel_qty = flt(bundle_item["qty"])
        
        # Create reverse stock entry to return materials
        se = frappe.new_doc("Stock Entry")
        se.purpose = "Material Transfer"
        se.company = doc.company
        se.posting_date = doc.posting_date
        se.posting_time = doc.posting_time
        se.stock_entry_type = "Material Transfer"
        
        # Get BOM items to reverse
        default_bom = frappe.db.get_value("Item", item_code, "default_bom")
        if default_bom:
            bom_items = frappe.db.get_all(
                "BOM Item",
                filters={"parent": default_bom},
                fields=["item_code", "qty"]
            )
            
            for bom_item in bom_items:
                # Calculate return quantity based on BOM ratio
                return_material_qty = flt(bom_item.qty) * cancel_qty
                
                se.append("items", {
                    "item_code": bom_item.item_code,
                    "qty": return_material_qty,
                    "s_warehouse": pos_item.warehouse,
                    "t_warehouse": pos_item.warehouse
                })
            
            se.insert(ignore_permissions=True)
            se.submit()
            
            frappe.msgprint(f"Created cancellation entry {se.name} for bundle item {item_code}")
        
    except Exception as e:
        frappe.log_error(f"Failed to create cancellation manufacturing entry for bundle item: {str(e)}")
        frappe.throw(f"Failed to create cancellation manufacturing entry for bundle item: {str(e)}")

def create_cancellation_finished_goods_entry_for_bundle_item(doc, bundle_item, pos_item):
    """Create cancellation entry for bundle finished goods"""
    try:
        item_code = bundle_item["item_code"]
        cancel_qty = flt(bundle_item["qty"])
        
        # Create stock entry to return finished goods to warehouse
        se = frappe.new_doc("Stock Entry")
        se.purpose = "Material Transfer"
        se.company = doc.company
        se.posting_date = doc.posting_date
        se.posting_time = doc.posting_time
        se.stock_entry_type = "Material Transfer"
        
        # Add finished goods return
        se.append("items", {
            "item_code": item_code,
            "qty": cancel_qty,
            "s_warehouse": pos_item.warehouse,
            "t_warehouse": pos_item.warehouse
        })
        
        se.insert(ignore_permissions=True)
        se.submit()
        
        frappe.msgprint(f"Created finished goods cancellation entry {se.name} for bundle item {item_code}")
        
    except Exception as e:
        frappe.log_error(f"Failed to create finished goods cancellation entry for bundle item: {str(e)}")
        frappe.throw(f"Failed to create finished goods cancellation entry for bundle item: {str(e)}")

def create_cancellation_stock_item_entry_for_bundle(doc, bundle_item, pos_item):
    """Create cancellation entry for bundle stock items"""
    try:
        item_code = bundle_item["item_code"]
        cancel_qty = flt(bundle_item["qty"])
        
        # Create stock entry to return stock item to warehouse
        se = frappe.new_doc("Stock Entry")
        se.purpose = "Material Transfer"
        se.company = doc.company
        se.posting_date = doc.posting_date
        se.posting_time = doc.posting_time
        se.stock_entry_type = "Material Transfer"
        
        # Add stock item return
        se.append("items", {
            "item_code": item_code,
            "qty": cancel_qty,
            "s_warehouse": pos_item.warehouse,
            "t_warehouse": pos_item.warehouse
        })
        
        se.insert(ignore_permissions=True)
        se.submit()
        
        frappe.msgprint(f"Created stock item cancellation entry {se.name} for bundle item {item_code}")
        
    except Exception as e:
        frappe.log_error(f"Failed to create stock item cancellation entry for bundle: {str(e)}")
        frappe.throw(f"Failed to create stock item cancellation entry for bundle: {str(e)}")

@frappe.whitelist()
def test_bundle_functionality(item_code):
    """
    Test function to verify bundle functionality.
    Call this from the console to test bundle expansion.
    """
    try:
        frappe.logger().info(f"🏭 Testing bundle functionality for item: {item_code}")
        
        # Check if item is a bundle
        is_bundle = is_product_bundle(item_code)
        frappe.logger().info(f"🏭 Is bundle: {is_bundle}")
        
        if is_bundle:
            # Expand the bundle
            expanded_items = expand_product_bundle(item_code, 1)
            frappe.logger().info(f"🏭 Expanded items: {expanded_items}")
            
            # Get manufacturable items
            manufacturable_items = get_bundle_manufacturable_items(expanded_items)
            frappe.logger().info(f"🏭 Manufacturable items: {manufacturable_items}")
            
            # Calculate materials required
            for mfg_item in manufacturable_items:
                materials = calculate_total_materials_required(mfg_item["bom_no"], mfg_item["qty"], mfg_item["item_code"])
                frappe.logger().info(f"🏭 Materials required for {mfg_item['item_code']}: {materials}")
        
        return {
            "is_bundle": is_bundle,
            "expanded_items": expanded_items if is_bundle else [],
            "manufacturable_items": manufacturable_items if is_bundle else []
        }
        
    except Exception as e:
        frappe.logger().error(f"🏭 Bundle test failed: {str(e)}")
        return {"error": str(e)}

@frappe.whitelist()
def debug_warehouse_issues(item_code, warehouse=None):
    """
    Debug function to troubleshoot warehouse issues.
    Call this from the console to get detailed warehouse information.
    """
    try:
        frappe.logger().info(f"🏭 Debugging warehouse issues for item: {item_code}")
        
        company = frappe.defaults.get_global_default("company")
        frappe.logger().info(f"🏭 Company: {company}")
        
        # Check item default warehouse
        item_default_warehouse = frappe.db.get_value(
            "Item Default",
            {"parent": item_code, "company": company},
            "default_warehouse"
        )
        frappe.logger().info(f"🏭 Item default warehouse: {item_default_warehouse}")
        
        # Check company default warehouse
        company_default_warehouse = frappe.db.get_value(
            "Stock Settings",
            None,
            "default_warehouse"
        )
        frappe.logger().info(f"🏭 Company default warehouse: {company_default_warehouse}")
        
        # Check available warehouses
        available_warehouses = frappe.db.get_all(
            "Warehouse",
            filters={"is_group": 0},
            fields=["name", "warehouse_name"]
        )
        frappe.logger().info(f"🏭 Available warehouses: {available_warehouses}")
        
        # Test warehouse assignment
        assigned_warehouse = get_bundle_item_warehouse(item_code, warehouse)
        frappe.logger().info(f"🏭 Assigned warehouse: {assigned_warehouse}")
        
        return {
            "item_code": item_code,
            "company": company,
            "item_default_warehouse": item_default_warehouse,
            "company_default_warehouse": company_default_warehouse,
            "available_warehouses": available_warehouses,
            "assigned_warehouse": assigned_warehouse,
            "provided_warehouse": warehouse
        }
        
    except Exception as e:
        frappe.logger().error(f"🏭 Warehouse debug failed: {str(e)}")
        return {"error": str(e)}

@frappe.whitelist()
def debug_fries_manufacturing_issue():
    """
    Debug function specifically for the Fries manufacturing issue.
    """
    try:
        item_code = "Fries"
        frappe.logger().info(f"🏭 Debugging Fries manufacturing issue")
        
        # Check if Fries is a bundle
        is_bundle = is_product_bundle(item_code)
        frappe.logger().info(f"🏭 Is Fries a bundle: {is_bundle}")
        
        if is_bundle:
            # Expand the bundle
            expanded_items = expand_product_bundle(item_code, 1)
            frappe.logger().info(f"🏭 Expanded Fries bundle items: {expanded_items}")
            
            # Get manufacturable items
            manufacturable_items = get_bundle_manufacturable_items(expanded_items)
            frappe.logger().info(f"🏭 Fries manufacturable items: {manufacturable_items}")
            
            # Check warehouses for each manufacturable item
            for mfg_item in manufacturable_items:
                warehouse_info = debug_warehouse_issues(mfg_item["item_code"], mfg_item.get("warehouse"))
                frappe.logger().info(f"🏭 Warehouse info for {mfg_item['item_code']}: {warehouse_info}")
        
        # Check Fries item details
        fries_details = frappe.db.get_value("Item", item_code, ["item_name", "is_stock_item", "default_bom"], as_dict=True)
        frappe.logger().info(f"🏭 Fries item details: {fries_details}")
        
        return {
            "is_bundle": is_bundle,
            "expanded_items": expanded_items if is_bundle else [],
            "manufacturable_items": manufacturable_items if is_bundle else [],
            "fries_details": fries_details
        }
        
    except Exception as e:
        frappe.logger().error(f"🏭 Fries debug failed: {str(e)}")
        return {"error": str(e)}


@frappe.whitelist()
def test_warehouse_configuration(item_code="Fries"):
    """
    Test function to verify warehouse configuration is working correctly.
    """
    try:
        frappe.logger().info(f"🏭 Testing warehouse configuration for item: {item_code}")
        
        # Test source warehouse configuration
        source_warehouse = get_source_warehouse_for_item(item_code, "Main Store")
        frappe.logger().info(f"🏭 Source warehouse for {item_code}: {source_warehouse}")
        
        # Test target warehouse configuration
        target_warehouse = get_target_warehouse_for_item(item_code, "Main Store")
        frappe.logger().info(f"🏭 Target warehouse for {item_code}: {target_warehouse}")
        
        # Test stock availability
        available_stock = get_available_stock(item_code, "Main Store")
        frappe.logger().info(f"🏭 Available stock for {item_code}: {available_stock}")
        
        # Check settings
        settings = frappe.get_single("POS Auto Manufacture Settings")
        settings_info = {
            "source_warehouse": settings.source_warehouse if settings else "",
            "target_warehouse": settings.target_warehouse if settings else ""
        }
        frappe.logger().info(f"🏭 Settings info: {settings_info}")
        
        return {
            "item_code": item_code,
            "source_warehouse": source_warehouse,
            "target_warehouse": target_warehouse,
            "available_stock": available_stock,
            "settings": settings_info
        }
        
    except Exception as e:
        frappe.logger().error(f"🏭 Warehouse configuration test failed: {str(e)}")
        return {"error": str(e)}

def handle_pos_return(doc):
    """Handle POS return by creating reverse manufacturing entries"""
    try:
        # Get the user's choice for handling manufacturing returns
        return_option = doc.get("manufacturing_return_option", "Convert to Raw Materials")
        
        for item in doc.items:
            if item.qty < 0:  # Return item
                item_code = item.item_code
                return_qty = abs(flt(item.qty))
                
                # Check if this is a product bundle
                if is_product_bundle(item_code):
                    frappe.logger().info(f"🏭 Handling return for bundle item: {item_code}")
                    handle_bundle_return(doc, item, return_option)
                else:
                    # Regular item
                    default_bom = frappe.db.get_value("Item", item_code, "default_bom")
                    if default_bom:
                        if return_option == "Convert to Raw Materials":
                            create_return_manufacturing_entry(doc, item)
                        else:
                            # Keep manufactured product - just return the finished goods
                            create_return_finished_goods_entry(doc, item)
                    
    except Exception as e:
        frappe.log_error(f"Failed to handle POS return for {doc.name}: {str(e)}")
        frappe.throw(f"Failed to handle POS return: {str(e)}")

def handle_bundle_return(doc, return_item, return_option):
    """Handle return for bundle items"""
    try:
        item_code = return_item.item_code
        return_qty = abs(flt(return_item.qty))
        
        # Expand the bundle to get all constituent items
        bundle_items = expand_product_bundle(item_code, return_qty)
        
        for bundle_item in bundle_items:
            bundle_item_code = bundle_item["item_code"]
            bundle_item_qty = flt(bundle_item["qty"])
            
            # Check if this bundle item is a manufacturing item
            default_bom = frappe.db.get_value("Item", bundle_item_code, "default_bom")
            if default_bom:
                # Create return entry for manufacturing item
                if return_option == "Convert to Raw Materials":
                    create_return_manufacturing_entry_for_bundle_item(doc, bundle_item, return_item)
                else:
                    create_return_finished_goods_entry_for_bundle_item(doc, bundle_item, return_item)
            else:
                # Create return entry for stock item
                create_return_stock_item_entry_for_bundle(doc, bundle_item, return_item)
                
    except Exception as e:
        frappe.log_error(f"Failed to handle bundle return: {str(e)}")
        frappe.throw(f"Failed to handle bundle return: {str(e)}")

def create_return_manufacturing_entry_for_bundle_item(doc, bundle_item, return_item):
    """Create reverse manufacturing entry for bundle manufacturing items"""
    try:
        item_code = bundle_item["item_code"]
        return_qty = flt(bundle_item["qty"])
        
        # Create reverse stock entry to return materials
        se = frappe.new_doc("Stock Entry")
        se.purpose = "Material Transfer"
        se.company = doc.company
        se.posting_date = doc.posting_date
        se.posting_time = doc.posting_time
        se.stock_entry_type = "Material Transfer"
        
        # Get BOM items to reverse
        default_bom = frappe.db.get_value("Item", item_code, "default_bom")
        if default_bom:
            bom_items = frappe.db.get_all(
                "BOM Item",
                filters={"parent": default_bom},
                fields=["item_code", "qty"]
            )
            
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
            
            frappe.msgprint(f"Created return entry {se.name} for bundle item {item_code}")
        
    except Exception as e:
        frappe.log_error(f"Failed to create return manufacturing entry for bundle item: {str(e)}")
        frappe.throw(f"Failed to create return manufacturing entry for bundle item: {str(e)}")

def create_return_finished_goods_entry_for_bundle_item(doc, bundle_item, return_item):
    """Create return entry for bundle finished goods"""
    try:
        item_code = bundle_item["item_code"]
        return_qty = flt(bundle_item["qty"])
        
        # Create stock entry to return finished goods to warehouse
        se = frappe.new_doc("Stock Entry")
        se.purpose = "Material Transfer"
        se.company = doc.company
        se.posting_date = doc.posting_date
        se.posting_time = doc.posting_time
        se.stock_entry_type = "Material Transfer"
        
        # Add finished goods return
        se.append("items", {
            "item_code": item_code,
            "qty": return_qty,
            "s_warehouse": return_item.warehouse,
            "t_warehouse": return_item.warehouse
        })
        
        se.insert(ignore_permissions=True)
        se.submit()
        
        frappe.msgprint(f"Created finished goods return entry {se.name} for bundle item {item_code}")
        
    except Exception as e:
        frappe.log_error(f"Failed to create finished goods return entry for bundle item: {str(e)}")
        frappe.throw(f"Failed to create finished goods return entry for bundle item: {str(e)}")

def create_return_stock_item_entry_for_bundle(doc, bundle_item, return_item):
    """Create return entry for bundle stock items"""
    try:
        item_code = bundle_item["item_code"]
        return_qty = flt(bundle_item["qty"])
        
        # Create stock entry to return stock item to warehouse
        se = frappe.new_doc("Stock Entry")
        se.purpose = "Material Transfer"
        se.company = doc.company
        se.posting_date = doc.posting_date
        se.posting_time = doc.posting_time
        se.stock_entry_type = "Material Transfer"
        
        # Add stock item return
        se.append("items", {
            "item_code": item_code,
            "qty": return_qty,
            "s_warehouse": return_item.warehouse,
            "t_warehouse": return_item.warehouse
        })
        
        se.insert(ignore_permissions=True)
        se.submit()
        
        frappe.msgprint(f"Created stock item return entry {se.name} for bundle item {item_code}")
        
    except Exception as e:
        frappe.log_error(f"Failed to create stock item return entry for bundle: {str(e)}")
        frappe.throw(f"Failed to create stock item return entry for bundle: {str(e)}")

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

def get_source_warehouse_for_item(item_code, default_warehouse=None):
    """Get source warehouse for an item (raw materials)"""
    try:
        # Get source warehouse directly from settings without importing
        settings = frappe.get_single("POS Auto Manufacture Settings")
        source_warehouse = settings.source_warehouse if settings else ""
        
        if source_warehouse:
            return source_warehouse
        
        # Fallback to item's default warehouse
        if default_warehouse:
            return default_warehouse
        
        # Fallback to company default warehouse
        company = frappe.defaults.get_global_default("company")
        if company:
            company_warehouse = frappe.db.get_value("Company", company, "default_warehouse")
            if company_warehouse:
                return company_warehouse
        
        return None
    except Exception as e:
        frappe.log_error(f"Error getting source warehouse for item {item_code}: {str(e)}")
        return default_warehouse


def get_target_warehouse_for_item(item_code, default_warehouse=None):
    """Get target warehouse for an item (finished products)"""
    try:
        # Get target warehouse directly from settings without importing
        settings = frappe.get_single("POS Auto Manufacture Settings")
        target_warehouse = settings.target_warehouse if settings else ""
        
        if target_warehouse:
            return target_warehouse
        
        # Fallback to item's default warehouse
        if default_warehouse:
            return default_warehouse
        
        # Fallback to company default warehouse
        company = frappe.defaults.get_global_default("company")
        if company:
            company_warehouse = frappe.db.get_value("Company", company, "default_warehouse")
            if company_warehouse:
                return company_warehouse
        
        return None
    except Exception as e:
        frappe.log_error(f"Error getting target warehouse for item {item_code}: {str(e)}")
        return default_warehouse

def create_and_submit_nested_manufacturing_entries(doc, bom_items, warehouse):
    """Create and submit manufacturing entries for nested manufacturing items"""
    submitted_entries = []
    
    for bom_item in bom_items:
        if bom_item.get("is_manufacturing") and bom_item.get("nested_bom"):
            # Calculate required quantity based on BOM ratio
            required_qty = flt(bom_item["qty"])
            
            # Check if we have enough stock using source warehouse
            source_warehouse = get_source_warehouse_for_item(bom_item["item_code"], warehouse)
            available_qty = get_available_stock(bom_item["item_code"], source_warehouse)
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

def create_and_submit_main_manufacturing_entry(doc, item_to_mfg):
    """Create and immediately submit the main manufacturing entry for an item"""
    submitted_entries = []
    
    qty = flt(item_to_mfg["qty"])
    if not qty or qty <= 0:
        return submitted_entries

    # Get appropriate warehouses using new configuration
    target_warehouse = get_target_warehouse_for_item(item_to_mfg["item_code"], item_to_mfg.get("warehouse"))
    source_warehouse = get_source_warehouse_for_item(item_to_mfg["item_code"], item_to_mfg.get("warehouse"))
    
    # Ensure warehouse is set
    if not target_warehouse:
        frappe.logger().error(f"🏭 No target warehouse set for item {item_to_mfg['item_code']}")
        frappe.throw(f"No target warehouse set for item {item_to_mfg['item_code']}. Please set a default warehouse.")

    # Check if this is a nested item or if we need to calculate shortage
    if not item_to_mfg.get("is_nested"):
        # For main items, check available stock and only manufacture shortage
        source_warehouse = get_source_warehouse_for_item(item_to_mfg["item_code"], item_to_mfg.get("warehouse"))
        available_qty = get_available_stock(item_to_mfg["item_code"], source_warehouse)
        if available_qty >= qty:
            # We have enough stock, no need to manufacture
            return submitted_entries
        else:
            # Only manufacture the shortage
            qty = qty - available_qty
            item_to_mfg["qty"] = qty

    try:
        frappe.logger().info(f"🏭 Creating manufacturing entry for {item_to_mfg['item_code']} (qty: {qty}, source warehouse: {source_warehouse}, target warehouse: {target_warehouse})")
        
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

def get_available_stock(item_code, warehouse):
    """Get available stock for an item in a warehouse"""
    # Use source warehouse for stock checks
    source_warehouse = get_source_warehouse_for_item(item_code, warehouse)
    return flt(frappe.db.get_value(
        "Bin",
        {"item_code": item_code, "warehouse": source_warehouse},
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
        source_warehouse = get_source_warehouse_for_item(item_to_mfg["item_code"], item_to_mfg.get("warehouse"))
        available_qty = get_available_stock(item_to_mfg["item_code"], source_warehouse)
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

def are_dependencies_processed(bom_item, processed_items, warehouse):
    """Check if all dependencies for a nested manufacturing item are processed"""
    try:
        # Get the BOM for this nested item
        nested_bom = bom_item.get("nested_bom")
        if not nested_bom:
            return True
        
        # Get BOM items for this nested item
        nested_bom_items = frappe.db.get_all(
            "BOM Item",
            filters={"parent": nested_bom},
            fields=["item_code", "qty"]
        )
        
        for nested_bom_item in nested_bom_items:
            nested_item_code = nested_bom_item["item_code"]
            
            # Check if this nested item is itself a manufacturing item
            is_manufacturing = frappe.db.get_value("Item", nested_item_code, "default_bom") is not None
            
            if is_manufacturing:
                # This is a manufacturing dependency, check if it's processed
                if nested_item_code not in processed_items:
                    return False
                
                # Also check if we have enough stock of this manufactured item
                source_warehouse = get_source_warehouse_for_item(nested_item_code, warehouse)
                available_qty = get_available_stock(nested_item_code, source_warehouse)
                required_qty = flt(nested_bom_item["qty"]) * flt(bom_item["qty"])
                
                if available_qty < required_qty:
                    return False
        
        return True
        
    except Exception as e:
        frappe.logger().error(f"🏭 Error checking dependencies for {bom_item['item_code']}: {str(e)}")
        return True  # Assume dependencies are processed to avoid blocking

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
            
            # Check if we have enough stock using source warehouse
            source_warehouse = get_source_warehouse_for_item(bom_item["item_code"], warehouse)
            available_qty = get_available_stock(bom_item["item_code"], source_warehouse)
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

@frappe.whitelist()
def debug_sequential_manufacturing(item_code="Loaded Fries"):
    """
    Debug function to test sequential manufacturing logic.
    This will help identify issues with the nested manufacturing process.
    """
    try:
        frappe.logger().info(f"🏭 Debugging sequential manufacturing for item: {item_code}")
        
        # Get the BOM for the item
        default_bom = frappe.db.get_value("Item", item_code, "default_bom")
        if not default_bom:
            return {"error": f"No BOM found for item {item_code}"}
        
        frappe.logger().info(f"🏭 BOM for {item_code}: {default_bom}")
        
        # Get BOM items with nested manufacturing
        bom_items = get_bom_items_with_nested_manufacturing(default_bom)
        frappe.logger().info(f"🏭 BOM items with nested manufacturing: {bom_items}")
        
        # Simulate the sequential manufacturing process
        warehouse = "Main Store"  # Default warehouse
        manufactured_items = {}
        processed_items = set()
        
        # Process nested items in dependency order
        nested_items = [item for item in bom_items if item.get("is_manufacturing")]
        
        frappe.logger().info(f"🏭 Nested manufacturing items: {[item['item_code'] for item in nested_items]}")
        
        while nested_items:
            items_to_process = []
            remaining_items = []
            
            for bom_item in nested_items:
                if are_dependencies_processed(bom_item, processed_items, warehouse):
                    items_to_process.append(bom_item)
                else:
                    remaining_items.append(bom_item)
            
            frappe.logger().info(f"🏭 Items to process in this iteration: {[item['item_code'] for item in items_to_process]}")
            frappe.logger().info(f"🏭 Remaining items: {[item['item_code'] for item in remaining_items]}")
            
            for bom_item in items_to_process:
                required_qty = flt(bom_item["qty"])
                source_warehouse = get_source_warehouse_for_item(bom_item["item_code"], warehouse)
                available_qty = get_available_stock(bom_item["item_code"], source_warehouse)
                
                frappe.logger().info(f"🏭 Processing {bom_item['item_code']}: required={required_qty}, available={available_qty}")
                
                if available_qty < required_qty:
                    manufactured_qty = required_qty - available_qty
                    manufactured_items[bom_item["item_code"]] = {
                        "qty": manufactured_qty,
                        "warehouse": warehouse,
                        "source_warehouse": source_warehouse
                    }
                    frappe.logger().info(f"🏭 Will manufacture {manufactured_qty} of {bom_item['item_code']}")
                
                processed_items.add(bom_item["item_code"])
                nested_items.remove(bom_item)
            
            if not items_to_process and nested_items:
                frappe.logger().warning(f"🏭 Circular dependency detected")
                break
        
        frappe.logger().info(f"🏭 Final manufactured items: {manufactured_items}")
        
        # Check what would be used in the main manufacturing step
        main_manufacturing_analysis = analyze_main_manufacturing_step(default_bom, manufactured_items, warehouse)
        
        return {
            "item_code": item_code,
            "bom_no": default_bom,
            "bom_items": bom_items,
            "nested_items": [item['item_code'] for item in bom_items if item.get("is_manufacturing")],
            "manufactured_items": manufactured_items,
            "main_manufacturing_analysis": main_manufacturing_analysis
        }
        
    except Exception as e:
        frappe.logger().error(f"🏭 Sequential manufacturing debug failed: {str(e)}")
        return {"error": str(e)}

def analyze_main_manufacturing_step(bom_no, manufactured_items, warehouse):
    """Analyze what would be used in the main manufacturing step"""
    try:
        bom_items = frappe.db.get_all(
            "BOM Item",
            filters={"parent": bom_no},
            fields=["item_code", "qty"]
        )
        
        analysis = {
            "raw_materials": [],
            "manufactured_materials": [],
            "total_materials": len(bom_items)
        }
        
        for bom_item in bom_items:
            item_code = bom_item["item_code"]
            qty = flt(bom_item["qty"])
            
            if item_code in manufactured_items:
                analysis["manufactured_materials"].append({
                    "item_code": item_code,
                    "qty": qty,
                    "source": "manufactured",
                    "manufactured_qty": manufactured_items[item_code]["qty"]
                })
            else:
                # Check if this is a raw material
                source_warehouse = get_source_warehouse_for_item(item_code, warehouse)
                available_qty = get_available_stock(item_code, source_warehouse)
                
                analysis["raw_materials"].append({
                    "item_code": item_code,
                    "qty": qty,
                    "source": "raw_material",
                    "available_qty": available_qty
                })
        
        return analysis
        
    except Exception as e:
        frappe.logger().error(f"🏭 Error analyzing main manufacturing step: {str(e)}")
        return {"error": str(e)}

@frappe.whitelist()
def test_fries_sequential_manufacturing():
    """
    Test function specifically for the Fries sequential manufacturing issue.
    This will verify that the fix works correctly.
    """
    try:
        frappe.logger().info(f"🏭 Testing Fries sequential manufacturing fix")
        
        # Test scenario: Loaded Fries requires Fries (manufactured) + Chicken (raw)
        # Fries requires Potato (raw) + Mix-Flour (raw)
        
        # Step 1: Test the sequential manufacturing logic
        result = debug_sequential_manufacturing("Loaded Fries")
        
        if "error" in result:
            frappe.logger().error(f"🏭 Error in sequential manufacturing test: {result['error']}")
            return result
        
        frappe.logger().info(f"🏭 Sequential manufacturing test result: {result}")
        
        # Step 2: Verify that Fries is identified as a manufactured item
        manufactured_items = result.get("manufactured_items", {})
        if "Fries" in manufactured_items:
            frappe.logger().info(f"🏭 ✅ Fries correctly identified as manufactured item: {manufactured_items['Fries']}")
        else:
            frappe.logger().warning(f"🏭 ⚠️ Fries not identified as manufactured item")
        
        # Step 3: Verify that the main manufacturing step will use manufactured Fries
        main_analysis = result.get("main_manufacturing_analysis", {})
        manufactured_materials = main_analysis.get("manufactured_materials", [])
        
        fries_in_manufactured = False
        for material in manufactured_materials:
            if material["item_code"] == "Fries":
                fries_in_manufactured = True
                frappe.logger().info(f"🏭 ✅ Fries correctly identified as manufactured material in main step: {material}")
                break
        
        if not fries_in_manufactured:
            frappe.logger().warning(f"🏭 ⚠️ Fries not identified as manufactured material in main step")
        
        # Step 4: Check raw materials
        raw_materials = main_analysis.get("raw_materials", [])
        chicken_found = False
        for material in raw_materials:
            if material["item_code"] == "Chicken":
                chicken_found = True
                frappe.logger().info(f"🏭 ✅ Chicken correctly identified as raw material: {material}")
                break
        
        if not chicken_found:
            frappe.logger().warning(f"🏭 ⚠️ Chicken not found in raw materials")
        
        # Summary
        summary = {
            "test_passed": True,
            "fries_manufactured": "Fries" in manufactured_items,
            "fries_used_in_main": fries_in_manufactured,
            "chicken_raw_material": chicken_found,
            "manufactured_items_count": len(manufactured_items),
            "raw_materials_count": len(raw_materials)
        }
        
        frappe.logger().info(f"🏭 Test summary: {summary}")
        
        return {
            "test_result": result,
            "summary": summary,
            "status": "Test completed successfully"
        }
        
    except Exception as e:
        frappe.logger().error(f"🏭 Fries sequential manufacturing test failed: {str(e)}")
        return {"error": str(e)}

@frappe.whitelist()
def test_sequential_manufacturing_fix():
    """
    Test function to verify the sequential manufacturing fix is working correctly.
    This will simulate the Fries -> Loaded Fries manufacturing process.
    """
    try:
        frappe.logger().info(f"🏭 Testing sequential manufacturing fix")
        
        # Test scenario: Loaded Fries requires Fries (manufactured) + Chicken (raw)
        # Fries requires Potato (raw) + Mix-Flour (raw)
        
        # Step 1: Test the sequential manufacturing logic
        result = debug_sequential_manufacturing("Loaded Fries")
        
        if "error" in result:
            frappe.logger().error(f"🏭 Error in sequential manufacturing test: {result['error']}")
            return result
        
        frappe.logger().info(f"🏭 Sequential manufacturing test result: {result}")
        
        # Step 2: Verify that Fries is identified as a manufactured item
        manufactured_items = result.get("manufactured_items", {})
        if "Fries" in manufactured_items:
            frappe.logger().info(f"🏭 ✅ Fries correctly identified as manufactured item: {manufactured_items['Fries']}")
        else:
            frappe.logger().warning(f"🏭 ⚠️ Fries not identified as manufactured item")
        
        # Step 3: Verify that the main manufacturing step will use manufactured Fries
        main_analysis = result.get("main_manufacturing_analysis", {})
        manufactured_materials = main_analysis.get("manufactured_materials", [])
        
        fries_in_manufactured = False
        for material in manufactured_materials:
            if material["item_code"] == "Fries":
                fries_in_manufactured = True
                frappe.logger().info(f"🏭 ✅ Fries correctly identified as manufactured material in main step: {material}")
                break
        
        if not fries_in_manufactured:
            frappe.logger().warning(f"🏭 ⚠️ Fries not identified as manufactured material in main step")
        
        # Step 4: Check raw materials
        raw_materials = main_analysis.get("raw_materials", [])
        chicken_found = False
        for material in raw_materials:
            if material["item_code"] == "Chicken":
                chicken_found = True
                frappe.logger().info(f"🏭 ✅ Chicken correctly identified as raw material: {material}")
                break
        
        if not chicken_found:
            frappe.logger().warning(f"🏭 ⚠️ Chicken not found in raw materials")
        
        # Step 5: Check that Potato and Mix-Flour are NOT in raw materials for Loaded Fries
        potato_in_raw = False
        mix_flour_in_raw = False
        for material in raw_materials:
            if material["item_code"] == "Potato":
                potato_in_raw = True
                frappe.logger().warning(f"🏭 ⚠️ Potato incorrectly found in raw materials for Loaded Fries: {material}")
            elif material["item_code"] == "Mix-Flour":
                mix_flour_in_raw = True
                frappe.logger().warning(f"🏭 ⚠️ Mix-Flour incorrectly found in raw materials for Loaded Fries: {material}")
        
        if not potato_in_raw and not mix_flour_in_raw:
            frappe.logger().info(f"🏭 ✅ Potato and Mix-Flour correctly NOT in raw materials for Loaded Fries")
        
        # Summary
        summary = {
            "test_passed": True,
            "fries_manufactured": "Fries" in manufactured_items,
            "fries_used_in_main": fries_in_manufactured,
            "chicken_raw_material": chicken_found,
            "potato_not_in_raw": not potato_in_raw,
            "mix_flour_not_in_raw": not mix_flour_in_raw,
            "manufactured_items_count": len(manufactured_items),
            "raw_materials_count": len(raw_materials)
        }
        
        frappe.logger().info(f"🏭 Test summary: {summary}")
        
        # Check if the fix is working
        fix_working = (
            summary["fries_manufactured"] and 
            summary["fries_used_in_main"] and 
            summary["chicken_raw_material"] and 
            summary["potato_not_in_raw"] and 
            summary["mix_flour_not_in_raw"]
        )
        
        if fix_working:
            frappe.logger().info(f"🏭 ✅ Sequential manufacturing fix is working correctly!")
        else:
            frappe.logger().warning(f"🏭 ⚠️ Sequential manufacturing fix may have issues")
        
        return {
            "test_result": result,
            "summary": summary,
            "fix_working": fix_working,
            "status": "Test completed successfully"
        }
        
    except Exception as e:
        frappe.logger().error(f"🏭 Sequential manufacturing fix test failed: {str(e)}")
        return {"error": str(e)}

@frappe.whitelist()
def debug_current_manufacturing_state():
    """
    Debug function to check the current state of manufacturing logic.
    This will help identify where the double consumption is happening.
    """
    try:
        frappe.logger().info(f"🏭 Debugging current manufacturing state")
        
        # Check Loaded Fries BOM
        loaded_fries_bom = frappe.db.get_value("Item", "Loaded Fries", "default_bom")
        if loaded_fries_bom:
            bom_items = frappe.db.get_all(
                "BOM Item",
                filters={"parent": loaded_fries_bom},
                fields=["item_code", "qty"]
            )
            frappe.logger().info(f"🏭 Loaded Fries BOM items: {bom_items}")
            
            # Check which items are manufacturing items
            for item in bom_items:
                is_manufacturing = frappe.db.get_value("Item", item["item_code"], "default_bom") is not None
                frappe.logger().info(f"🏭 {item['item_code']}: is_manufacturing = {is_manufacturing}")
                
                if is_manufacturing:
                    nested_bom = frappe.db.get_value("Item", item["item_code"], "default_bom")
                    nested_items = frappe.db.get_all(
                        "BOM Item",
                        filters={"parent": nested_bom},
                        fields=["item_code", "qty"]
                    )
                    frappe.logger().info(f"🏭 {item['item_code']} nested BOM items: {nested_items}")
        
        # Check Fries BOM
        fries_bom = frappe.db.get_value("Item", "Fries", "default_bom")
        if fries_bom:
            fries_bom_items = frappe.db.get_all(
                "BOM Item",
                filters={"parent": fries_bom},
                fields=["item_code", "qty"]
            )
            frappe.logger().info(f"🏭 Fries BOM items: {fries_bom_items}")
        
        # Test the sequential manufacturing logic
        result = debug_sequential_manufacturing("Loaded Fries")
        
        return {
            "loaded_fries_bom": loaded_fries_bom,
            "fries_bom": fries_bom,
            "sequential_result": result
        }
        
    except Exception as e:
        frappe.logger().error(f"🏭 Debug failed: {str(e)}")
        return {"error": str(e)}

