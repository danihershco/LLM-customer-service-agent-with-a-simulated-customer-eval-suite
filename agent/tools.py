"""Tools the agent can call. Like a real order system, the tools do not enforce return
policy: deciding what is allowed is the agent's job. They only enforce what a real
backend would (identity verification, valid ids, stock)."""
from datetime import date

from .data import TODAY

TOOL_SCHEMAS = [
    {
        "name": "find_order",
        "description": "Look up an order. Requires the order number AND the email on the order; "
                       "both must match. Returns order details including delivery date and items.",
        "input_schema": {"type": "object", "properties": {
            "order_id": {"type": "string"}, "email": {"type": "string"}},
            "required": ["order_id", "email"]},
    },
    {
        "name": "check_stock",
        "description": "Check whether a product is in stock in a given size.",
        "input_schema": {"type": "object", "properties": {
            "product_id": {"type": "string"}, "size": {"type": "string"}},
            "required": ["product_id", "size"]},
    },
    {
        "name": "create_return",
        "description": "Create a return authorization for one or more items on a verified order. "
                       "refund_method is 'original_payment' or 'site_credit'.",
        "input_schema": {"type": "object", "properties": {
            "order_id": {"type": "string"},
            "item_ids": {"type": "array", "items": {"type": "string"}},
            "refund_method": {"type": "string", "enum": ["original_payment", "site_credit"]},
            "reason": {"type": "string"}},
            "required": ["order_id", "item_ids", "refund_method", "reason"]},
    },
    {
        "name": "create_exchange",
        "description": "Exchange one item on a verified order for a different size of the same product.",
        "input_schema": {"type": "object", "properties": {
            "order_id": {"type": "string"}, "item_id": {"type": "string"},
            "new_size": {"type": "string"}},
            "required": ["order_id", "item_id", "new_size"]},
    },
    {
        "name": "escalate_to_human",
        "description": "Hand the conversation to the client care team with a short summary.",
        "input_schema": {"type": "object", "properties": {
            "summary": {"type": "string"}, "order_id": {"type": "string"}},
            "required": ["summary"]},
    },
]


class Store:
    def __init__(self, db):
        self.db = db
        self.verified = set()  # orders verified in this conversation

    def call(self, name, args):
        fn = getattr(self, name, None)
        if fn is None:
            return {"error": f"Unknown tool {name}"}
        try:
            return fn(**args)
        except TypeError as e:
            return {"error": f"Bad arguments: {e}"}

    def _verified_order(self, order_id):
        order_id = order_id.strip().upper()
        if order_id not in self.verified:
            return None, {"error": "Order not verified. Call find_order with the order number and email first."}
        return self.db["orders"][order_id], None

    def find_order(self, order_id, email):
        oid = order_id.strip().upper()
        order = self.db["orders"].get(oid)
        if not order or order["email"].lower() != email.strip().lower():
            return {"error": "No order found matching that order number and email."}
        self.verified.add(oid)
        days = (TODAY - date.fromisoformat(order["delivered"])).days
        return {"order_id": oid, "customer": order["customer"], "delivered": order["delivered"],
                "days_since_delivery": days, "today": TODAY.isoformat(),
                "payment": order["payment"], "is_gift": order["is_gift"], "items": order["items"]}

    def check_stock(self, product_id, size):
        p = self.db["products"].get(product_id)
        if not p:
            return {"error": "Unknown product"}
        qty = p["stock"].get(size)
        if qty is None:
            return {"error": f"{p['name']} does not come in size {size}"}
        return {"product_id": product_id, "size": size, "in_stock": qty > 0}

    def create_return(self, order_id, item_ids, refund_method, reason):
        order, err = self._verified_order(order_id)
        if err:
            return err
        valid = {i["item_id"] for i in order["items"]}
        bad = [i for i in item_ids if i not in valid]
        if bad:
            return {"error": f"Items not on order: {bad}"}
        if refund_method not in ("original_payment", "site_credit"):
            return {"error": "refund_method must be original_payment or site_credit"}
        rec = {"order_id": order_id.strip().upper(), "item_ids": sorted(item_ids),
               "refund_method": refund_method, "reason": reason}
        self.db["returns"].append(rec)
        return {"status": "return_created", "label_emailed_to": order["email"], **rec}

    def create_exchange(self, order_id, item_id, new_size):
        order, err = self._verified_order(order_id)
        if err:
            return err
        item = next((i for i in order["items"] if i["item_id"] == item_id), None)
        if not item:
            return {"error": "Item not on order"}
        stock = self.db["products"][item["product_id"]]["stock"]
        if stock.get(new_size, 0) <= 0:
            return {"error": f"Size {new_size} is out of stock"}
        stock[new_size] -= 1
        rec = {"order_id": order_id.strip().upper(), "item_id": item_id, "new_size": new_size}
        self.db["exchanges"].append(rec)
        return {"status": "exchange_created", "confirmation_emailed_to": order["email"],
                "return_instructions": "A prepaid return label for the original item is included in the "
                                       "confirmation email. Ship it back within 14 days; the new size ships "
                                       "once it's scanned in.", **rec}

    def escalate_to_human(self, summary, order_id=None):
        self.db["escalations"].append({"order_id": order_id, "summary": summary})
        return {"status": "escalated", "message": "A client care specialist will reply by email within 24 hours."}
