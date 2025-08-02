# Copyright (c) 2024, XEuroTech and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class POSAutoManufactureSettings(Document):
	# begin: auto-generated types
	# This code is auto-generated. Do not modify anything in this block.

	from typing import TYPE_CHECKING

	if TYPE_CHECKING:
		from frappe.types import DF

		check_stock_before_manufacturing: DF.Check
		create_nested_work_orders: DF.Check
		enable_auto_manufacturing: DF.Check
		handle_wastage_on_cancel: DF.Check
		handle_wastage_on_return: DF.Check
		manufacturing_return_option: DF.Literal["Create Return Stock Entry", "Reverse Manufacturing Entry", "Both"]
		track_manufacturing_wastage: DF.Check
		wastage_percentage: DF.Percent
	# end: auto-generated types

	def validate(self):
		"""Validate settings before saving"""
		if self.track_manufacturing_wastage:
			if not self.wastage_percentage or self.wastage_percentage < 0:
				frappe.throw(_("Wastage percentage must be a positive number"))
			
			if self.wastage_percentage > 100:
				frappe.throw(_("Wastage percentage cannot exceed 100%"))

	def get_setting(self, setting_name):
		"""Get a specific setting value"""
		settings = frappe.get_single("POS Auto Manufacture Settings")
		return getattr(settings, setting_name, None)

	def is_auto_manufacturing_enabled(self):
		"""Check if auto manufacturing is enabled"""
		return self.get_setting("enable_auto_manufacturing")

	def should_check_stock_before_manufacturing(self):
		"""Check if stock should be verified before manufacturing"""
		return self.get_setting("check_stock_before_manufacturing")

	def should_create_nested_work_orders(self):
		"""Check if nested work orders should be created"""
		return self.get_setting("create_nested_work_orders")

	def should_track_manufacturing_wastage(self):
		"""Check if manufacturing wastage should be tracked"""
		return self.get_setting("track_manufacturing_wastage")

	def get_wastage_percentage(self):
		"""Get the wastage percentage setting"""
		return self.get_setting("wastage_percentage") or 5.0

	def should_handle_wastage_on_return(self):
		"""Check if wastage should be handled on returns"""
		return self.get_setting("handle_wastage_on_return")

	def should_handle_wastage_on_cancel(self):
		"""Check if wastage should be handled on cancellations"""
		return self.get_setting("handle_wastage_on_cancel")

	def get_manufacturing_return_option(self):
		"""Get the manufacturing return option"""
		return self.get_setting("manufacturing_return_option") or "Create Return Stock Entry" 