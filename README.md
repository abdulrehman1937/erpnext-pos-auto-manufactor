# POS Auto Manufacture

Automatically deduct BOM materials on POS orders with advanced features for returns, wastage tracking, cancellation handling, and nested manufacturing support.

## Features

### Core Functionality
- **Automatic Manufacturing**: Creates Work Orders and Stock Entries automatically when POS invoices are submitted
- **Nested BOM Support**: Handles manufacturing products that are themselves BOMs (multi-level manufacturing)
- **Stock Availability Check**: Checks available stock before creating manufacturing entries
- **Warehouse Management**: Flexible warehouse configuration for WIP and finished goods

### Returns & Cancellation Handling
- **Return Processing**: Automatically creates reverse manufacturing entries for returned items
- **Cancellation Support**: Cancels related Work Orders and Stock Entries when POS invoices are cancelled
- **Material Recovery**: Returns materials to warehouse when products are returned

### Wastage Tracking
- **Automatic Wastage Calculation**: Tracks wastage based on configured percentages
- **Actual vs Expected Tracking**: Compares actual consumption with BOM expectations
- **Wastage Item Support**: Dedicated wastage items for proper accounting

### Advanced Features
- **Comprehensive Logging**: Detailed logging of all manufacturing activities
- **Error Handling**: Robust error handling with detailed error messages
- **Configuration Management**: Flexible settings for all features
- **Stock Validation**: Validates stock availability before manufacturing

## Installation

1. Install the app in your Frappe/ERPNext instance
2. Configure settings in "POS Auto Manufacture Settings"
3. Set up wastage items for manufacturing products (optional)
4. Configure warehouses for WIP and finished goods

## Configuration

### POS Auto Manufacture Settings

Navigate to **Setup > Customize > Doctype > POS Auto Manufacture Settings** to configure:

#### Wastage Tracking
- **Enable Wastage Tracking**: Turn on/off wastage tracking
- **Default Wastage Percentage**: Set default wastage percentage (default: 5%)
- **Wastage Item Field**: Custom field name for wastage items
- **Track Actual vs Expected**: Compare actual consumption with BOM expectations

#### Nested BOM Handling
- **Enable Nested BOM Handling**: Handle multi-level manufacturing
- **Check Stock Before Manufacturing**: Validate stock availability
- **Create Nested Work Orders**: Create separate work orders for nested items

#### Return Handling
- **Enable Return Handling**: Process returns automatically
- **Create Reverse Entries**: Create reverse manufacturing entries
- **Return Materials to Warehouse**: Return materials when products are returned

#### Cancellation Handling
- **Enable Cancellation Handling**: Handle POS invoice cancellations
- **Cancel Related Work Orders**: Cancel work orders when POS is cancelled
- **Cancel Related Stock Entries**: Cancel stock entries when POS is cancelled

#### Logging
- **Enable Logging**: Turn on/off logging
- **Log Level**: Set logging level (DEBUG, INFO, WARNING, ERROR)
- **Log Manufacturing Entries**: Log all manufacturing activities
- **Log Errors**: Log error details

#### Warehouse Settings
- **Use Same Warehouse for WIP**: Use same warehouse for WIP and finished goods
- **Default WIP Warehouse**: Default warehouse for work-in-progress
- **Default Finished Goods Warehouse**: Default warehouse for finished goods

## Usage

### Basic Usage

1. Create a POS invoice with manufacturable items
2. Submit the POS invoice
3. The system automatically:
   - Prepares Work Orders and Manufacturing Stock Entries during validation
   - Submits the manufacturing entries after POS invoice submission
   - Handles nested BOMs if present
   - Tracks wastage if enabled
   - Allows negative stock for manufacturing (with warnings)
   - Only manufactures the quantity not in stock

### Returns Processing

1. Create a POS return invoice
2. Add items with negative quantities
3. Choose manufacturing return option:
   - **Convert to Raw Materials**: Cancels manufacturing entries and returns raw materials
   - **Keep Manufactured Product**: Keeps the manufactured product and handles return
4. Submit the return invoice
5. The system automatically:
   - Creates reverse manufacturing entries (if "Convert to Raw Materials" selected)
   - Returns materials to warehouse
   - Updates stock levels

### Cancellation Handling

