frappe.ui.form.on('Sales Invoice Item', {
    /**
     * This event triggers when the item_code field is set or changed in a row
     * of the items table in the POS.
     */
    item_code: function(frm, cdt, cdn) {
        try {
            // Safely get the row data
            let row = null;
            if (locals && locals[cdt] && locals[cdt][cdn]) {
                row = locals[cdt][cdn];
            } else {
                console.warn('Row not found for cdt:', cdt, 'cdn:', cdn);
                return;
            }
            
            console.log('Stock check for item:', row);
            
            // We only need to check when an item code and quantity are present.
            if (row && row.item_code && row.qty > 0) {
                // Call the server-side Python function to check BOM stock levels.
                frappe.call({
                    method: "pos_auto_manufacture.api.stock_checker.check_bom_stock_levels",
                    args: {
                        item_code: row.item_code,
                        qty: row.qty,
                        warehouse: row.warehouse || ''
                    },
                    callback: function(r) {
                        try {
                            // The server returns a list of items with low stock.
                            if (r && r.message && r.message.length > 0) {
                                let warning_message = `<b>Warning: Low stock for ${row.item_name || row.item_code} ingredients:</b><br><ul>`;
                                
                                r.message.forEach(function(item) {
                                    warning_message += `<li>${item.item_name}: <b>${item.available} ${item.uom}</b> available (requires ${item.required} ${item.uom})</li>`;
                                });
                                
                                warning_message += "</ul>";

                                // Display a non-blocking message to the user.
                                frappe.msgprint({
                                    title: __('Stock Alert'),
                                    indicator: 'orange',
                                    message: __(warning_message)
                                });
                            }
                        } catch (callbackError) {
                            console.error('Error in callback:', callbackError);
                        }
                    },
                    error: function(err) {
                        console.error('Error checking BOM stock levels:', err);
                    }
                });
            }
        } catch (error) {
            console.error('Error in item_code handler:', error);
        }
    },
    /**
     * This event triggers when the quantity is changed, so we re-check stock levels.
     */
    qty: function(frm, cdt, cdn) {
        try {
            // Re-use the same logic from the item_code trigger.
            frappe.ui.form.trigger('Sales Invoice Item', 'item_code', cdt, cdn);
        } catch (error) {
            console.error('Error in qty handler:', error);
        }
    }
});