/* ================================================================
   Sidebar JS — CRM Base
   Pin/unpin, hover expand, group toggle, Lucide icons
   ================================================================ */
(function () {
  'use strict';

  var PINNED_KEY = 'crm_sidebar_pinned';

  var sidebar   = document.getElementById('sidebar');
  var layout    = document.getElementById('appLayout');
  var pinBtn    = document.getElementById('sbPinBtn');

  if (!sidebar) return;

  var pinned = localStorage.getItem(PINNED_KEY) === 'true';

  /* ── Pin state ────────────────────────────────────────────── */
  function applyPin() {
    if (pinned) {
      sidebar.classList.add('sb-expanded');
      layout && layout.classList.add('sb-pinned');
      pinBtn && pinBtn.classList.add('pinned');
    } else {
      sidebar.classList.remove('sb-expanded');
      layout && layout.classList.remove('sb-pinned');
      pinBtn && pinBtn.classList.remove('pinned');
    }
  }

  pinBtn && pinBtn.addEventListener('click', function (e) {
    e.stopPropagation();
    pinned = !pinned;
    localStorage.setItem(PINNED_KEY, pinned);
    applyPin();
  });

  /* ── Hover (only when not pinned) ─────────────────────────── */
  sidebar.addEventListener('mouseenter', function () {
    if (!pinned) sidebar.classList.add('sb-expanded');
  });
  sidebar.addEventListener('mouseleave', function () {
    if (!pinned) sidebar.classList.remove('sb-expanded');
  });

  /* ── Collapsible groups ────────────────────────────────────── */
  var OPEN_KEY = 'crm_sb_open_groups';

  function getSavedGroups() {
    try { return JSON.parse(localStorage.getItem(OPEN_KEY) || '[]'); }
    catch (e) { return []; }
  }

  function saveOpenGroups() {
    var open = [];
    document.querySelectorAll('.sb-group.open').forEach(function (g) {
      if (g.dataset.group) open.push(g.dataset.group);
    });
    localStorage.setItem(OPEN_KEY, JSON.stringify(open));
  }

  // Restore previously open groups
  var savedGroups = getSavedGroups();
  document.querySelectorAll('.sb-group').forEach(function (group) {
    if (savedGroups.indexOf(group.dataset.group) !== -1) {
      group.classList.add('open');
    }
  });

  // Auto-open group containing active item
  document.querySelectorAll('.sb-item.active').forEach(function (item) {
    var group = item.closest('.sb-group');
    if (group) group.classList.add('open');
  });

  // Click to toggle
  document.querySelectorAll('.sb-group-header').forEach(function (header) {
    header.addEventListener('click', function () {
      var group = header.closest('.sb-group');
      if (group) {
        group.classList.toggle('open');
        saveOpenGroups();
      }
    });
  });

  /* ── Init ──────────────────────────────────────────────────── */
  applyPin();

  if (window.lucide) {
    lucide.createIcons();
  }

})();

/* ================================================================
   FAB — Floating Action Button
   ================================================================ */
(function () {
  'use strict';

  var fabContainer = document.getElementById('fabContainer');
  var fabMain      = document.getElementById('fabMain');
  if (!fabMain) return;

  var isOpen = false;

  function toggleFab() {
    isOpen = !isOpen;
    fabContainer.classList.toggle('open', isOpen);
  }

  fabMain.addEventListener('click', function (e) {
    e.stopPropagation();
    toggleFab();
  });

  document.addEventListener('click', function (e) {
    if (isOpen && fabContainer && !fabContainer.contains(e.target)) {
      isOpen = false;
      fabContainer.classList.remove('open');
    }
  });

})();

/* ================================================================
   Quick-Add Customer Modal
   ================================================================ */
(function () {
  'use strict';

  var overlay    = document.getElementById('quickAddOverlay');
  var closeBtn   = document.getElementById('quickAddClose');
  var form       = document.getElementById('quickAddForm');
  var submitBtn  = document.getElementById('quickAddSubmit');

  if (!overlay) return;

  window.openQuickAdd = function () {
    overlay.classList.add('open');
    // Close FAB if open
    var fab = document.getElementById('fabContainer');
    if (fab) fab.classList.remove('open');
    // Focus first input
    var first = overlay.querySelector('input');
    if (first) setTimeout(function () { first.focus(); }, 200);
  };

  function closeModal() {
    overlay.classList.remove('open');
    if (form) form.reset();
  }

  closeBtn && closeBtn.addEventListener('click', closeModal);
  overlay.addEventListener('click', function (e) {
    if (e.target === overlay) closeModal();
  });

  // Submit via fetch
  form && form.addEventListener('submit', function (e) {
    e.preventDefault();
    var name  = document.getElementById('qaName').value.trim();
    var phone = document.getElementById('qaPhone').value.trim();
    if (!name) { document.getElementById('qaName').focus(); return; }

    submitBtn.disabled = true;
    submitBtn.textContent = '...';

    var csrf = document.querySelector('meta[name="csrf-token"]').content;

    fetch('/customers/quick-add', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': csrf
      },
      body: JSON.stringify({ name: name, phone: phone })
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
      if (data.customer_id) {
        window.location.href = '/customers/' + data.customer_id;
      } else {
        alert(data.error || 'Error saving customer');
        submitBtn.disabled = false;
        submitBtn.textContent = submitBtn.dataset.label || 'Save';
      }
    })
    .catch(function () {
      alert('Network error. Please try again.');
      submitBtn.disabled = false;
      submitBtn.textContent = submitBtn.dataset.label || 'Save';
    });
  });

})();
