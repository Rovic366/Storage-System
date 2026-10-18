from __future__ import annotations

from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.generic import ListView, TemplateView, View

from accounts.mixins import RoleRequiredMixin
from inventory import services as inv
from transactions import services as tx
from transactions.models import Checkout

from inventory.models import Tool

from .forms import AdjustForm, CheckoutFastForm, IssueForm, ReceiveForm, ReturnForm, TransferForm

OP_FORMS = {
    "receive": ReceiveForm,
    "issue": IssueForm,
    "transfer": TransferForm,
    "adjust": AdjustForm,
}
OP_LABELS = {
    "receive": "Receive stock",
    "issue": "Issue stock",
    "transfer": "Transfer",
    "adjust": "Adjust stock take",
}


class StockOpsView(RoleRequiredMixin, TemplateView):
    roles = ("stock",)
    template_name = "transactions/ops.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            op=self.kwargs.get("op", "receive"),
            forms={key: FormCls() for key, FormCls in OP_FORMS.items()},
            op_labels=OP_LABELS,
        )
        return ctx


class StockOpSubmitView(RoleRequiredMixin, View):
    roles = ("stock",)
    http_method_names = ["post"]

    def post(self, request, op: str):
        form_cls = OP_FORMS.get(op)
        if form_cls is None:
            messages.error(request, "Unknown stock operation.")
            return redirect("transactions:ops", op="receive")
        form = form_cls(request.POST)
        if form.is_valid():
            tool = form.tool
            try:
                if op == "receive":
                    target = form.cleaned_data.get("to_location")
                    inv.receive_stock(
                        tool, form.cleaned_data["quantity"], request.user,
                        to_location=target,
                        reference_no=form.cleaned_data.get("reference_no", ""),
                        notes=form.cleaned_data.get("notes", ""),
                    )
                    messages.success(
                        request,
                        f"Received {form.cleaned_data['quantity']} unit(s) into "
                        f"{tool.location.code} ({tool.sku}).",
                    )
                elif op == "issue":
                    inv.issue_stock(
                        tool, form.cleaned_data["quantity"], request.user,
                        reference_no=form.cleaned_data.get("reference_no", ""),
                        notes=form.cleaned_data.get("notes", ""),
                    )
                    messages.success(
                        request,
                        f"Issued {form.cleaned_data['quantity']} unit(s) of {tool.sku}.",
                    )
                elif op == "transfer":
                    inv.transfer_stock(
                        tool, form.cleaned_data["to_location"], request.user,
                        reference_no=form.cleaned_data.get("reference_no", ""),
                        notes=form.cleaned_data.get("notes", ""),
                    )
                    messages.success(
                        request,
                        f"{tool.sku} transferred to {tool.location.code}.",
                    )
                elif op == "adjust":
                    inv.adjust_stock(
                        tool, form.cleaned_data["delta"], request.user,
                        notes=form.cleaned_data.get("notes", ""),
                    )
                    messages.success(request, f"{tool.sku} adjusted by {form.cleaned_data['delta']}.")
                return redirect(f"{reverse('transactions:ops', args=[op])}")
            except inv.StockError as exc:
                form.add_error(None, str(exc))
        submitted = {op: form}
        ctx = {
            "op": op,
            "forms": {key: F() for key, F in OP_FORMS.items()},
            "submitted": submitted,
            "op_labels": OP_LABELS,
        }
        return render(self.request, "transactions/ops.html", ctx, status=400)


class CheckoutFastEntryView(RoleRequiredMixin, View):
    roles = ("checkout",)
    http_method_names = ["get", "post"]

    def get(self, request, *args, **kwargs):
        form = CheckoutFastForm()
        context = self._context(form)
        return render(request, "transactions/checkout_form.html", context)

    def post(self, request, *args, **kwargs):
        form = CheckoutFastForm(request.POST)
        if form.is_valid():
            tool = form.tool
            try:
                checkout = tx.checkout_tool(
                    tool,
                    borrower=form.cleaned_data["borrower"],
                    due_at=form.cleaned_data["due_at"],
                    issued_by=request.user,
                    notes=form.cleaned_data.get("notes", ""),
                )
                messages.success(
                    request,
                    f"{tool.sku} checked out to {checkout.borrower.username}; "
                    f"due {checkout.due_at:%Y-%m-%d %H:%M}.",
                )
                return redirect("transactions:checkout_list")
            except tx.StockError as exc:
                form.add_error(None, str(exc))
        context = self._context(form)
        return render(request, "transactions/checkout_form.html", context, status=400)

    def _context(self, form):
        tools = Tool.objects.active().order_by("sku")[:500]
        return {
            "form": form,
            "tool_list": tools,
            "overdue_now": Checkout.objects.overdue().count(),
        }


class CheckoutListView(RoleRequiredMixin, ListView):
    roles = ("checkout",)
    context_object_name = "checkouts"
    template_name = "transactions/checkout_list.html"
    paginate_by = 50

    def get_queryset(self):
        g = self.request.GET
        tab = g.get("tab", "open")
        qs = Checkout.objects.select_related("tool", "borrower", "issued_by")
        if tab == "open":
            qs = qs.open()
        elif tab == "overdue":
            qs = qs.overdue()
        elif tab == "returned":
            qs = qs.returned()
        if q := g.get("q", "").strip():
            qs = qs.filter(
                tool__sku__icontains=q
            ) | qs.filter(borrower__username__icontains=q) | qs.filter(
                tool__name__icontains=q
            )
            qs = qs.distinct()
        return qs.order_by("due_at" if tab in ("open", "overdue") else "-checked_out_at")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            tab=self.request.GET.get("tab", "open"),
            overdue_count=Checkout.objects.overdue().count(),
            querystring=self.request.GET.urlencode(),
        )
        return ctx


class ReturnCheckoutView(RoleRequiredMixin, View):
    roles = ("checkout",)
    http_method_names = ["get", "post"]

    def get(self, request, pk: int):
        from django.shortcuts import render

        checkout = get_object_or_404(
            Checkout.objects.select_related("tool", "borrower"), pk=pk
        )
        if checkout.returned_at:
            messages.info(request, "Already returned.")
            return redirect("transactions:checkout_list")
        form = ReturnForm()
        return render(request, "transactions/return_form.html",
                      {"checkout": checkout, "form": form})

    def post(self, request, pk: int):
        checkout = get_object_or_404(Checkout.objects.select_related("tool", "borrower"), pk=pk)
        form = ReturnForm(request.POST)
        if form.is_valid():
            try:
                updated = tx.return_tool(
                    checkout, request.user,
                    condition_in=form.cleaned_data.get("condition_in") or "",
                    notes=form.cleaned_data.get("notes") or "",
                )
                late = " — LATE" if updated.due_at and updated.due_at < updated.returned_at else ""
                messages.success(request, f"Return recorded for {updated.tool.sku}{late}.")
                return redirect("transactions:checkout_list")
            except tx.StockError as exc:
                form.add_error(None, str(exc))
        from django.shortcuts import render

        return render(request, "transactions/return_form.html",
                      {"checkout": checkout, "form": form}, status=400)
