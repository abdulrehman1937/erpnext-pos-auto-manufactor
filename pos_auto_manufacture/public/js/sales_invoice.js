frappe.ui.form.on('Sales Invoice', {
    /**
     * This event triggers when the form is loaded
     */
    refresh: function(frm) {
        // Add manufacturing return options for returns and cancellations
        if (frm.doc.is_return || frm.doc.docstatus == 2) {
            add_manufacturing_return_options(frm);
        }
        
        // Add manufacturing options button for POS invoices
        if (frm.doc.is_pos && frm.doc.docstatus == 0) {
            add_manufacturing_options_button(frm);
        }
    },
    
    /**
     * This event triggers when the form is saved
     */
    after_save: function(frm) {
        // Check if this is a return or cancellation
        if (frm.doc.is_return || frm.doc.docstatus == 2) {
            show_manufacturing_return_dialog(frm);
        }
    },
    
    /**
     * This event triggers before the form is cancelled
     */
    before_cancel: function(frm) {
        // Show dialog before cancellation
        show_manufacturing_cancellation_dialog(frm);
        return false; // Prevent default cancellation
    }
});

function add_manufacturing_return_options(frm) {
    // Add custom field for manufacturing return option if not exists
    if (!frm.get_field('manufacturing_return_option')) {
        frm.add_custom_button(__('Manufacturing Options'), function() {
            show_manufacturing_return_dialog(frm);
        }, __('Manufacturing'));
    }
}

function add_manufacturing_options_button(frm) {
    frm.add_custom_button(__('Manufacturing Settings'), function() {
        show_manufacturing_settings_dialog(frm);
    }, __('Manufacturing'));
}

function show_manufacturing_settings_dialog(frm) {
    let d = new frappe.ui.Dialog({
        title: __('Manufacturing Settings'),
        fields: [
            {
                fieldtype: 'Section Break',
                label: __('Stock Management')
            },
            {
                fieldtype: 'Check',
                fieldname: 'check_stock_before_manufacturing',
                label: __('Check Stock Before Manufacturing'),
                default: 1,
                description: __('Check if raw materials are available before creating manufacturing entries')
            },
            {
                fieldtype: 'Check',
                fieldname: 'create_nested_work_orders',
                label: __('Create Nested Work Orders'),
                default: 1,
                description: __('Create separate work orders for nested BOM items')
            },
            {
                fieldtype: 'Column Break'
            },
            {
                fieldtype: 'Section Break',
                label: __('Wastage Tracking')
            },
            {
                fieldtype: 'Check',
                fieldname: 'track_manufacturing_wastage',
                label: __('Track Manufacturing Wastage'),
                default: 1,
                description: __('Create wastage tracking entries during manufacturing')
            },
            {
                fieldtype: 'Float',
                fieldname: 'wastage_percentage',
                label: __('Default Wastage Percentage'),
                default: 5.0,
                description: __('Default wastage percentage for manufacturing')
            },
            {
                fieldtype: 'Section Break',
                label: __('Return Handling')
            },
            {
                fieldtype: 'Select',
                fieldname: 'manufacturing_return_option',
                label: __('Default Return Option'),
                options: 'Convert to Raw Materials\nKeep Manufactured Product\nReverse Manufacturing Process',
                default: 'Convert to Raw Materials',
                description: __('Default option for handling manufacturing entries on returns/cancellations')
            }
        ],
        primary_action_label: __('Save Settings'),
        primary_action: function() {
            let values = d.get_values();
            // Save settings to the document
            Object.keys(values).forEach(key => {
                frm.set_value(key, values[key]);
            });
            frm.save('Update');
            d.hide();
            frappe.msgprint({
                title: __('Settings Saved'),
                message: __('Manufacturing settings have been saved to this invoice.'),
                indicator: 'green'
            });
        },
        secondary_action_label: __('Cancel'),
        secondary_action: function() {
            d.hide();
        }
    });
    
    d.show();
}

function show_manufacturing_return_dialog(frm) {
    let d = new frappe.ui.Dialog({
        title: __('Manufacturing Return Options'),
        fields: [
            {
                fieldtype: 'Select',
                fieldname: 'manufacturing_return_option',
                label: __('How to handle manufacturing entries?'),
                options: 'Convert to Raw Materials\nKeep Manufactured Product\nReverse Manufacturing Process\nCancel Only',
                default: frm.doc.manufacturing_return_option || 'Convert to Raw Materials',
                description: __('Choose how to handle manufacturing entries when cancelling or returning')
            },
            {
                fieldtype: 'HTML',
                fieldname: 'explanation',
                options: `
                    <div style="padding: 10px; background: #f8f9fa; border-radius: 4px; margin: 10px 0;">
                        <h6>Options Explanation:</h6>
                        <ul>
                            <li><strong>Convert to Raw Materials:</strong> Cancels manufacturing entries and returns raw materials to warehouse</li>
                            <li><strong>Keep Manufactured Product:</strong> Keeps the manufactured product and just handles the return/cancellation</li>
                            <li><strong>Reverse Manufacturing Process:</strong> Creates reverse manufacturing entries to convert finished goods back to raw materials</li>
                            <li><strong>Cancel Only:</strong> Simply cancels the manufacturing entries without any material movement</li>
                        </ul>
                    </div>
                `
            },
            {
                fieldtype: 'Check',
                fieldname: 'handle_wastage_on_return',
                label: __('Handle Wastage on Return'),
                default: 1,
                description: __('Include wastage handling in the return process')
            }
        ],
        primary_action_label: __('Save'),
        primary_action: function() {
            let values = d.get_values();
            frm.set_value('manufacturing_return_option', values.manufacturing_return_option);
            frm.set_value('handle_wastage_on_return', values.handle_wastage_on_return);
            frm.save();
            d.hide();
        },
        secondary_action_label: __('Cancel'),
        secondary_action: function() {
            d.hide();
        }
    });
    
    d.show();
}

