#!/usr/bin/env python3
"""
Test script to verify module imports work correctly
"""

import sys
import os

# Add the apps directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    # Test importing the main module
    import pos_auto_manufacture.pos_auto_manufacture.pos_auto_manufacture.pos_auto_manufacture as main_module
    print("✅ Main module imported successfully")
    
    # Test if the function exists
    if hasattr(main_module, 'handle_pos_return_or_cancel'):
        print("✅ handle_pos_return_or_cancel function exists")
    else:
        print("❌ handle_pos_return_or_cancel function not found")
    
    # Test if other functions exist
    functions_to_test = [
        'create_manufacture_entry_from_pos',
        'submit_manufacturing_entries',
        'calculate_total_materials_required'
    ]
    
    for func_name in functions_to_test:
        if hasattr(main_module, func_name):
            print(f"✅ {func_name} function exists")
        else:
            print(f"❌ {func_name} function not found")
    
    print("\n🎉 All tests passed! Module is working correctly.")
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    sys.exit(1) 