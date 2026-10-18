from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.generic import FormView, ListView

from accounts.mixins import RoleRequiredMixin
from maintenance import services
from maintenance.models import MaintenanceLog, MaintenanceSchedule

from .forms import MaintenanceLogForm, MaintenanceScheduleForm


class ScheduleListView(RoleRequiredMixin, ListView):
    context_object_name = "schedules"
    template_name = "maintenance/schedule.html"
    paginate_by = 50

    def get_queryset(self):
        g = self.request.GET
        tab = g.get("tab", "due")
        qs = MaintenanceSchedule.objects.select_related("tool", "tool__location")
        if tab == "overdue":
            qs = qs.overdue()
        elif tab == "due":
            qs = qs.due_within(7)
        elif tab == "calendar":
            qs = qs.due_within(31)
        if q := g.get("q", "").strip():
            qs = qs.filter(tool__sku__icontains=q) | qs.filter(
                tool__name__icontains=q)
        if tt := g.get("type"):
            qs = qs.filter(task_type=tt)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            tab=self.request.GET.get("tab", "due"),
            task_types=MaintenanceSchedule.TaskType.choices,
            querystring=self.request.GET.urlencode(),
            today=maintenance_today(),
            recent_logs=MaintenanceLog.objects.select_related(
                "tool", "performed_by").order_by("-date", "-id")[:15],
        )
        return ctx


def maintenance_today():
    from django.utils import timezone

    return timezone.localdate()


class LogTaskView(RoleRequiredMixin, FormView):
    roles = ("maintenance",)
    form_class = MaintenanceLogForm
    http_method_names = ["get", "post"]

    def dispatch(self, request, *args, **kwargs):
        self.schedule = get_object_or_404(
            MaintenanceSchedule.objects.select_related("tool"), pk=kwargs["pk"]
        )
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, pk: int):
        form = MaintenanceLogForm(initial={"task_type": self.schedule.task_type})
        return render(request, "maintenance/log.html",
                      {"schedule": self.schedule, "form": form,
                       "next_due_preview": services.next_due_preview(self.schedule)})

    def post(self, request, pk: int):
        form = MaintenanceLogForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                log, schedule = services.log_task(
                    self.schedule, request.user,
                    date=form.cleaned_data["date"],
                    cost=form.cleaned_data.get("cost") or 0,
                    notes=form.cleaned_data.get("notes") or "",
                    task_type=form.cleaned_data["task_type"],
                    attachments=form.cleaned_data.get("attachments"),
                )
                messages.success(
                    request,
                    f"Task logged for {schedule.tool.sku}; next due "
                    f"{schedule.next_due:%Y-%m-%d}.",
                )
                return redirect("maintenance:schedule")
            except (services.StockError, ValueError) as exc:
                form.add_error(None, str(exc))
        return render(request, "maintenance/log.html",
                      {"schedule": self.schedule, "form": form,
                       "next_due_preview": services.next_due_preview(self.schedule)},
                      status=400)


class ScheduleCreateView(RoleRequiredMixin, FormView):
    roles = ("inventory_write",)
    form_class = MaintenanceScheduleForm
    template_name = "maintenance/schedule_create.html"

    def form_valid(self, form):
        schedule = form.save()
        from accounts.services import audit

        audit(self.request.user, "SCHEDULE_CREATED", schedule,
              meta={"task_type": schedule.task_type, "interval": schedule.interval_days})
        messages.success(self.request, "Schedule created.")
        return redirect("maintenance:schedule")
