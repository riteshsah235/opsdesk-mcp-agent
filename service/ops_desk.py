"""Ops Desk backend. Plain Python. No MCP code, no decorators, no framework."""

_ORDERS = {
    "A1001": {"customer": "Maya Rao", "item": "Trail Backpack", "sku": "BP-20", "qty": 1, "total": 79, "status": "delivered", "days_since_delivery": 4},
    "A1002": {"customer": "Dev Patel", "item": "Steel Bottle", "sku": "BT-11", "qty": 2, "total": 36, "status": "delivered", "days_since_delivery": 41},
    "A1004": {"customer": "Sam Lee", "item": "Two-Person Tent", "sku": "TN-30", "qty": 1, "total": 189, "status": "delivered", "days_since_delivery": 3},
    "A1003": {"customer": "Maya Rao", "item": "Camp Stove", "sku": "ST-05", "qty": 1, "total": 120, "status": "shipped", "days_since_delivery": 0},
}
_STOCK = {"BP-20": 14, "BT-11": 0, "ST-05": 3, "TN-30": 6}
REFUND_AUTO_LIMIT = 100
REFUND_WINDOW_DAYS = 30


class OpsDesk:
    @staticmethod
    def get_order(order_id: str) -> str:
        o = _ORDERS.get(order_id)
        if o is None:
            return "order not found"
        return "%s | customer=%s | item=%s x%d | sku=%s | total=$%d | status=%s | days_since_delivery=%d" % (
            order_id, o["customer"], o["item"], o["qty"], o["sku"], o["total"], o["status"], o["days_since_delivery"])

    @staticmethod
    def list_customer_orders(customer: str) -> str:
        return ",".join(k for k, o in _ORDERS.items() if o["customer"].lower() == customer.lower())

    @staticmethod
    def check_stock(sku: str) -> str:
        """Units in stock for a SKU such as BP-20 (SKUs come from get_order). Unknown SKU returns an explicit error."""
        if sku not in _STOCK:
            return "ERROR: unknown sku '%s' (use the sku field from get_order)" % sku
        return "%s: %d units in stock" % (sku, _STOCK[sku])

    @staticmethod
    def evaluate_refund(order_id: str) -> str:
        """Returns the policy decision for a refund: APPROVE, NEEDS_HUMAN, or DENY, with the reason."""
        o = _ORDERS.get(order_id)
        if o is None:
            return "DENY: order not found"
        if o["status"] != "delivered":
            return "DENY: order not delivered yet"
        if o["days_since_delivery"] > REFUND_WINDOW_DAYS:
            return "DENY: outside %d day refund window" % REFUND_WINDOW_DAYS
        if o["total"] > REFUND_AUTO_LIMIT:
            return "NEEDS_HUMAN: total above auto limit"
        return "APPROVE: within window and limit"
