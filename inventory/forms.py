from django import forms
from django.core.validators import MinValueValidator

from .models import Tool


class ToolForm(forms.ModelForm):
    initial_quantity = forms.IntegerField(
        required=False, min_value=0,
        help_text="Opening stock (creates a Receive movement); editable later via stock ops.",
        widget=forms.NumberInput(attrs={"class": "input", "placeholder": "e.g. 5"}),
    )

    class Meta:
        model = Tool
        fields = (
            "sku", "name", "description", "category", "supplier", "manufacturer",
            "model_number", "serial_number", "unit_cost", "reorder_level",
            "max_stock_level", "location", "status", "condition",
            "requires_calibration", "image",
        )
        widgets = {
            "sku": forms.TextInput(attrs={"class": "input font-mono uppercase", "maxlength": 32}),
            "name": forms.TextInput(attrs={"class": "input"}),
            "description": forms.Textarea(attrs={"class": "input h-16 py-1.5", "rows": 3}),
            "manufacturer": forms.TextInput(attrs={"class": "input"}),
            "model_number": forms.TextInput(attrs={"class": "input font-mono"}),
            "serial_number": forms.TextInput(attrs={"class": "input font-mono"}),
            "unit_cost": forms.NumberInput(attrs={"class": "input font-mono", "step": "0.01"}),
            "reorder_level": forms.NumberInput(attrs={"class": "input font-mono"}),
            "max_stock_level": forms.NumberInput(attrs={"class": "input font-mono"}),
            "status": forms.Select(attrs={"class": "select"}),
            "condition": forms.Select(attrs={"class": "select"}),
            "category": forms.Select(attrs={"class": "select"}),
            "supplier": forms.Select(attrs={"class": "select"}),
            "location": forms.Select(attrs={"class": "select"}),
            "requires_calibration": forms.CheckboxInput(attrs={"class": "checkbox"}),
            "image": forms.ClearableFileInput(attrs={"class": "input py-1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields.pop("initial_quantity")
            self.fields["sku"].disabled = False

    def clean_sku(self):
        return self.cleaned_data["sku"].strip().upper()

    def clean_max_stock_level(self):
        mx = self.cleaned_data.get("max_stock_level")
        if mx is not None and mx < (self.cleaned_data.get("reorder_level") or 0):
            raise forms.ValidationError(
                "Max stock level cannot be smaller than reorder level."
            )
        return mx

    def clean(self):
        cleaned = super().clean()
        location = cleaned.get("location")
        mx = cleaned.get("max_stock_level")
        if self.instance and self.instance.pk:
            return cleaned
        if location and mx:
            occupied = sum(t.quantity_on_hand for t in location.tools.all())
            if cleaned.get("initial_quantity") and occupied + cleaned["initial_quantity"] > location.capacity:
                self.add_error(
                    "location",
                    f"Location {location.code} capacity exceeded "
                    f"({occupied}/{location.capacity} occupied).",
                )
        return cleaned


class QuickEditForm(forms.Form):
    tool_id = forms.IntegerField(widget=forms.HiddenInput(attrs={"class": " input"}))
    quantity = forms.IntegerField(
        validators=[MinValueValidator(0)],
        widget=forms.NumberInput(attrs={"class": "input num w-16 text-right h-6"}),
    )
    status = forms.ChoiceField(
        choices=[("", "— keep —")] + list(Tool.Status.choices), required=False,
        widget=forms.Select(attrs={"class": "select h-6 py-0 text-2xs"}),
    )
    notes = forms.CharField(required=False, widget=forms.HiddenInput)
