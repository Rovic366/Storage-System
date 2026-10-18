from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.core.exceptions import PermissionDenied

from . import roles


class RoleRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    """View mixin: restrict access to the listed role groups (or superusers).

    `roles = ()` means any authenticated user passes. Unauthenticated users are
    redirected to login; authenticated users without the proper role get a 403.
    """

    roles: tuple[str, ...] = ()

    def test_func(self) -> bool:
        user = self.request.user
        if not user.is_authenticated:
            return False
        if not self.roles:
            return True
        return roles.has_role(user, *self.roles)

    def handle_no_permission(self):
        if self.request.user.is_authenticated:
            raise PermissionDenied("Your role does not have access to this action.")
        return super().handle_no_permission()
