/* Storage OS shell: Alpine components, keyboard shortcuts, HTMX glue. */
(function () {
  "use strict";

  const THEME_KEY = "sos-theme";
  const DENSITY_KEY = "sos-density";
  const SIDEBAR_KEY = "sos-sidebar";

  // ---------------------------------------------------------------- settings

  window.toggleTheme = function () {
    const root = document.documentElement;
    const next = root.classList.contains("dark") ? "light" : "dark";
    root.classList.remove("dark", "light");
    root.classList.add(next);
    try { localStorage.setItem(THEME_KEY, next); } catch (e) {}
    if (window.Charts) window.Charts.rerenderAll();
  };

  window.toggleDensity = function () {
    const root = document.documentElement;
    const next = root.classList.contains("density-compact") ? "density-comfortable" : "density-compact";
    root.classList.remove("density-compact", "density-comfortable");
    root.classList.add(next);
    try { localStorage.setItem(DENSITY_KEY, next.replace("density-", "")); } catch (e) {}
  };

  window.deltaClass = function (direction) {
    if (direction === "down") return "text-rose-400";
    if (direction === "+") return "text-emerald-400";
    return "text-ink-3";
  };

  window.palette = function () {
    return {
      paletteOpen: false,
      q: "",
      loading: false,
      results: [],
      count: 0,
      index: 0,

      open() {
        this.paletteOpen = true;
        this.$nextTick(() => this.$refs.input && this.$refs.input.focus());
      },
      close() {
        this.paletteOpen = false;
        this.q = "";
        this.results = [];
      },
      onKey(e) {
        if (e.key === "/" && !this.paletteOpen && !e.ctrlKey && !e.altKey && !e.metaKey) {
          const el = document.activeElement;
          if (!el || !["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)) {
            e.preventDefault();
            this.open();
          }
        }
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
          e.preventDefault();
          this.paletteOpen ? this.close() : this.open();
        }
        if (e.key === "Escape" && this.paletteOpen) this.close();
      },
      search() {
        if (!this.q) { this.results = []; this.count = 0; this.loading = false; return; }
        this.loading = true;
        fetch("/api/search/?q=" + encodeURIComponent(this.q))
          .then((r) => r.json())
          .then((data) => {
            this.results = data.results || [];
            this.count = data.count || 0;
            this.index = 0;
            this.loading = false;
          })
          .catch(() => { this.loading = false; });
      },
      move(delta) {
        if (!this.results.length) return;
        const n = this.results.length;
        this.index = (this.index + delta + n) % n;
      },
      go() {
        const r = this.results[this.index];
        if (r) window.location.href = r.url;
      },
    };
  };

  // ---------------------------------------------------------------- shell

  window.shell = function () {
    return {
      paletteOpen: false,
      mobileNav: false,
      applyFilters(select, event) {
        const form = select.closest("form");
        const range = form.querySelector("[name=range]").value;
        const wh = form.querySelector("[name=wh]").value;
        const onDashboard = window.location.pathname === "/";

        if (onDashboard) {
          htmx.ajax("GET", "/partials/grid/?range=" + range + "&wh=" + encodeURIComponent(wh),
            { target: "#dash-grid", swap: "innerHTML" });
          history.pushState({}, "", "/?range=" + range + "&wh=" + encodeURIComponent(wh));
        } else {
          window.location.href = "/?range=" + range + "&wh=" + encodeURIComponent(wh);
        }
      },
    };
  };

  // ---------------------------------------------------------------- sidebar

  window.sidebar = function () {
    return {
      open: (function () {
        try { return localStorage.getItem(SIDEBAR_KEY) !== "0"; } catch (e) { return true; }
      })(),
      toggle() {
        this.open = !this.open;
        try { localStorage.setItem(SIDEBAR_KEY, this.open ? "1" : "0"); } catch (e) {}
      },
    };
  };

  window.deltaClass = function (direction) {
    if (direction === "down") return "text-rose-400";
    if (direction === "+") return "text-emerald-400";
    return "text-ink-3";
  };

  // ---------------------------------------------------------------- keys g-x

  document.addEventListener("DOMContentLoaded", function () {
    let pending = null;
    const MAP = { d: "/", i: "/inventory/", o: "/transactions/ops/receive/",
      k: "/transactions/checkouts/", m: "/maintenance/", r: "/reports/", a: "/accounts/audit/" };
    document.addEventListener("keydown", function (e) {
      const tag = (document.activeElement || {}).tagName;
      if (["INPUT", "TEXTAREA", "SELECT"].includes(tag)) pending = null;
      if (e.key === "Escape") pending = null;
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (e.key === "g") { pending = "g"; setTimeout(() => { pending = null; }, 700); return; }
      if (pending === "g" && MAP[e.key]) { window.location.href = MAP[e.key]; pending = null; }
    });

    // Refine sidebar active states by path prefix (beyond exact match).
    const path = window.location.pathname;
    document.querySelectorAll("aside a[href]").forEach(function (a) {
      const href = a.getAttribute("href");
      if (href && href !== "/" && path.startsWith(href) && href.startsWith("/")) a.classList.add("active");
      if (href === "/" && path === "/") a.classList.add("active");
    });

    // HTMX lifecycle: skeleton shimmer while swapping
    document.body.addEventListener("htmx:beforeSwap", function (evt) {
      const target = evt.detail && evt.detail.target;
      if (target && target.id === "dash-grid") {
        target.classList.add("htmx-swap-pending");
      }
    });
    document.body.addEventListener("htmx:afterSwap", function (evt) {
      const target = evt.detail && evt.detail.target;
      if (target && target.id === "dash-grid") {
        target.classList.remove("htmx-swap-pending");
      }
      if (window.Charts) window.Charts.rerenderAll();
    });
    document.body.addEventListener("htmx:responseError", function (evt) {
      console.warn("HTMX request failed", evt.detail && evt.detail.xhr && evt.detail.xhr.status);
    });

    // Row-level HTMX loading for drawer links inside tables
    document.addEventListener("click", function (e) {
      const drawerLink = e.target.closest("[data-drawer]");
      if (drawerLink) {
        e.preventDefault();
        const drawer = document.getElementById("tool-drawer");
        if (!drawer) return;
        drawer.classList.remove("hidden");
        drawer.innerHTML = "<div class='drawer-skeleton'></div>";
        htmx.ajax("GET", drawerLink.getAttribute("data-drawer"), drawer, "innerHTML");
      }
      if (e.key === "Escape") {
        const drawer = document.getElementById("tool-drawer");
        if (drawer) drawer.classList.add("hidden");
      }
    });
  });

  // -----------------------------------------------------------------> escape closes drawer
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") {
      const drawer = document.getElementById("tool-drawer");
      if (drawer) drawer.classList.add("hidden");
    }
  });

  // ---------------------------------------------------------------- table helpers

  function getCookie(name) {
    const value = document.cookie ? document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)") : null;
    return value ? value.pop() : "";
  }

  window.tableCols = function () {
    return {
      hidden: (function () {
        try { return JSON.parse(localStorage.getItem("sos-cols") || "[]"); }
        catch (e) { return []; }
      })(),
      toggleCol(key) {
        const i = this.hidden.indexOf(key);
        if (i >= 0) this.hidden.splice(i, 1); else this.hidden.push(key);
        try { localStorage.setItem("sos-cols", JSON.stringify(this.hidden)); } catch (e) {}
      },
    };
  };

  window.stopRow = function (event) {
    event.stopPropagation();
  };

  window.selectAllRows = function (master) {
    document.querySelectorAll("#inv-tbody input[type=checkbox][data-row-id]")
      .forEach(function (cb) { cb.checked = master.checked; });
    window.updateBulkCount();
  };

  window.updateBulkCount = function () {
    const count = document.querySelectorAll("#inv-tbody input[type=checkbox][data-row-id]:checked").length;
    const el = document.getElementById("bulk-count");
    if (el) el.textContent = String(count);
  };

  window.bulkMoveDialog = function () {}; // controlled by Alpine toggle

  function selectedIds() {
    return Array.from(
      document.querySelectorAll("#inv-tbody input[type=checkbox][data-row-id]:checked")
    ).map(function (cb) { return cb.value; });
  }

  window.bulkAction = function (action) {
    const ids = selectedIds();
    if (!ids.length) return;
    let moveTo = "";
    if (action === "move") {
      const sel = document.getElementById("bulk-move-target");
      if (!sel || !sel.value) { alert("Pick a destination bin first."); return; }
      moveTo = sel.value;
    }
    if (action === "retire" && !confirm("Retire " + ids.length + " tool(s)? This cannot be undone.")) return;
    const form = document.createElement("form");
    form.method = "POST";
    form.action = document.getElementById("inv-table").dataset.bulkUrl || "/inventory/bulk/";
    const set = function (name, value) {
      const input = document.createElement("input");
      input.type = "hidden"; input.name = name; input.value = value;
      form.appendChild(input);
    };
    set("csrfmiddlewaretoken", getCookie("csrftoken"));
    set("action", action);
    ids.forEach(function (id) { set("ids", id); });
    if (moveTo) set("target_location", moveTo);
    document.body.appendChild(form);
    form.submit();
  };
})();
