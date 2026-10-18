from __future__ import annotations

from django import forms
from django.utils import timezone

from inventory.models import Tool
from maintenance.models import MaintenanceLog, MaintenanceSchedule


class MaintenanceLogForm(forms.ModelForm):
    class Meta:
        model = MaintenanceLog
        fields = ("task_type", "date", "cost", "notes", "attachments")
        widgets = {
            "task_type": forms.Select(attrs={"class": "select h-6 py-0 text-2xs"}),
            "date": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "cost": forms.NumberInput(attrs={
                "class": "input num text-right h-6 py-0 text-2xs", "step": "0.01",
                "placeholder": "0.00"}),
            "notes": forms.TextInput(attrs={
                "class": "input h-6 py-0 text-2xs", "placeholder": "Notes"}),
            "attachments": forms.ClearableFileInput(attrs={"class": "input py-0", "type": "file"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["date"].initial = timezone.localdate()

    def clean_date(self):
        date = self.cleaned_data["date"]
        if date > timezone.localdate():
            raise forms.ValidationError("Log date cannot be in the future.")
        return date


class MaintenanceScheduleForm(forms.ModelForm):
    class Meta:
        model = MaintenanceSchedule
        fields = ("tool", "task_type", "interval_days", "last_done", "next_due")
        widgets = {
            "tool": forms.Select(attrs={"class": "select"}),
            "task_type": forms.Select(attrs={"class": "select"}),
            "interval_days": forms.NumberInput(attrs={"class": "input font-mono text-right"}),
            "last_done": forms.DateInput(attrs={"class": "input", "type": "date"}),
            "next_due": forms.DateInput(attrs={"class": "input", "type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tool"].queryset = Tool.objects.active().select_related("category")
        self.fields["last_done"].required = False

    def clean(self):
        cleaned = super().clean()
        last_done, next_due = cleaned.get("last_done"), cleaned.get("next_due")
        interval = cleaned.get("interval_days") or 0
        tool = cleaned.get("tool")
        task_type = cleaned.get("task_type")
        if tool and task_type:
            exists = MaintenanceSchedule.objects.filter(tool=tool, task_type=task_type)
            if self.instance.pk:
                exists = exists.exclude(pk=self.instance.pk)
            if exists.exists():
                self.add_error(
                    "task_type", f"{tool.sku} already has a {task_type} schedule."
                )
        if last_done and next_due and interval and next_due < last_done:
            self.add_error("next_due", "next_due cannot be before last_done.")
        return cleaned
