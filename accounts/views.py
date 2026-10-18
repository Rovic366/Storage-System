from django.contrib.auth import views as auth_views
from django.views.generic import ListView

from . import roles
from .mixins import RoleRequiredMixin

# ---------------------------------------------------------------- login/logout


class LoginView(auth_views.LoginView):
    template_name = "registration/login.html"
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["app_name"] = "STORAGE OS"
        return ctx


class LogoutView(auth_views.LogoutView):
    pass


# ---------------------------------------------------------------- audit trail


class AuditListView(RoleRequiredMixin, ListView):
    roles = ("audit",)
    context_object_name = "logs"
    template_name = "accounts/audit.html"
    paginate_by = 100

    def get_queryset(self):
        from .models import AuditLog

        qs = AuditLog.objects.select_related("user")
        if action := self.request.GET.get("action"):
            qs = qs.filter(action=action)
        if q := self.request.GET.get("q"):
            qs = qs.filter(object_repr__icontains=q) | qs.filter(user__username__icontains=q)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        from .models import AuditLog

        ctx["actions"] = sorted(set(AuditLog.objects.values_list("action", flat=True)))
        ctx["roles_available"] = roles.ALL_ROLES
        return ctx
