from django.dispatch import Signal

# Sent by the order service once an order has been placed and paid for.
order_placed = Signal(providing_args=["order", "user"])

# Sent whenever a product changes status (draft -> active, etc).
product_status_changed = Signal(providing_args=["product", "old_status", "new_status"])

# Sent when one user follows another.
user_followed = Signal(providing_args=["follower", "followee"])