function show_manufacturing_cancellation_dialog(frm) {
    // First check if there are any manufacturing entries to handle
    frappe.call({
        method: "pos_auto_manufacture.utils.get_related_work_orders",
        args: {
            sales_invoice: frm.doc.name
        },
        callback: function(r) {
            if (r.message && r.message.length > 0) {
                // There are manufacturing entries, show options
                show_cancellation_options_dialog(frm, r.message);
            } else {
                // No manufacturing entries, proceed with normal cancellation
                frm.cancel();
            }
        }
    });
}

function show_cancellation_options_dialog(frm, work_orders) {
    let d = new frappe.ui.Dialog({
        title: __('Manufacturing Cancellation Options'),
        fields: [
            {
                fieldtype: 'HTML',
                fieldname: 'summary',
                options: `
                    <div style="padding: 10px; background: #fff3cd; border: 1px solid #ffeaa7; border-radius: 4px; margin: 10px 0;">
                        <h6>⚠️ Manufacturing Entries Found</h6>
                        <p>This invoice has ${work_orders.length} manufacturing work order(s) that need to be handled:</p>
                        <ul>
                            ${work_orders.map(wo => `<li>${wo.production_item} (Qty: ${wo.qty})</li>`).join('')}
                        </ul>
                    </div>
                `
            },
            {
                fieldtype: 'Select',
                fieldname: 'manufacturing_return_option',
                label: __('How to handle manufacturing entries?'),
                options: 'Convert to Raw Materials\nKeep Manufactured Product\nReverse Manufacturing Process\nCancel Only',
                default: frm.doc.manufacturing_return_option || 'Convert to Raw Materials',
                description: __('Choose how to handle manufacturing entries when cancelling')
            },
            {
                fieldtype: 'HTML',
                fieldname: 'explanation',
                options: `
                    <div style="padding: 10px; background: #f8f9fa; border-radius: 4px; margin: 10px 0;">
                        <h6>Options Explanation:</h6>
                        <ul>
                            <li><strong>Convert to Raw Materials:</strong> Cancels manufacturing entries and returns raw materials to warehouse</li>
                            <li><strong>Keep Manufactured Product:</strong> Keeps the manufactured product and just handles the cancellation</li>
                            <li><strong>Reverse Manufacturing Process:</strong> Creates reverse manufacturing entries to convert finished goods back to raw materials</li>
                            <li><strong>Cancel Only:</strong> Simply cancels the manufacturing entries without any material movement</li>
                        </ul>
                    </div>
                `
            },
            {
                fieldtype: 'Check',
                fieldname: 'handle_wastage_on_cancel',
                label: __('Handle Wastage on Cancellation'),
                default: 1,
                description: __('Include wastage handling in the cancellation process')
            },
            {
                fieldtype: 'Check',
                fieldname: 'confirm_cancellation',
                label: __('I understand this will affect manufacturing entries'),
                default: 0,
                description: __('Please confirm that you understand the implications')
            }
        ],
        primary_action_label: __('Cancel Invoice'),
        primary_action: function() {
            let values = d.get_values();
            
            if (!values.confirm_cancellation) {
                frappe.msgprint({
                    title: __('Confirmation Required'),
                    message: __('Please confirm that you understand the implications of cancelling manufacturing entries.'),
                    indicator: 'red'
                });
                return;
            }
            
            frm.set_value('manufacturing_return_option', values.manufacturing_return_option);
            frm.set_value('handle_wastage_on_cancel', values.handle_wastage_on_cancel);
            frm.save('Update').then(() => {
                // Now proceed with cancellation
                frm.cancel();
            });
            d.hide();
        },
        secondary_action_label: __('Keep Invoice'),
        secondary_action: function() {
            d.hide();
        }
    });
    
    d.show();
}

// Enhanced stock checking for POS
frappe.ui.form.on('Sales Invoice Item', {
    /**
     * This event triggers when the item_code field is set or changed in a row
     * of the items table in the POS.
     */
    item_code: function(frm, cdt, cdn) {
        let row = locals[cdt][cdn];

        // We only need to check when an item code and quantity are present.
        if (row.item_code && row.qty > 0) {
            // Call the server-side Python function to check BOM stock levels.
            frappe.call({
                method: "pos_auto_manufacture.api.check_bom_stock_levels",
                args: {
                    item_code: row.item_code,
                    qty: row.qty,
                    warehouse: row.warehouse
                },
                callback: function(r) {
                    // The server returns a list of items with low stock.
                    if (r.message && r.message.length > 0) {
                        let warning_message = `<b>Warning: Low stock for ${row.item_name} ingredients:</b><br><ul>`;
                        
                        r.message.forEach(function(item) {
                            warning_message += `<li>${item.item_name}: <b>${item.available} ${item.uom}</b> available (requires ${item.required} ${item.uom})</li>`;
                        });
                        
                        warning_message += "</ul>";
                        warning_message += "<br><strong>Note:</strong> Manufacturing will proceed with negative stock if needed.";

                        // Display a non-blocking message to the user.
                        frappe.msgprint({
                            title: __('Stock Alert'),
                            indicator: 'orange',
                            message: __(warning_message)
                        });
                    }
                }
            });
        }
    },
    /**
     * This event triggers when the quantity is changed, so we re-check stock levels.
     */
    qty: function(frm, cdt, cdn) {
        // Re-use the same logic from the item_code trigger.
        frappe.ui.form.trigger('Sales Invoice Item', 'item_code', cdt, cdn);
    }
}); 