#!/usr/bin/env python3
"""
Test script to verify warehouse changes in POS Auto Manufacture app
"""

import frappe
import sys
import os

def test_warehouse_settings():
    """Test the new warehouse settings functionality"""
    print("Testing warehouse settings...")
    
    try:
        # Test getting settings
        from pos_auto_manufacture.utils.settings import get_source_warehouse, get_target_warehouse
        
        source_warehouse = get_source_warehouse()
        target_warehouse = get_target_warehouse()
        
        print(f"Source warehouse from settings: {source_warehouse}")
        print(f"Target warehouse from settings: {target_warehouse}")
        
        return True
        
    except Exception as e:
        print(f"Error testing warehouse settings: {str(e)}")
        return False

def test_stock_checker():
    """Test the stock checker with source warehouse"""
    print("Testing stock checker...")
    
    try:
        from pos_auto_manufacture.api.stock_checker import check_bom_stock_levels
        
        # Test with a sample item (you may need to adjust this)
        result = check_bom_stock_levels("Fries", 1)
        print(f"Stock checker result: {result}")
        
        return True
        
    except Exception as e:
        print(f"Error testing stock checker: {str(e)}")
        return False

def test_warehouse_functions():
    """Test the warehouse utility functions"""
    print("Testing warehouse functions...")
    
    try:
        from pos_auto_manufacture.pos_auto_manufacture.pos_auto_manufacture import (
            get_source_warehouse_for_item, 
            get_target_warehouse_for_item
        )
        
        # Test warehouse functions
        source_warehouse = get_source_warehouse_for_item("Fries", "Main Store")
        target_warehouse = get_target_warehouse_for_item("Fries", "Main Store")
        
        print(f"Source warehouse for Fries: {source_warehouse}")
        print(f"Target warehouse for Fries: {target_warehouse}")
        
        return True
        
    except Exception as e:
        print(f"Error testing warehouse functions: {str(e)}")
        return False

def main():
    """Main test function"""
    print("Starting warehouse changes test...")
    
    tests = [
        ("Warehouse Settings", test_warehouse_settings),
        ("Stock Checker", test_stock_checker),
        ("Warehouse Functions", test_warehouse_functions)
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n--- Testing {test_name} ---")
        if test_func():
            print(f"✅ {test_name} passed")
            passed += 1
        else:
            print(f"❌ {test_name} failed")
    
    print(f"\n--- Test Summary ---")
    print(f"Passed: {passed}/{total}")
    
    if passed == total:
        print("🎉 All tests passed!")
        return 0
    else:
        print("⚠️  Some tests failed!")
        return 1

if __name__ == "__main__":
    sys.exit(main()) 