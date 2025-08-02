#!/usr/bin/env python3
"""
Test script for POS Auto Manufacture functionality
This script demonstrates the various features of the POS auto-manufacture system
"""

import frappe
from frappe.utils import flt, now_datetime

def test_basic_manufacturing():
    """Test basic manufacturing functionality"""
    print("🧪 Testing Basic Manufacturing...")
    
    # Create a test POS invoice
    pos_invoice = create_test_pos_invoice()
    
    # Submit the invoice to trigger manufacturing
    # The system will prepare entries during validation and submit them after
    pos_invoice.submit()
    
    print(f"✅ Created POS Invoice: {pos_invoice.name}")
    print(f"📋 Work Orders created: {get_related_work_orders(pos_invoice.name)}")
    print(f"📦 Stock Entries created: {get_related_stock_entries(pos_invoice.name)}")

def test_nested_bom_manufacturing():
    """Test nested BOM manufacturing"""
    print("\n🧪 Testing Nested BOM Manufacturing...")
    
    # Create test items with nested BOMs
    create_nested_bom_items()
    
    # Create POS invoice with final product
    pos_invoice = create_test_pos_invoice_with_nested_bom()
    pos_invoice.submit()
    
    print(f"✅ Created POS Invoice with Nested BOM: {pos_invoice.name}")
    print(f"📋 Nested Work Orders: {get_nested_work_orders(pos_invoice.name)}")

def test_return_handling():
    """Test return handling functionality"""
    print("\n🧪 Testing Return Handling...")
    
    # Create a return POS invoice
    return_invoice = create_test_return_invoice()
    return_invoice.submit()
    
    print(f"✅ Created Return Invoice: {return_invoice.name}")
    print(f"🔄 Reverse entries created: {get_reverse_entries(return_invoice.name)}")

def test_cancellation_handling():
    """Test cancellation handling"""
    print("\n🧪 Testing Cancellation Handling...")
    
    # Create and submit a POS invoice
    pos_invoice = create_test_pos_invoice()
    pos_invoice.submit()
    
    # Cancel the invoice
    pos_invoice.cancel()
    
    print(f"✅ Cancelled POS Invoice: {pos_invoice.name}")
    print(f"❌ Cancelled Work Orders: {get_cancelled_work_orders(pos_invoice.name)}")
    print(f"❌ Cancelled Stock Entries: {get_cancelled_stock_entries(pos_invoice.name)}")

def test_wastage_tracking():
    """Test wastage tracking functionality"""
    print("\n🧪 Testing Wastage Tracking...")
    
    # Create manufacturing stock entry with wastage
    stock_entry = create_test_manufacturing_stock_entry_with_wastage()
    stock_entry.submit()
    
    print(f"✅ Created Stock Entry with Wastage: {stock_entry.name}")
    print(f"📊 Wastage tracked: {get_wastage_entries(stock_entry.name)}")

def create_test_pos_invoice():
    """Create a test POS invoice"""
    pos_invoice = frappe.new_doc("Sales Invoice")
    pos_invoice.is_pos = 1
    pos_invoice.company = frappe.defaults.get_global_default("company")
    pos_invoice.posting_date = now_datetime().date()
    pos_invoice.posting_time = now_datetime().time()
    
    # Add a manufacturable item
    pos_invoice.append("items", {
        "item_code": "Test-Manufacturable-Item",
        "qty": 10,
        "rate": 100,
        "warehouse": "Stores - Test Company"
    })
    
    pos_invoice.insert()
    return pos_invoice

def create_test_pos_invoice_with_nested_bom():
    """Create a test POS invoice with nested BOM"""
    pos_invoice = frappe.new_doc("Sales Invoice")
    pos_invoice.is_pos = 1
    pos_invoice.company = frappe.defaults.get_global_default("company")
    pos_invoice.posting_date = now_datetime().date()
    pos_invoice.posting_time = now_datetime().time()
    
    # Add a final product that requires nested manufacturing
    pos_invoice.append("items", {
        "item_code": "Test-Final-Product",
        "qty": 5,
        "rate": 200,
        "warehouse": "Stores - Test Company"
    })
    
    pos_invoice.insert()
    return pos_invoice

def create_test_return_invoice():
    """Create a test return POS invoice"""
    return_invoice = frappe.new_doc("Sales Invoice")
    return_invoice.is_pos = 1
    return_invoice.is_return = 1
    return_invoice.company = frappe.defaults.get_global_default("company")
    return_invoice.posting_date = now_datetime().date()
    return_invoice.posting_time = now_datetime().time()
    
    # Add returned items (negative quantities)
    return_invoice.append("items", {
        "item_code": "Test-Manufacturable-Item",
        "qty": -2,  # Negative for return
        "rate": 100,
        "warehouse": "Stores - Test Company"
    })
    
    return_invoice.insert()
    return return_invoice

