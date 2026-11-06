from rest_framework import permissions


def resolve_owner(obj, owner_field):
    """Follow a dotted/double-underscore path from ``obj`` to the owning user."""
    target = obj
    for part in owner_field.replace("__", ".").split("."):
        target = getattr(target, part, None)
        if target is None:
            return None
    return target


class IsOwnerOrReadOnly(permissions.BasePermission):
    """Read for everyone authenticated, write only for the owner (or staff).

    Views declare ``owner_field`` (default ``"owner"``) pointing at the user FK.
    """

    message = "You must be the owner of this object to modify it."

    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        if request.user and request.user.is_staff:
            return True
        owner = resolve_owner(obj, getattr(view, "owner_field", "owner"))
        return owner is not None and owner == request.user


class IsOwner(permissions.BasePermission):
    """Only the owner (or staff) may see or touch the object at all."""

    message = "You do not have access to this object."

    def has_object_permission(self, request, view, obj):
        if request.user and request.user.is_staff:
            return True
        owner = resolve_owner(obj, getattr(view, "owner_field", "owner"))
        return owner is not None and owner == request.user


class IsAdminOrReadOnly(permissions.BasePermission):
    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and request.user.is_staff)


class IsSelfOrAdmin(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.method in permissions.SAFE_METHODS:
            return True
        return bool(request.user and (request.user.is_staff or obj == request.user))
