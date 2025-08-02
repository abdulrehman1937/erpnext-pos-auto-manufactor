#!/usr/bin/env python3
"""
Test script to verify the handle_pos_return_or_cancel function exists
"""

import sys
import os

# Add the apps directory to the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

try:
    # Test importing the module
    import pos_auto_manufacture.pos_auto_manufacture.pos_auto_manufacture.pos_auto_manufacture as main_module
    print("✅ Module imported successfully")
    
    # Test if the function exists
    if hasattr(main_module, 'handle_pos_return_or_cancel'):
        print("✅ handle_pos_return_or_cancel function exists")
        print(f"Function location: {main_module.handle_pos_return_or_cancel}")
    else:
        print("❌ handle_pos_return_or_cancel function not found")
        print("Available functions:")
        for attr in dir(main_module):
            if not attr.startswith('_'):
                print(f"  - {attr}")
    
    # Test if other functions exist
    functions_to_test = [
        'create_manufacture_entry_from_pos',
        'submit_manufacturing_entries',
        'track_manufacturing_wastage'
    ]
    
    for func_name in functions_to_test:
        if hasattr(main_module, func_name):
            print(f"✅ {func_name} function exists")
        else:
            print(f"❌ {func_name} function not found")
    
    print("\n🎉 Test completed!")
    
except ImportError as e:
    print(f"❌ Import error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"❌ Unexpected error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1) 