def create_nested_bom_items():
    """Create test items with nested BOMs"""
    # Create raw materials
    create_item_if_not_exists("Raw-Material-1", "Raw Material")
    create_item_if_not_exists("Raw-Material-2", "Raw Material")
    
    # Create sub-assembly (manufacturing item)
    create_item_if_not_exists("Sub-Assembly-1", "Product")
    
    # Create BOM for sub-assembly
    create_bom_if_not_exists("Sub-Assembly-1", [
        {"item_code": "Raw-Material-1", "qty": 2},
        {"item_code": "Raw-Material-2", "qty": 1}
    ])
    
    # Create final product
    create_item_if_not_exists("Test-Final-Product", "Product")
    
    # Create BOM for final product
    create_bom_if_not_exists("Test-Final-Product", [
        {"item_code": "Sub-Assembly-1", "qty": 1},
        {"item_code": "Raw-Material-1", "qty": 1}
    ])

def create_test_manufacturing_stock_entry_with_wastage():
    """Create a test manufacturing stock entry with wastage"""
    stock_entry = frappe.new_doc("Stock Entry")
    stock_entry.purpose = "Manufacture"
    stock_entry.company = frappe.defaults.get_global_default("company")
    stock_entry.posting_date = now_datetime().date()
    stock_entry.posting_time = now_datetime().time()
    stock_entry.fg_completed_qty = 10
    
    # Add materials consumed (with excess for wastage)
    stock_entry.append("items", {
        "item_code": "Raw-Material-1",
        "qty": 25,  # More than BOM requirement
        "s_warehouse": "Stores - Test Company",
        "is_finished_item": 0
    })
    
    # Add finished goods
    stock_entry.append("items", {
        "item_code": "Test-Manufacturable-Item",
        "qty": 10,
        "t_warehouse": "Stores - Test Company",
        "is_finished_item": 1
    })
    
    stock_entry.insert()
    return stock_entry

def create_item_if_not_exists(item_code, item_group):
    """Create an item if it doesn't exist"""
    if not frappe.db.exists("Item", item_code):
        item = frappe.new_doc("Item")
        item.item_code = item_code
        item.item_name = item_code
        item.item_group = item_group
        item.stock_uom = "Nos"
        item.insert()

def create_bom_if_not_exists(item_code, bom_items):
    """Create a BOM if it doesn't exist"""
    if not frappe.db.exists("BOM", {"item": item_code, "is_default": 1}):
        bom = frappe.new_doc("BOM")
        bom.item = item_code
        bom.is_default = 1
        bom.quantity = 1
        
        for bom_item in bom_items:
            bom.append("items", {
                "item_code": bom_item["item_code"],
                "qty": bom_item["qty"]
            })
        
        bom.insert()
        bom.submit()

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

def get_nested_work_orders(sales_invoice):
    """Get nested work orders for a sales invoice"""
    work_orders = get_related_work_orders(sales_invoice)
    nested_orders = []
    
    for wo in work_orders:
        # Check if this work order has nested work orders
        nested = frappe.db.get_all(
            "Work Order",
            filters={"description": ["like", f"%{sales_invoice}%"], "production_item": ["!=", wo.production_item]},
            fields=["name", "production_item", "qty"]
        )
        nested_orders.extend(nested)
    
    return nested_orders

def get_reverse_entries(return_invoice):
    """Get reverse entries created for returns"""
    return frappe.db.get_all(
        "Stock Entry",
        filters={"purpose": "Material Transfer", "posting_date": frappe.get_doc("Sales Invoice", return_invoice).posting_date},
        fields=["name", "purpose"]
    )

def get_cancelled_work_orders(sales_invoice):
    """Get cancelled work orders"""
    return frappe.db.get_all(
        "Work Order",
        filters={"description": ["like", f"%{sales_invoice}%"], "docstatus": 2},
        fields=["name", "production_item"]
    )

def get_cancelled_stock_entries(sales_invoice):
    """Get cancelled stock entries"""
    work_orders = [wo.name for wo in get_related_work_orders(sales_invoice)]
    if work_orders:
        return frappe.db.get_all(
            "Stock Entry",
            filters={"work_order": ["in", work_orders], "docstatus": 2},
            fields=["name", "purpose"]
        )
    return []

def get_wastage_entries(stock_entry):
    """Get wastage entries related to a stock entry"""
    return frappe.db.get_all(
        "Stock Entry",
        filters={"purpose": "Material Transfer", "posting_date": frappe.get_doc("Stock Entry", stock_entry).posting_date},
        fields=["name", "purpose"]
    )

def run_all_tests():
    """Run all tests"""
    print("🚀 Starting POS Auto Manufacture Tests...\n")
    
    try:
        test_basic_manufacturing()
        test_nested_bom_manufacturing()
        test_return_handling()
        test_cancellation_handling()
        test_wastage_tracking()
        
        print("\n✅ All tests completed successfully!")
        
    except Exception as e:
        print(f"\n❌ Test failed: {str(e)}")
        frappe.log_error(f"POS Auto Manufacture Test Failed: {str(e)}")

if __name__ == "__main__":
    run_all_tests() 