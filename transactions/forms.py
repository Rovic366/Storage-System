from datetime import timedelta

from django import forms
from django.contrib.auth import get_user_model
from django.utils import timezone

from inventory.models import Location, Tool

User = get_user_model()


def _lookup_tool(value: str):
    value = (value or "").strip().upper()
    return (
        Tool.objects.filter(sku=value).first()
        or Tool.objects.filter(barcode_value=value).first()
    )


class BaseStockOpForm(forms.Form):
    """Base for Receive / Issue / Transfer / Adjust: resolves a tool by SKU."""

    sku = forms.CharField(
        label="Tool SKU / barcode",
        widget=forms.TextInput(attrs={
            "class": "input font-mono uppercase",
            "placeholder": "Scan barcode or type SKU", "autofocus": "autofocus",
        }),
    )
    notes = forms.CharField(required=False, widget=forms.TextInput(
        attrs={"class": "input", "placeholder": "Optional note"}))

    def clean_sku(self):
        value = self.cleaned_data["sku"].strip().upper()
        tool = _lookup_tool(value)
        if not tool:
            raise forms.ValidationError("No tool matches that SKU / barcode.")
        if tool.status in (Tool.Status.RETIRED, Tool.Status.LOST):
            raise forms.ValidationError(f"{tool.sku} is {tool.get_status_display()}; blocked.")
        if tool.status == Tool.Status.IN_MAINTENANCE:
            raise forms.ValidationError(f"{tool.sku} is In Maintenance; blocked.")
        self._tool = tool
        return value

    @property
    def tool(self):
        return getattr(self, "_tool", None)


class ReceiveForm(BaseStockOpForm):
    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "input font-mono text-right"}),
    )
    to_location = forms.ModelChoiceField(
        queryset=Location.objects.filter(is_active=True).order_by("code"),
        required=False, empty_label="— keep current bin —",
        widget=forms.Select(attrs={"class": "select"}),
    )
    reference_no = forms.CharField(required=False, widget=forms.TextInput(
        attrs={"class": "input font-mono", "placeholder": "PO / reference"}))


class IssueForm(BaseStockOpForm):
    quantity = forms.IntegerField(
        min_value=1,
        widget=forms.NumberInput(attrs={"class": "input font-mono text-right"}),
    )
    reference_no = forms.CharField(required=False, widget=forms.TextInput(
        attrs={"class": "input font-mono", "placeholder": "Job no / reference"}))


class TransferForm(BaseStockOpForm):
    to_location = forms.ModelChoiceField(
        queryset=Location.objects.filter(is_active=True).exclude(code=""),
        widget=forms.Select(attrs={"class": "select"}),
    )
    reference_no = forms.CharField(required=False, widget=forms.TextInput(
        attrs={"class": "input font-mono", "placeholder": "Reference"}))

    def clean(self):
        cleaned = super().clean()
        tool = getattr(self, "_tool", None)
        if tool and self.cleaned_data.get("to_location"):
            if self.cleaned_data["to_location"].pk == tool.location_id:
                self.add_error("to_location", "Same as the tool's current bin.")
        return cleaned


class AdjustForm(BaseStockOpForm):
    delta = forms.IntegerField(
        help_text="Stock-take delta: positive restock, negative shrinkage.",
        widget=forms.NumberInput(attrs={"class": "input font-mono text-right"}),
    )
    reference_no = forms.CharField(required=False, widget=forms.TextInput(
        attrs={"class": "input font-mono", "placeholder": "Stock take ref"}))


class CheckoutFastForm(forms.Form):
    sku = forms.CharField(
        label="Tool SKU / barcode",
        widget=forms.TextInput(attrs={
            "class": "input font-mono uppercase",
            "placeholder": "Scan barcode or type SKU", "autofocus": "autofocus",
            "list": "sku-list",
        }),
    )
    borrower = forms.ModelChoiceField(
        queryset=User.objects.filter(is_active=True).order_by("username"),
        widget=forms.Select(attrs={"class": "select"}),
    )
    due_at = forms.SplitDateTimeField(
        input_date_formats=["%Y-%m-%d"], input_time_formats=["%H:%M"],
        initial=lambda: ((timezone.localtime() + timedelta(days=3))
                         .replace(hour=17, minute=0, second=0, microsecond=0)),
        widget=forms.SplitDateTimeWidget(
            date_attrs={"class": "input", "type": "date"},
            time_attrs={"class": "input", "type": "time"},
        ),
    )
    notes = forms.CharField(required=False, widget=forms.TextInput(
        attrs={"class": "input", "placeholder": "Purpose / note"}))

    def clean_sku(self):
        value = self.cleaned_data["sku"].strip().upper()
        tool = _lookup_tool(value)
        if not tool:
            raise forms.ValidationError("No tool matches that SKU / barcode.")
        if tool.status == Tool.Status.CHECKED_OUT:
            raise forms.ValidationError(
                f"{tool.sku} is already checked out. Settle the open checkout first."
            )
        if tool.status == Tool.Status.IN_MAINTENANCE:
            raise forms.ValidationError(f"{tool.sku} is In Maintenance and cannot be issued.")
        if tool.status in (Tool.Status.RETIRED, Tool.Status.LOST):
            raise forms.ValidationError(f"{tool.sku} is {tool.get_status_display()}.")
        if tool.quantity_on_hand < 1:
            raise forms.ValidationError(f"{tool.sku} has no stock.")
        self._tool = tool
        return value

    @property
    def tool(self):
        return getattr(self, "_tool", None)


class ReturnForm(forms.Form):
    condition_in = forms.ChoiceField(
        choices=[("", "— as issued —")] + list(Tool.Condition.choices),
        required=False, label="Condition on return",
        widget=forms.Select(attrs={"class": "select"}),
    )
    notes = forms.CharField(required=False, widget=forms.TextInput(
        attrs={"class": "input", "placeholder": "Optional note"}))
