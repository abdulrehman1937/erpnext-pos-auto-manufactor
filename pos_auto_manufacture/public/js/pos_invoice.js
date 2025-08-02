frappe.ui.form.on('Sales Invoice Item', {
    /**
     * This event triggers when the item_code field is set or changed in a row
     * of the items table in the POS.
     */
    item_code: function(frm, cdt, cdn) {
        console.log("new version");
        
        // Use setTimeout to ensure the row is properly initialized
        setTimeout(() => {
            console.log("new version");
            this.checkStockLevels(frm, cdt, cdn);
        }, 100);
    },
    
    /**
     * This event triggers when the quantity is changed, so we re-check stock levels.
     */
    qty: function(frm, cdt, cdn) {
        // Use setTimeout to ensure the row is properly initialized
        setTimeout(() => {
            this.checkStockLevels(frm, cdt, cdn);
        }, 100);
    },
    
    /**
     * Centralized function to check stock levels with comprehensive error handling
     */
    checkStockLevels: function(frm, cdt, cdn) {
        try {
            // Multiple ways to get the row data safely
            let row = null;
            
            // Method 1: Try locals access
            if (typeof locals !== 'undefined' && locals && locals[cdt] && locals[cdt][cdn]) {
                row = locals[cdt][cdn];
            }
            // Method 2: Try frm.get_doc method
            else if (frm && frm.get_doc) {
                try {
                    row = frm.get_doc(cdt, cdn);
                } catch (e) {
                    console.warn('Could not get row via frm.get_doc:', e);
                }
            }
            // Method 3: Try direct access from form
            else if (frm && frm.doc && frm.doc.items) {
                const items = frm.doc.items;
                if (items && items.length > 0) {
                    // Find the item by name or try to get the last modified one
                    row = items.find(item => item.name === cdn) || items[items.length - 1];
                }
            }
            
            // If we still don't have a row, log and return
            if (!row) {
                console.warn('Could not retrieve row data for cdt:', cdt, 'cdn:', cdn);
                return;
            }
            
            // Validate that we have the required data
            if (!row.item_code || !row.qty || row.qty <= 0) {
                return; // No need to check stock if no item or quantity
            }
            
            console.log('Checking stock levels for item:', row.item_code, 'qty:', row.qty);
            
            // Make the API call with comprehensive error handling
            frappe.call({
                method: "pos_auto_manufacture.api.stock_checker.check_bom_stock_levels",
                args: {
                    item_code: row.item_code,
                    qty: parseFloat(row.qty) || 0,
                    warehouse: row.warehouse || ''
                },
                callback: function(response) {
                    try {
                        if (response && response.message && Array.isArray(response.message) && response.message.length > 0) {
                            // Build warning message
                            let warning_message = `<b>Warning: Low stock for ${row.item_name || row.item_code} ingredients:</b><br><ul>`;
                            
                            response.message.forEach(function(item) {
                                if (item && item.item_name && item.available !== undefined && item.required !== undefined) {
                                    warning_message += `<li>${item.item_name}: <b>${item.available} ${item.uom || 'units'}</b> available (requires ${item.required} ${item.uom || 'units'})</li>`;
                                }
                            });
                            
                            warning_message += "</ul>";

                            // Display the warning
                            frappe.msgprint({
                                title: __('Stock Alert'),
                                indicator: 'orange',
                                message: __(warning_message)
                            });
                        }
                    } catch (callbackError) {
                        console.error('Error processing stock check response:', callbackError);
                    }
                },
                error: function(error) {
                    console.error('Error checking BOM stock levels:', error);
                }
            });
            
        } catch (error) {
            console.error('Error in checkStockLevels:', error);
        }
    }
});