1. Cancel a POS invoice
2. Choose manufacturing cancellation option:
   - **Convert to Raw Materials**: Cancels manufacturing entries and returns raw materials
   - **Keep Manufactured Product**: Keeps the manufactured product and handles cancellation
3. The system automatically:
   - Cancels related Work Orders
   - Cancels related Stock Entries
   - Creates reverse manufacturing entries (if "Convert to Raw Materials" selected)
   - Reverses stock movements

## New Features

### Smart Manufacturing
- **Negative Stock Support**: Allows manufacturing even with insufficient stock (with warnings)
- **Shortage-Only Manufacturing**: Only manufactures the quantity not available in stock
- **Real-time Stock Checking**: JavaScript alerts for low stock during POS entry
- **Flexible Return Options**: Choose how to handle manufacturing during returns/cancellations

### Manufacturing Return Options
When cancelling or returning POS invoices, users can choose:

1. **Convert to Raw Materials**:
   - Cancels manufacturing entries
   - Returns raw materials to warehouse
   - Creates reverse manufacturing entries
   - Suitable when you want to recover materials

2. **Keep Manufactured Product**:
   - Keeps the manufactured product
   - Just handles the return/cancellation
   - No reverse manufacturing entries
   - Suitable when you want to keep the finished goods

## Nested BOM Support

The system supports multi-level manufacturing where BOM items are themselves manufacturing products:

```
Product A (Final Product)
├── Sub-Assembly B (Manufacturing Item)
│   ├── Raw Material 1
│   └── Raw Material 2
└── Raw Material 3
```

When manufacturing Product A, the system:
1. Checks if Sub-Assembly B needs to be manufactured
2. Creates manufacturing entries for Sub-Assembly B if needed
3. Uses the manufactured Sub-Assembly B for Product A
4. Handles stock availability for all levels

## Wastage Tracking

### Automatic Wastage Calculation
- Calculates wastage based on configured percentage
- Creates wastage entries for tracking
- Supports custom wastage items

### Actual vs Expected Tracking
- Compares actual material consumption with BOM expectations
- Identifies excess consumption as wastage
- Creates detailed wastage reports

## Error Handling

The system includes comprehensive error handling:
- Validates prerequisites before manufacturing
- Handles stock shortages gracefully
- Provides detailed error messages
- Logs all errors for troubleshooting

## Logging

All manufacturing activities are logged:
- Manufacturing entry creation
- Stock movements
- Wastage calculations
- Error details
- Return and cancellation activities

## API Functions

### Core Functions
- `create_manufacture_entry_from_pos(doc, method)`: Main manufacturing function
- `handle_pos_return_or_cancel(doc, method)`: Handle returns and cancellations
- `track_manufacturing_wastage(doc, method)`: Track manufacturing wastage

### Utility Functions
- `get_settings()`: Get system settings
- `is_manufacturable_item(item_code)`: Check if item is manufacturable
- `get_nested_bom_structure(bom_no)`: Get complete BOM structure
- `calculate_total_materials_required(bom_no, qty)`: Calculate total materials needed
- `check_stock_availability(materials_required, warehouse)`: Check stock availability

## Troubleshooting

### Common Issues

1. **Manufacturing entries not created**
   - Check if items have default BOMs
   - Verify POS invoice is submitted
   - Check error logs

2. **Stock shortages**
   - Review stock availability before manufacturing
   - Check nested BOM requirements
   - Verify warehouse configurations

3. **Return processing issues**
   - Ensure return handling is enabled
   - Check return item configurations
   - Verify warehouse settings

### Logs

Check logs for detailed information:
- Manufacturing activities: `frappe.logger().info()`
- Errors: `frappe.log_error()`
- Warnings: `frappe.logger().warning()`

## Development

### Adding Custom Features

1. Extend the utility functions in `utils.py`
2. Add new event handlers in `hooks.py`
3. Update settings in the configuration doctype
4. Test thoroughly with various scenarios

### Custom Wastage Items

To use custom wastage items:
1. Add a custom field to Item doctype (e.g., "wastage_item")
2. Configure the field name in settings
3. Set wastage items for manufacturing products

## Support

For support and questions:
- Check the error logs for detailed information
- Review the configuration settings
- Test with sample data first
- Contact the development team for complex issues

## License

MIT License - see license.txt for details.
