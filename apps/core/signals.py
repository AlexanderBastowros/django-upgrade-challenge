from django.dispatch import Signal

order_placed = Signal(providing_args=["order", "user"])

product_status_changed = Signal(providing_args=["product", "old_status", "new_status"])

user_followed = Signal(providing_args=["follower", "followee"])
