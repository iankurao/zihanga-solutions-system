// Global utility functions

// The reference of the record a save created (WL-..., SUB-..., HRV-..., LOT-...).
function createdReference(result) {
  var keys = ['business_id', 'harvest_code', 'event_code', 'check_code', 'approval_code', 'lot_code'];
  function find(value, depth) {
    if (!value || typeof value !== 'object' || depth > 2) return null;
    for (var i = 0; i < keys.length; i++) {
      if (typeof value[keys[i]] === 'string' && value[keys[i]]) return value[keys[i]];
    }
    for (var key in value) {
      var found = find(value[key], depth + 1);
      if (found) return found;
    }
    return null;
  }
  return find(result, 0);
}

// Tell the user what happened to a save, where they can see it: a message
// pinned to the bottom of the screen (the page may be scrolled far below the
// top bar) and a line under the form's submit button that stays until the
// next entry. type is 'success' or 'error'.
function showFormResult(form, message, type) {
  var ok = type === 'success';
  var toast = document.getElementById('notification');
  if (toast) {
    toast.className = 'alert erp-toast ' + (ok ? 'alert-success' : 'alert-danger');
    toast.setAttribute('role', ok ? 'status' : 'alert');
    toast.textContent = '';
    var icon = document.createElement('i');
    icon.className = 'fas ' + (ok ? 'fa-check-circle' : 'fa-exclamation-circle');
    icon.setAttribute('aria-hidden', 'true');
    var text = document.createElement('span');
    text.textContent = message;
    var close = document.createElement('button');
    close.type = 'button';
    close.className = 'erp-toast-close';
    close.setAttribute('aria-label', 'Close message');
    close.textContent = '\u00d7';
    close.addEventListener('click', function() { toast.style.display = 'none'; });
    toast.append(icon, text, close);
    toast.style.display = 'flex';
    clearTimeout(showFormResult.timer);
    // Errors stay until closed; success fades after a few seconds.
    if (ok) showFormResult.timer = setTimeout(function() { toast.style.display = 'none'; }, 6000);
  }
  if (form) {
    var line = form.querySelector('.form-result');
    if (!line) {
      line = document.createElement('p');
      line.className = 'form-result';
      line.setAttribute('aria-live', 'polite');
      var button = form.querySelector('button[type="submit"]');
      (button ? button.parentNode : form).insertBefore(line, button ? button.nextSibling : null);
      // The line describes the last save; it goes once the next entry starts.
      form.addEventListener('input', function() { line.hidden = true; });
    }
    line.textContent = (ok ? '\u2713 ' : '\u26a0 ') + message;
    line.classList.toggle('is-error', !ok);
    line.hidden = false;
  }
}

function showSection(sectionId, element) {
  document.querySelectorAll('.section').forEach(function(section) {
    section.classList.remove('active');
  });
  document.querySelectorAll('.nav-link').forEach(function(link) {
    link.classList.remove('active');
  });
  var section = document.getElementById(sectionId);
  if (section) {
    section.classList.add('active');
  } else {
    console.warn("Section with id '" + sectionId + "' not found.");
    return;
  }
  // Pick-lists follow records saved since the page was opened.
  if (sectionId === 'drying' && window.refreshDryingData) window.refreshDryingData();
  if (sectionId === 'frass' && window.refreshFrassLots) window.refreshFrassLots(true);
  if (element) {
    element.classList.add('active');
  }
}

function showAlert(type, message) {
  var successAlert = document.getElementById('successAlert');
  var errorAlert = document.getElementById('errorAlert');
  if (!successAlert || !errorAlert) return;
  if (type === 'success') {
    var span = successAlert.querySelector('span');
    if (span) span.textContent = message;
    successAlert.style.display = 'block';
    errorAlert.style.display = 'none';
  } else {
    var span = errorAlert.querySelector('span');
    if (span) span.textContent = message;
    errorAlert.style.display = 'block';
    successAlert.style.display = 'none';
  }
  setTimeout(function() {
    successAlert.style.display = 'none';
    errorAlert.style.display = 'none';
  }, 5000);
}

function logout() {
  if (confirm('Are you sure you want to logout?')) {
    window.location.href = '/logout';
  }
}

function toggleSidebarSection(sectionId) {
  var group = document.getElementById(sectionId);
  if (group) {
    group.style.display = (group.style.display === 'none' || group.style.display === '') ? 'block' : 'none';
  }
}

// Larvae Feeding & Facility Section JavaScript

document.addEventListener('DOMContentLoaded', function() {
    // Track form submission states to prevent multiple submissions
    const formSubmissionStates = new Map();
    
    // Form elements
    const forms = {
        // Waste Management
        wasteSourcing: document.getElementById('wasteSourcingForm'),
        storageRecords: document.getElementById('storageRecordsForm'),
        processingRecords: document.getElementById('processingRecordsForm'),
        wasteEnvironmentalMonitoring: document.getElementById('wasteEnvironmentalMonitoringForm'),
        // Feeding
        feedingRecords: document.getElementById('feedingRecordsForm'),
        feedingEnvironmentalMonitoring: document.getElementById('environmentalMonitoringForm'),
        substratePreparation: document.getElementById('substratePreparationForm'),
        healthIntervention: document.getElementById('healthInterventionForm'),
        harvestYield: document.getElementById('harvestYieldForm'),
        feedingSchedule: document.getElementById('feedingScheduleForm'),
        // Facility
        cageMonitoring: document.getElementById('cageMonitoringForm'),
        facilityMaintenance: document.getElementById('facilityMaintenanceForm'),
        pupaeTransition: document.getElementById('pupaeTransitionForm'),
        eggCollection: document.getElementById('eggCollectionForm'),
        baitPreparation: document.getElementById('baitPreparationForm'),
        // Hatchery
        batchInfo: document.getElementById('batchInformationForm'),
        hatcheryEnvironmentalMonitoring: document.getElementById('hatcheryEnvironmentalMonitoringForm'),
        cleaningSanitation: document.getElementById('cleaningForm'),
        problemsSolutions: document.getElementById('problemsSolutionsForm')
    };

    // Larval forms record an event on the production batch named on the form.
    const productionEventTypes = {
        'feedingSchedule': 'feeding',
        'feedingEnvironmentalMonitoring': 'monitoring',
        'healthIntervention': 'health',
        'harvestYield': 'harvest'
    };

    // API endpoints
    const apiEndpoints = {
        'wasteSourcing': 'waste-sourcing',
        'substratePreparation': 'substrate-preparation',
        // Farm operation logs (backend/domains/farm_operations.py): each
        // record carries the farm, site and facility chosen on the form.
        'storageRecords': 'farm-operations/waste-storage',
        'processingRecords': 'farm-operations/waste-processing',
        'wasteEnvironmentalMonitoring': 'farm-operations/waste-monitoring',
        'batchInfo': 'farm-operations/hatchery-batch',
        'feedingRecords': 'farm-operations/hatchery-feeding',
        'hatcheryEnvironmentalMonitoring': 'farm-operations/hatchery-monitoring',
        'cleaningSanitation': 'farm-operations/hatchery-cleaning',
        'problemsSolutions': 'farm-operations/hatchery-problem',
        'cageMonitoring': 'farm-operations/cage-monitoring',
        'facilityMaintenance': 'farm-operations/facility-maintenance',
        'pupaeTransition': 'farm-operations/pupae-transition',
        'eggCollection': 'farm-operations/egg-collection',
        'baitPreparation': 'farm-operations/bait-preparation'
    };

    // Notification function
    function showNotification(message, type = 'success', form = null) {
        showFormResult(form, message, type === 'success' ? 'success' : 'error');
    }

    let availableWasteLots = [];
    let locationRows = [];

    function uniqueBy(rows, key) {
        const seen = new Map();
        rows.forEach(row => {
            if (row[key] != null && !seen.has(row[key])) seen.set(row[key], row);
        });
        return [...seen.values()];
    }

    // Dates of things that happened start at today and cannot be later;
    // planned dates are left empty. Times start at now. People fields start
    // with the signed-in person's name. All stay editable.
    const PLANNED_DATE_FIELDS = new Set(['followUpDate', 'fermentationReady', 'expectedHatchDate']);
    const PERSON_FIELDS = new Set(['collectionPersonnel', 'handlerOperator', 'operator', 'personnel',
        'cleaning_personnel', 'qcPersonnel', 'reviewedBy', 'inspector']);
    const twoDigits = n => String(n).padStart(2, '0');
    const localToday = () => {
        const d = new Date();
        return `${d.getFullYear()}-${twoDigits(d.getMonth() + 1)}-${twoDigits(d.getDate())}`;
    };
    const localNow = () => {
        const d = new Date();
        return `${twoDigits(d.getHours())}:${twoDigits(d.getMinutes())}`;
    };

    // ---- Production batch pickers and tray suggestions -------------------------
    // Batches are chosen from a list instead of typed, so a number cannot be
    // mistyped; harvests only offer batches that are ready for harvest.
    const BATCH_FIELDS = {
        feedingProductionBatchId: 'open', monitoringProductionBatchId: 'open',
        healthProductionBatchId: 'open', harvestProductionBatch: 'ready'
    };
    const BATCH_STATUS_TEXT = {
        PLANNED: 'Planned', ACTIVE: 'Active', MONITORING: 'Monitoring', READY_FOR_HARVEST: 'Ready for harvest',
        HARVESTED: 'Harvested', PAUSED: 'Paused', HEALTH_ALERT: 'Health alert'
    };
    const TRAY_FIELDS = { feedingScheduleForm: 'tray_reference', healthInterventionForm: 'tray_reference',
        environmentalMonitoringForm: 'tray_facility_id' };
    let pickerBatches = [];
    let pickerUnits = [];
    const batchRef = batch => batch.business_id || batch.batch_code;

    function batchLabel(batch) {
        const age = batch.age_days == null ? null : `${batch.age_days} day${batch.age_days === 1 ? '' : 's'}`;
        return [batchRef(batch), BATCH_STATUS_TEXT[batch.status] || batch.status, batch.facility_name, age]
            .filter(Boolean).join(' · ');
    }

    function asSelect(field) {
        if (field.tagName === 'SELECT') return field;
        const select = document.createElement('select');
        select.id = field.id;
        select.name = field.name;
        select.className = field.className;
        select.required = field.required;
        field.replaceWith(select);
        return select;
    }

    function refreshTrayOptions(form) {
        const name = form && TRAY_FIELDS[form.id];
        const tray = name && form.querySelector(`[name="${name}"]`);
        if (!tray) return;
        const chosen = (form.querySelector('[name="production_batch_id"]') || {}).value;
        const batch = pickerBatches.find(b => batchRef(b) === chosen);
        const units = pickerUnits
            .filter(unit => !batch || unit.facility_id === batch.facility_id)
            .sort((a, b) => (b.batch_business_id === chosen) - (a.batch_business_id === chosen));
        const listId = `${form.id}Trays`;
        let list = document.getElementById(listId);
        if (!list) {
            list = document.createElement('datalist');
            list.id = listId;
            form.appendChild(list);
            tray.setAttribute('list', listId);
            tray.setAttribute('autocomplete', 'off');
        }
        list.replaceChildren(...units.map(unit => {
            const holds = unit.batch_business_id ? ` (holds ${unit.batch_business_id})` : ' (free)';
            const option = new Option(`${unit.name}${holds}`, unit.unit_code);
            return option;
        }));
        // The batch's own bio-pod is the usual answer.
        const own = units.filter(unit => unit.batch_business_id === chosen);
        if (own.length === 1 && !tray.value) tray.value = own[0].unit_code;
    }

    async function loadBatchPickers() {
        try {
            const [batches, units] = await Promise.all([
                fetch('/api/production/batches', { credentials: 'include' }),
                fetch('/api/production/units', { credentials: 'include' })
            ]);
            pickerBatches = batches.ok ? ((await batches.json()).data || []) : [];
            pickerUnits = units.ok ? ((await units.json()).data || []) : [];
        } catch (error) {
            pickerBatches = [];
            pickerUnits = [];
        }
        Object.entries(BATCH_FIELDS).forEach(([id, which]) => {
            const field = document.getElementById(id);
            if (!field) return;
            const select = asSelect(field);
            const keep = select.value;
            const choices = pickerBatches.filter(batch => which === 'ready'
                ? batch.status === 'READY_FOR_HARVEST'
                : !['COMPLETED', 'CANCELLED'].includes(batch.status));
            const empty = which === 'ready' ? 'No batch is ready for harvest' : 'No open production batches';
            select.replaceChildren(new Option(choices.length ? 'Select production batch' : empty, ''));
            choices.forEach(batch => select.add(new Option(batchLabel(batch), batchRef(batch))));
            if (keep && choices.some(batch => batchRef(batch) === keep)) select.value = keep;
            else if (choices.length === 1) select.value = batchRef(choices[0]);
            refreshTrayOptions(select.form);
        });
    }

    document.addEventListener('change', event => {
        if (event.target.name === 'production_batch_id') refreshTrayOptions(event.target.form);
    });

    // ---- Checks as you type ---------------------------------------------------------
    function fieldLabel(field) {
        const label = field.id && document.querySelector(`label[for="${field.id}"]`);
        return (label ? label.textContent : field.name).replace(/\*/g, '').trim();
    }

    function fieldProblem(field) {
        if (field.type === 'hidden' || field.disabled || !field.willValidate) return '';
        const v = field.validity;
        const label = fieldLabel(field);
        if (v.valueMissing || (field.required && !String(field.value).trim())) return `${label} is required`;
        if (v.badInput) return `${label}: enter a number`;
        if (v.rangeUnderflow) return `${label} must be at least ${field.min}`;
        if (v.rangeOverflow) {
            return field.type === 'date' ? `${label} cannot be in the future` : `${label} must be at most ${field.max}`;
        }
        if (v.typeMismatch || v.patternMismatch) return `${label} is not valid`;
        return '';
    }

    function showFieldProblem(field, problem) {
        field.classList.toggle('is-invalid', !!problem);
        let feedback = field.nextElementSibling;
        if (!(feedback && feedback.classList.contains('invalid-feedback'))) {
            if (!problem) return;
            feedback = document.createElement('div');
            feedback.className = 'invalid-feedback';
            field.insertAdjacentElement('afterend', feedback);
        }
        if (problem) feedback.textContent = problem;
    }

    // Every problem in the form, marked on its field; the first one gets focus.
    function reportProblems(form, extra = {}) {
        const problems = [];
        form.querySelectorAll('input, select, textarea').forEach(field => {
            const problem = extra[field.name] || fieldProblem(field);
            showFieldProblem(field, problem);
            if (problem) problems.push({ field, problem });
        });
        Object.entries(extra).forEach(([name, problem]) => {
            if (!problems.some(p => p.field.name === name)) problems.push({ field: null, problem });
        });
        if (!problems.length) return false;
        const shown = problems.slice(0, 4).map(p => p.problem).join('; ');
        const more = problems.length > 4 ? ` and ${problems.length - 4} more` : '';
        showFormResult(form, `Not saved yet. ${shown}${more}.`, 'error');
        const first = problems.find(p => p.field);
        if (first) {
            first.field.scrollIntoView({ block: 'center', behavior: 'smooth' });
            first.field.focus({ preventScroll: true });
        }
        return true;
    }

    window.reportFormProblems = reportProblems;

    function enableLiveChecks() {
        document.querySelectorAll('.main-content form').forEach(form => {
            // The page shows its own messages instead of the browser's bubbles.
            form.setAttribute('novalidate', '');
            form.addEventListener('focusout', event => {
                if (event.target.matches('input, select, textarea')) {
                    showFieldProblem(event.target, fieldProblem(event.target));
                }
            });
            form.addEventListener('change', event => {
                if (event.target.matches('select, input[type="date"], input[type="time"]')) {
                    showFieldProblem(event.target, fieldProblem(event.target));
                }
            });
        });
    }

    // ---- Last 5 entries under each form -----------------------------------------------
    const RECENT_KIND = {
        wasteSourcing: 'waste', substratePreparation: 'substrate', feedingSchedule: 'feeding',
        feedingEnvironmentalMonitoring: 'monitoring', healthIntervention: 'health', harvestYield: 'harvest'
    };

    function recentKind(formType) {
        if (RECENT_KIND[formType]) return RECENT_KIND[formType];
        const endpoint = apiEndpoints[formType] || '';
        return endpoint.startsWith('farm-operations/') ? endpoint.slice('farm-operations/'.length) : null;
    }

    function recentWhen(value) {
        if (!value) return '';
        if (/^\d{4}-\d{2}-\d{2}$/.test(value)) return value;
        const date = new Date(value);
        return isNaN(date) ? value : date.toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
    }

    async function loadRecentEntries(form, formType) {
        const kind = recentKind(formType);
        if (!form || !kind) return;
        let box = form.nextElementSibling;
        if (!(box && box.classList.contains('recent-entries'))) {
            box = document.createElement('section');
            box.className = 'recent-entries';
            box.setAttribute('aria-label', 'Last 5 entries');
            const heading = document.createElement('h3');
            heading.textContent = 'Last 5 entries';
            box.append(heading, document.createElement('ul'));
            form.insertAdjacentElement('afterend', box);
        }
        const list = box.querySelector('ul');
        const line = text => { const li = document.createElement('li'); li.className = 'recent-empty'; li.textContent = text; return li; };
        try {
            const response = await fetch(`/api/data-entry/recent?kind=${encodeURIComponent(kind)}`, { credentials: 'include' });
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.message);
            if (!payload.data.length) { list.replaceChildren(line('Nothing recorded yet.')); return; }
            list.replaceChildren(...payload.data.map(row => {
                const li = document.createElement('li');
                const ref = document.createElement(row.href ? 'a' : 'strong');
                if (row.href) ref.href = row.href;
                ref.className = 'recent-ref';
                ref.textContent = row.ref;
                const text = document.createElement('span');
                text.className = 'recent-text';
                text.textContent = row.text;
                const meta = document.createElement('span');
                meta.className = 'recent-meta';
                meta.textContent = [recentWhen(row.when), row.by].filter(Boolean).join(' · ');
                li.append(ref, text, meta);
                return li;
            }));
        } catch (error) {
            list.replaceChildren(line('Could not load the last entries.'));
        }
    }

    function loadAllRecentEntries() {
        Object.entries(forms).forEach(([formType, form]) => loadRecentEntries(form, formType));
    }

    function applyFormDefaults() {
        const page = document.querySelector('.main-content');
        if (!page) return;
        const today = localToday();
        page.querySelectorAll('input[type="date"]').forEach(input => {
            if (PLANNED_DATE_FIELDS.has(input.id)) return;
            input.max = today;
            if (!input.value) input.value = input.defaultValue = today;
        });
        page.querySelectorAll('input[type="time"]').forEach(input => {
            if (!input.value) input.value = localNow();
        });
        // After a save the form resets: the time moves on to now again.
        page.querySelectorAll('form').forEach(form => form.addEventListener('reset', () => setTimeout(() => {
            form.querySelectorAll('input[type="time"]').forEach(input => { input.value = localNow(); });
        }, 0)));
        (window.currentUser || Promise.resolve(null)).then(profile => {
            const name = profile && (profile.full_name || profile.username);
            if (!name) return;
            page.querySelectorAll('input[type="text"]').forEach(input => {
                if (PERSON_FIELDS.has(input.name) && !input.value) input.value = input.defaultValue = name;
            });
        });
    }

    function fillLocationSelect(select, rows, idKey, nameKey, placeholder, preferred) {
        const previousValue = select.value;
        select.replaceChildren(new Option(placeholder, ''));
        uniqueBy(rows, idKey).forEach(row => select.add(new Option(row[nameKey], row[idKey])));
        const has = value => value && [...select.options].some(option => option.value === String(value));
        if (has(previousValue)) {
            select.value = previousValue;
        } else if (has(preferred)) {
            select.value = String(preferred);
        } else if (select.options.length === 2) {
            select.selectedIndex = 1;
        }
    }

    // Each form remembers the farm, site and facility it was last used for on
    // this device, so a farmer picks their place once.
    function placeKey(picker) {
        const form = picker.closest('form');
        return form && form.id ? 'zehunger.place.' + form.id : null;
    }
    function rememberedPlace(picker) {
        try { return JSON.parse(localStorage.getItem(placeKey(picker)) || 'null') || {}; } catch (e) { return {}; }
    }
    function rememberPlace(picker) {
        const key = placeKey(picker);
        if (!key) return;
        const value = cls => (picker.querySelector(cls) || {}).value || '';
        try {
            localStorage.setItem(key, JSON.stringify({
                farm: value('.location-farm'), site: value('.location-site'), facility: value('.location-facility')
            }));
        } catch (e) { /* storage blocked: the form still works */ }
    }

    // Farm -> Site -> Facility selects, limited to active locations the
    // server reports as visible to the signed-in user.
    function renderLocationPicker(picker) {
        const farm = picker.querySelector('.location-farm');
        const site = picker.querySelector('.location-site');
        const facility = picker.querySelector('.location-facility');
        const saved = rememberedPlace(picker);
        fillLocationSelect(
            farm, locationRows, 'farm_id', 'farm_name',
            locationRows.length ? 'Select farm' : 'No farms available — ask an administrator', saved.farm
        );
        const sites = locationRows.filter(row => String(row.farm_id) === farm.value);
        fillLocationSelect(site, sites, 'site_id', 'site_name', farm.value ? 'Select site' : 'Select a farm first',
            saved.site);
        const facilities = sites.filter(row => String(row.site_id) === site.value);
        fillLocationSelect(
            facility, facilities, 'facility_id', 'facility_name',
            site.value ? 'Select facility' : 'Select a site first', saved.facility
        );
    }

    async function loadLocationHierarchy() {
        const pickers = document.querySelectorAll('.location-picker');
        if (!pickers.length) return;
        try {
            const response = await fetch('/api/locations/hierarchy', { credentials: 'include' });
            if (!response.ok) throw new Error('Could not load farms and facilities');
            const result = await response.json();
            locationRows = (result.data || []).filter(row =>
                row.facility_id && row.farm_status === 'active' &&
                row.site_status === 'active' && row.facility_status === 'active'
            );
        } catch (error) {
            console.error('Could not load location hierarchy:', error);
            locationRows = [];
        }
        pickers.forEach(renderLocationPicker);
        refreshWasteLotSelects();
        renderHatcheryBatches();
        document.dispatchEvent(new Event('locations-loaded'));
    }

    document.querySelectorAll('.location-picker').forEach(picker => {
        picker.addEventListener('change', event => {
            if (event.target.matches('.location-facility')) rememberPlace(picker);
            if (!event.target.matches('.location-farm, .location-site')) return;
            renderLocationPicker(picker);
            if (picker.id === 'substrateLocationPicker') refreshWasteLotSelects();
        });
        const form = picker.closest('form');
        if (form) {
            // form.reset() clears values first; rebuild dependent options after.
            form.addEventListener('reset', () => setTimeout(() => {
                renderLocationPicker(picker);
                if (picker.id === 'substrateLocationPicker') refreshWasteLotSelects();
            }, 0));
        }
    });

    function selectedSubstrateScope() {
        return {
            farmId: document.getElementById('substrateFarmId')?.value || '',
            siteId: document.getElementById('substrateSiteId')?.value || ''
        };
    }

    function refreshWasteLotSelects() {
        const scope = selectedSubstrateScope();
        const site = scope.farmId && scope.siteId;
        document.querySelectorAll('.substrate-waste-lot').forEach(select => {
            const previousValue = select.value;
            select.replaceChildren(new Option('Select an available Waste Lot', ''));
            const matchingLots = site
                ? availableWasteLots.filter(lot =>
                    String(lot.farm_id) === scope.farmId && String(lot.site_id) === scope.siteId)
                : [];
            matchingLots.forEach(lot => {
                select.add(new Option(
                    `${lot.business_id} — ${lot.source_name} — ${lot.available_quantity} ${lot.unit} available`,
                    lot.id
                ));
            });
            if (!matchingLots.length) {
                select.add(new Option(
                    site ? 'No available lots for this farm/site' : 'Select the farm and site first',
                    ''
                ));
            }
            if ([...select.options].some(option => option.value === previousValue && previousValue)) {
                select.value = previousValue;
            }
            select.dispatchEvent(new Event('change'));
        });
    }

    function addSubstrateInputRow() {
        const container = document.getElementById('substrateInputs');
        if (!container) return;

        const row = document.createElement('div');
        row.className = 'form-row substrate-input-row';
        const rowNumber = container.children.length + 1;

        const lotGroup = document.createElement('div');
        lotGroup.className = 'form-group substrate-lot-group';
        const lotLabel = document.createElement('label');
        lotLabel.htmlFor = `substrateWasteLot-${rowNumber}`;
        lotLabel.textContent = 'Waste Lot';
        const lotSelect = document.createElement('select');
        lotSelect.id = `substrateWasteLot-${rowNumber}`;
        lotSelect.name = 'wasteLotId';
        lotSelect.className = 'form-control substrate-waste-lot';
        lotSelect.required = true;
        lotSelect.addEventListener('change', () => {
            const selectedLot = availableWasteLots.find(lot => String(lot.id) === lotSelect.value);
            const quantityInput = row.querySelector('.substrate-quantity-used');
            const quantityLabel = row.querySelector('.substrate-quantity-label');
            if (selectedLot) {
                quantityInput.max = selectedLot.available_quantity;
                quantityLabel.textContent = `Quantity used (kg; ${selectedLot.available_quantity} available)`;
            } else {
                quantityInput.removeAttribute('max');
                quantityLabel.textContent = 'Quantity used (kg)';
            }
        });
        lotGroup.append(lotLabel, lotSelect);

        const quantityGroup = document.createElement('div');
        quantityGroup.className = 'form-group substrate-quantity-group';
        const quantityLabel = document.createElement('label');
        quantityLabel.htmlFor = `substrateQuantityUsed-${rowNumber}`;
        quantityLabel.className = 'substrate-quantity-label';
        quantityLabel.textContent = 'Quantity used (kg)';
        const quantityInput = document.createElement('input');
        quantityInput.type = 'number';
        quantityInput.id = `substrateQuantityUsed-${rowNumber}`;
        quantityInput.name = 'quantityUsed';
        quantityInput.className = 'form-control substrate-quantity-used';
        quantityInput.min = '0.001';
        quantityInput.step = '0.001';
        quantityInput.required = true;
        quantityGroup.append(quantityLabel, quantityInput);

        const actions = document.createElement('div');
        actions.className = 'form-group substrate-input-actions';
        const removeButton = document.createElement('button');
        removeButton.type = 'button';
        removeButton.className = 'btn btn-secondary';
        removeButton.textContent = 'Remove';
        removeButton.addEventListener('click', () => {
            if (container.querySelectorAll('.substrate-input-row').length > 1) row.remove();
        });
        actions.append(removeButton);
        row.append(lotGroup, quantityGroup, actions);
        container.append(row);
        refreshWasteLotSelects();
    }

    async function refreshSubstrateChainData() {
        const recordsContainer = document.getElementById('substrateBatchRecords');
        try {
            const [lotsResponse, batchesResponse] = await Promise.all([
                fetch('/api/waste-lots', { credentials: 'include' }),
                fetch('/api/substrate-batches', { credentials: 'include' })
            ]);
            if (!lotsResponse.ok || !batchesResponse.ok) {
                throw new Error('Could not load Waste Lots or Substrate Batches');
            }
            const lotsResult = await lotsResponse.json();
            const batchesResult = await batchesResponse.json();
            availableWasteLots = lotsResult.data || [];
            refreshWasteLotSelects();
            if (!recordsContainer) return;

            recordsContainer.replaceChildren();
            const batches = batchesResult.data || [];
            if (!batches.length) {
                const emptyState = document.createElement('p');
                emptyState.textContent = 'No Substrate Batches recorded yet.';
                recordsContainer.append(emptyState);
                return;
            }
            batches.forEach(batch => {
                const card = document.createElement('article');
                card.className = 'substrate-batch-card';
                const heading = document.createElement('h4');
                heading.textContent = `${batch.business_id} · ${batch.preparation_date}`;
                const site = document.createElement('p');
                const locationText = batch.facility_name
                    ? `${batch.farm_name} / ${batch.site_name} / ${batch.facility_name}`
                    : `${batch.farm_site} (older record, no location)`;
                site.textContent = `Location: ${locationText} · Total input: ${batch.total_input_weight_kg} kg`;
                const inputs = document.createElement('ul');
                (batch.inputs || []).forEach(input => {
                    const item = document.createElement('li');
                    item.textContent =
                        `${input.business_id} (${input.source_name}) — ${input.quantity_used} ${input.unit}`;
                    inputs.append(item);
                });
                card.append(heading, site, inputs);
                recordsContainer.append(card);
            });
        } catch (error) {
            console.error('Could not load Waste Lot traceability:', error);
            if (recordsContainer) {
                recordsContainer.textContent = 'Waste Lot availability and batch history could not be loaded.';
            }
        }
    }

    window.refreshSubstrateChainData = refreshSubstrateChainData;

    // Validate substrate batch ID exists
    async function validateSubstrateBatchId(batchId) {
        try {
            const response = await fetch(`/api/substrate/batches/${batchId}`, { credentials: 'include' });
            if (!response.ok) {
                throw new Error('Substrate batch ID not found');
            }
            return true;
        } catch (error) {
            console.error('Error validating substrate batch ID:', error);
            return false;
        }
    }

    // Form validation
    async function validateForm(form, formType) {
        console.log(`Validating form: ${formType}`);
        const errors = {};
        const formData = new FormData(form);
        
        console.log('Form fields:', Array.from(formData.entries()));
        
        form.querySelectorAll('input, select, textarea').forEach(field => {
            const problem = fieldProblem(field);
            if (problem) errors[field.name] = problem;
        });

        // Form-specific validation
        switch(formType) {
            case 'wasteSourcing': {
                const wasteWeight = parseFloat(formData.get('wasteWeight') || formData.get('waste_weight'));
                if (!isNaN(wasteWeight) && wasteWeight <= 0) {
                    errors.wasteWeight = 'Weight must be greater than 0';
                }
                break;
            }
            case 'storageRecords': {
                const storageDuration = parseInt(formData.get('storageDuration') || formData.get('storage_duration'));
                if (!isNaN(storageDuration) && storageDuration <= 0) {
                    errors.storageDuration = 'Storage duration must be greater than 0';
                }
                break;
            }
            case 'processingRecords': {
                const wasteProcessed = parseFloat(formData.get('wasteProcessed') || formData.get('waste_processed'));
                if (!isNaN(wasteProcessed) && wasteProcessed <= 0) {
                    errors.wasteProcessed = 'Waste processed must be greater than 0';
                }
                const wasteReduction = parseFloat(formData.get('wasteReduction') || formData.get('waste_reduction'));
                if (!isNaN(wasteReduction) && wasteReduction < 0) {
                    errors.wasteReduction = 'Waste reduction (kg) must be 0 or greater';
                }
                break;
            }
            case 'wasteEnvironmentalMonitoring': {
                const temp = parseFloat(formData.get('temperature'));
                if (!isNaN(temp) && (temp < -50 || temp > 100)) {
                    errors.temperature = 'Temperature must be between -50 and 100';
                }
                const waterConsistency = formData.get('water_consistency');
                if (!waterConsistency) {
                    errors.water_consistency = 'Water consistency is required';
                }
                break;
            }
            case 'feedingEnvironmentalMonitoring': {
                const temp = parseFloat(formData.get('temperature'));
                if (isNaN(temp)) errors.temperature = 'Temperature is required';
                const humidity = parseFloat(formData.get('humidity'));
                if (isNaN(humidity)) errors.humidity = 'Humidity is required';
                break;
            }
            case 'substratePreparation': {
                const moistureConsistency = formData.get('moistureConsistency');
                if (!moistureConsistency) {
                    errors.moistureConsistency = 'Moisture consistency is required';
                }
                const inputRows = form.querySelectorAll('.substrate-input-row');
                inputRows.forEach(row => {
                    const lotSelect = row.querySelector('.substrate-waste-lot');
                    const quantityInput = row.querySelector('.substrate-quantity-used');
                    const quantity = Number(quantityInput.value);
                    const maximum = Number(quantityInput.max);
                    if (!lotSelect.value) {
                        errors.wasteLotId = 'Select an available Waste Lot';
                    }
                    if (!Number.isFinite(quantity) || quantity <= 0) {
                        errors.quantityUsed = 'Enter a quantity greater than zero';
                    } else if (maximum && quantity > maximum) {
                        errors.quantityUsed = 'Quantity exceeds the available amount in this lot';
                    }
                });
                break;
            }
            case 'batchInfo': {
                const totalEggs = parseFloat(formData.get('total_eggs_grams'));
                if (!isNaN(totalEggs) && totalEggs <= 0) {
                    errors.total_eggs_grams = 'Total eggs must be greater than 0';
                }
                break;
            }
            case 'feedingRecords': {
                const feedPer5g = parseFloat(formData.get('feed_per_5g_eggs_grams'));
                if (!isNaN(feedPer5g) && feedPer5g <= 0) {
                    errors.feed_per_5g_eggs_grams = 'Feed per 5g eggs must be greater than 0';
                }
                const totalFeed = parseFloat(formData.get('total_feed_used_grams'));
                if (!isNaN(totalFeed) && totalFeed <= 0) {
                    errors.total_feed_used_grams = 'Total feed used must be greater than 0';
                }
                break;
            }
            case 'hatcheryEnvironmentalMonitoring': {
                const hTemp = parseFloat(formData.get('temperature_c'));
                if (!isNaN(hTemp) && (hTemp < -50 || hTemp > 100)) {
                    errors.temperature_c = 'Temperature must be between -50 and 100';
                }
                const hHumidity = parseFloat(formData.get('humidity_percent'));
                if (!isNaN(hHumidity) && (hHumidity < 0 || hHumidity > 100)) {
                    errors.humidity_percent = 'Humidity must be between 0 and 100';
                }
                break;
            }
            case 'pupaeTransition': {
                const loveCageVal = formData.get('love_cage_id');
                if (!loveCageVal || !loveCageVal.trim()) {
                    errors.love_cage_id = 'Please select a love cage range';
                    const errEl = document.getElementById('loveCageError');
                    if (errEl) { errEl.style.display = 'block'; errEl.textContent = 'Please select a love cage range'; }
                }
                break;
            }
            case 'cageMonitoring': {
                const cageIdVal = formData.get('cageId');
                if (!cageIdVal || !cageIdVal.trim()) {
                    errors.cageId = 'Please select a cage ID range';
                    const errEl = document.getElementById('cageMonitorError');
                    if (errEl) { errEl.style.display = 'block'; errEl.textContent = 'Please select a cage ID range'; }
                }
                break;
            }
            case 'eggCollection': {
                const eggCageVal = formData.get('cageId');
                if (!eggCageVal || !eggCageVal.trim()) {
                    errors.cageId = 'Please select a cage ID range';
                    const errEl = document.getElementById('eggCageError');
                    if (errEl) { errEl.style.display = 'block'; errEl.textContent = 'Please select a cage ID range'; }
                }
                break;
            }
            case 'baitPreparation': {
                const barrelVal = formData.get('barrelId');
                if (!barrelVal || !barrelVal.trim()) {
                    errors.barrelId = 'Please select a barrel ID range';
                    const errEl = document.getElementById('barrelError');
                    if (errEl) { errEl.style.display = 'block'; errEl.textContent = 'Please select a barrel ID range'; }
                }
                break;
            }
        }

        return Object.keys(errors).length > 0 ? errors : null;
    }

    // Handle form submission
    async function handleSubmit(form, formType) {
        // Prevent multiple submissions
        if (formSubmissionStates.get(formType)) {
            console.log(`Form ${formType} is already being submitted, ignoring duplicate submission`);
            return;
        }
        
        console.log(`Handling submission for form: ${formType}`);
        
        // Set submission flag
        formSubmissionStates.set(formType, true);
        
        // Disable submit button to prevent multiple clicks
        const submitButton = form.querySelector('button[type="submit"]');
        const originalText = submitButton ? submitButton.innerHTML : '';
        if (submitButton) {
            submitButton.disabled = true;
            submitButton.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Submitting...';
        }
        
        try {
            const errors = await validateForm(form, formType);
            if (errors && reportProblems(form, errors)) return;

            const formData = new FormData(form);
            const data = {};
            
            const numericFields = [
                'feed_quantity_kg', 'larvae_age_days', 'larvae_weight_g', 'consumption_rate_percent',
                'temperature', 'humidity', 'moisture_percentage', 'larvae_collected_kg', 'wet_weight', 'storage_temp',
                'start_weight_kg', 'end_weight_kg', 'consumption_g', 'larvae_biomass', 'quantity_consumed', 'frass_kg', 'substrateIntroducedKg',
                'lighting_hours', 'pupae_weight_added', 'old_pupae_removed', 'number_of_crates', 'eggs_collected'
            ];

            formData.forEach((value, key) => {
                if (numericFields.includes(key)) {
                    data[key] = value ? parseFloat(value) : null;
                } else {
                    data[key] = value;
                }
            });
            // A date and time typed on the form are local farm time.
            const eventDate = data.harvestDate || data.monitoring_date || data.feeding_date || data.healthDate;
            if (productionEventTypes[formType] && eventDate) {
                data.occurred_at = ErpUI.localOccurredAt(eventDate, data.event_time || data.monitoring_time);
            }
            if (formType === 'substratePreparation') {
                data.inputs = Array.from(form.querySelectorAll('.substrate-input-row')).map(row => ({
                    waste_lot_id: row.querySelector('.substrate-waste-lot').value,
                    quantity_used: row.querySelector('.substrate-quantity-used').value
                }));
            }

            const eventType = productionEventTypes[formType];
            const endpoint = eventType
                ? `production/batches/${encodeURIComponent(String(data.production_batch_id || '').trim())}/events/${eventType}`
                : apiEndpoints[formType];
            if (!endpoint) {
                throw new Error(`No API endpoint defined for form type: ${formType}`);
            }

            const apiUrl = `/api/${endpoint}`;

            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(data),
                credentials: 'include'
            });

            const result = await response.json();

            if (!response.ok) {
                throw new Error(result.message || `HTTP error! status: ${response.status}`);
            }
            
            const reference = createdReference(result);
            const saved = result.message || 'Saved';
            showNotification(reference && !saved.includes(reference) ? `${saved} \u00b7 ${reference}` : saved,
                'success', form);
            form.reset();
            if (formType === 'wasteSourcing' || formType === 'substratePreparation') {
                window.refreshSubstrateChainData();
            }
            if (formType === 'batchInfo' || formType === 'feedingRecords') {
                loadHatcheryBatches();
            }
            if (formType === 'harvestYield' && window.refreshDryingData) {
                window.refreshDryingData();
            }
            if (formType === 'harvestYield' && window.refreshFrassLots) {
                window.refreshFrassLots();
            }
            loadRecentEntries(form, formType);
            if (RECENT_KIND[formType]) loadBatchPickers();
        } catch (error) {
            console.error('Error details:', error);
            showNotification(`Not saved: ${error.message}`, 'error', form);
        } finally {
            // Reset submission flag and re-enable button
            formSubmissionStates.set(formType, false);
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.innerHTML = originalText;
            }
        }
    }

    // Add event listeners to forms (only once)
    Object.entries(forms).forEach(([formType, form]) => {
        if (form) {
            
            // Check if event listeners are already added
            if (form.hasAttribute('data-event-listeners-added')) {
                return;
            }
            
            // Mark form as having event listeners
            form.setAttribute('data-event-listeners-added', 'true');
            
            form.querySelectorAll('input, select, textarea').forEach(input => {
                input.addEventListener('input', function() {
                    this.classList.remove('is-invalid');
                });
            });

            form.addEventListener('submit', function(e) {
                e.preventDefault();
                handleSubmit(this, formType);
            });
        } else {
            // It's normal for some forms not to be on every page, so this is a soft warning.
            // console.warn(`Form not found: ${formType}`);
        }
    });

    const addSubstrateInputButton = document.getElementById('addSubstrateInput');
    if (addSubstrateInputButton) {
        addSubstrateInputButton.addEventListener('click', addSubstrateInputRow);
    }
    applyFormDefaults();
    enableLiveChecks();
    loadBatchPickers();
    loadAllRecentEntries();
    addSubstrateInputRow();
    refreshSubstrateChainData();
    loadLocationHierarchy();
    refreshAlertBadge();

    // Sidebar badge: open critical and warning alerts visible to this user.
    async function refreshAlertBadge() {
        const badge = document.getElementById('alertsNavCount');
        if (!badge) return;
        try {
            const response = await fetch('/api/alerts/summary', { credentials: 'include' });
            if (!response.ok) return;
            const counts = (await response.json()).counts || {};
            const urgent = (counts.critical || 0) + (counts.warning || 0);
            badge.textContent = String(urgent);
            badge.hidden = urgent === 0;
            badge.title = `${counts.critical || 0} critical, ${counts.warning || 0} warning`;
        } catch (error) {
            console.error('Could not load alert count:', error);
        }
    }

    // Hatchery feeding: choose one of the farm's hatchery batches (batches
    // recorded before locations are listed too, so running batches go on).
    let hatcheryBatches = [];
    async function loadHatcheryBatches() {
        const select = document.getElementById('hatcheryFeedingBatch');
        if (!select) return;
        try {
            const response = await fetch('/api/farm-operations/hatchery-batch?limit=500', { credentials: 'include' });
            hatcheryBatches = response.ok ? ((await response.json()).data || []) : [];
        } catch (e) {
            console.error('Could not load hatchery batches:', e);
            hatcheryBatches = [];
        }
        renderHatcheryBatches();
    }
    function renderHatcheryBatches() {
        const select = document.getElementById('hatcheryFeedingBatch');
        if (!select) return;
        const farmId = document.getElementById('feedingRecordsFarmId')?.value || '';
        const rows = hatcheryBatches.filter(b => !b.farm_id || String(b.farm_id) === farmId);
        const previous = select.value;
        select.replaceChildren(new Option(
            !farmId ? 'Select a farm first' : rows.length ? 'Select hatchery batch' : 'No hatchery batches on this farm yet', ''));
        rows.forEach(b => select.add(new Option(`${b.batch_number} · ${b.batch_date}`, b.batch_number)));
        if (rows.some(b => b.batch_number === previous)) select.value = previous;
    }
    document.getElementById('feedingRecordsFarmId')?.addEventListener('change', renderHatcheryBatches);
    document.getElementById('feedingRecordsForm')?.addEventListener('reset', () => setTimeout(renderHatcheryBatches, 0));
    loadHatcheryBatches();

    // Handle records filtering
    const recordsFilterForm = document.getElementById('recordsFilterForm');
    if (recordsFilterForm) {
        recordsFilterForm.addEventListener('submit', async function(e) {
            e.preventDefault();
            const date = document.getElementById('recordDate').value;
            const section = document.getElementById('recordSection').value;
            const resultsContainer = document.getElementById('recordsResults');
            
            if (!date) {
                showNotification('Please select a date.', 'error');
                return;
            }

            resultsContainer.innerHTML = `
                <div class="loading">
                    <i class="fas fa-spinner"></i>
                    <p>Loading records...</p>
                </div>`;

            try {
                const response = await fetch(`/api/records?date=${date}&section=${section}`, { credentials: 'include' });

                if (!response.ok) {
                    const errorData = await response.json();
                    throw new Error(errorData.message || 'Failed to fetch records');
                }

                const data = await response.json();
                
                if (data.success) {
                    displayRecords(data.records);
                } else {
                    throw new Error(data.message || 'An unknown error occurred');
                }

            } catch (error) {
                console.error('Error fetching records:', error);
                const problem = document.createElement('p');
                problem.className = 'text-danger';
                problem.textContent = 'Error: ' + error.message;
                resultsContainer.replaceChildren(problem);
                showNotification(error.message, 'error');
            }
        });
    }

    function displayRecords(records) {
        const resultsContainer = document.getElementById('recordsResults');
        resultsContainer.innerHTML = '';

        if (Object.keys(records).length === 0) {
            resultsContainer.innerHTML = `
                <div class="empty-state">
                    <i class="fas fa-inbox"></i>
                    <h4>No Records Found</h4>
                    <p>No records found for the selected date and section.</p>
                </div>`;
            return;
        }

        for (const [tableName, tableRecords] of Object.entries(records)) {
            const tableWrapper = document.createElement('div');
            tableWrapper.className = 'record-table-wrapper';

            const tableTitle = document.createElement('h3');
            tableTitle.textContent = tableName.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
            tableWrapper.appendChild(tableTitle);

            // Create responsive table container
            const tableContainer = document.createElement('div');
            tableContainer.className = 'table-responsive';

            const table = document.createElement('table');
            table.className = 'table table-striped table-bordered';

            // Create table header
            const thead = document.createElement('thead');
            const headerRow = document.createElement('tr');
            const headers = Object.keys(tableRecords[0]);
            
            headers.forEach(headerText => {
                const th = document.createElement('th');
                th.textContent = headerText.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
                headerRow.appendChild(th);
            });
            thead.appendChild(headerRow);
            table.appendChild(thead);

            // Create table body
            const tbody = document.createElement('tbody');
            tableRecords.forEach(record => {
                const row = document.createElement('tr');
                headers.forEach(header => {
                    const cell = document.createElement('td');
                    const value = record[header];
                    
                    // Format the cell content based on data type
                    if (value === null || value === undefined) {
                        cell.textContent = 'N/A';
                        cell.style.color = '#6c757d';
                        cell.style.fontStyle = 'italic';
                    } else {
                        // Format dates
                        if (header.toLowerCase().includes('date') || header.toLowerCase().includes('time')) {
                            cell.className = 'date-cell';
                            if (typeof value === 'string' && value.match(/^\d{4}-\d{2}-\d{2}/)) {
                                const date = new Date(value);
                                cell.textContent = date.toLocaleDateString();
                            } else {
                                cell.textContent = value;
                            }
                        }
                        // Format numbers
                        else if (header.toLowerCase().includes('weight') || 
                                 header.toLowerCase().includes('quantity') || 
                                 header.toLowerCase().includes('amount') ||
                                 header.toLowerCase().includes('temperature') ||
                                 header.toLowerCase().includes('humidity') ||
                                 header.toLowerCase().includes('percentage')) {
                            cell.className = 'number-cell';
                            const numValue = parseFloat(value);
                            if (!isNaN(numValue)) {
                                cell.textContent = numValue.toLocaleString();
                            } else {
                                cell.textContent = value;
                            }
                        }
                        // Format status/boolean values
                        else if (typeof value === 'boolean' || 
                                 (typeof value === 'string' && ['yes', 'no', 'true', 'false'].includes(value.toLowerCase()))) {
                            const statusBadge = document.createElement('span');
                            statusBadge.className = 'status-badge';
                            
                            if (value === true || value === 'yes' || value === 'true') {
                                statusBadge.classList.add('success');
                                statusBadge.textContent = 'Yes';
                            } else if (value === false || value === 'no' || value === 'false') {
                                statusBadge.classList.add('danger');
                                statusBadge.textContent = 'No';
                            } else {
                                statusBadge.classList.add('info');
                                statusBadge.textContent = value;
                            }
                            
                            cell.appendChild(statusBadge);
                        }
                        // Handle long text
                        else if (typeof value === 'string' && value.length > 50) {
                            const truncatedText = document.createElement('span');
                            truncatedText.className = 'text-truncate';
                            truncatedText.title = value; // Show full text on hover
                            truncatedText.textContent = value.length > 100 ? value.substring(0, 100) + '...' : value;
                            cell.appendChild(truncatedText);
                        }
                        // Default formatting
                        else {
                            cell.textContent = value;
                        }
                    }
                    
                    // Add data-label for mobile responsiveness
                    cell.setAttribute('data-label', header.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase()));
                    
                    row.appendChild(cell);
                });
                tbody.appendChild(row);
            });
            table.appendChild(tbody);
            tableContainer.appendChild(table);
            tableWrapper.appendChild(tableContainer);
            resultsContainer.appendChild(tableWrapper);
        }
    }

    // Open the section named in the address (e.g. /dashboard#hatchery from
    // the farmer portal), also when only the #part changes.
    function openLinkedSection() {
        const linkedSection = window.location.hash.slice(1);
        if (linkedSection && document.getElementById(linkedSection)?.classList.contains('section')) {
            const link = document.querySelector(`.nav-link[onclick*="'${linkedSection}'"]`);
            showSection(linkedSection, link);
        }
    }
    openLinkedSection();
    window.addEventListener('hashchange', openLinkedSection);
});

// Drying Process Section
document.addEventListener('DOMContentLoaded', function() {
  var traceForm = document.getElementById('dryingTraceLookupForm');
  var traceResult = document.getElementById('dryingTraceResult');
  var traceMessage = document.getElementById('dryingTraceMessage');
  if (traceForm && traceResult && traceMessage) {
    function escapeTrace(value) {
      return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }
    function numberTrace(value) {
      if (value == null || value === '') return '—';
      var parsed = Number(value);
      return Number.isFinite(parsed) ? parsed.toFixed(3) : escapeTrace(value);
    }
    function renderTrace(record) {
      var inputs = record.inputs || [];
      var outputs = record.outputs || [];
      document.getElementById('dryingTraceSource').innerHTML =
        inputs.length
          ? inputs.map(function(input) {
              return '<div class="trace-line"><strong>' +
                escapeTrace(input.harvest_code || input.harvest_id) +
                '</strong><span>Input quantity: ' +
                numberTrace(input.quantity) + ' ' + escapeTrace(input.unit) +
                '</span></div>';
            }).join('')
          : '<p>No Harvest inputs recorded.</p>';
      document.getElementById('dryingTraceProcess').innerHTML =
        '<div class="trace-line"><strong>Status</strong><span>' +
        escapeTrace(record.status) + '</span></div>' +
        '<div class="trace-line"><strong>Method</strong><span>' +
        escapeTrace(record.drying_method) + '</span></div>' +
        '<div class="trace-line"><strong>Personnel</strong><span>' +
        escapeTrace(record.personnel) + '</span></div>';
      document.getElementById('dryingTraceOutput').innerHTML =
        outputs.length
          ? outputs.map(function(output) {
              return '<div class="trace-line"><strong>Dried quantity: ' +
                numberTrace(output.quantity) + ' ' + escapeTrace(output.unit) +
                '</strong><span>Moisture: ' +
                numberTrace(output.moisture_percent) + '%' +
                ' · Yield: ' + numberTrace(output.yield_percentage) + '%</span></div>';
            }).join('')
          : '<p>No dried output recorded.</p>';
      traceResult.hidden = false;
    }
    traceForm.addEventListener('submit', async function(event) {
      event.preventDefault();
      traceMessage.textContent = 'Loading Drying Batch...';
      traceResult.hidden = true;
      var reference = document.getElementById('dryingTraceBatchRef').value.trim();
      try {
        var response = await fetch('/api/drying/batches/' + encodeURIComponent(reference), {
          credentials: 'include'
        });
        var payload = await response.json();
        if (!response.ok) throw new Error(payload.message || 'Could not load Drying Batch');
        renderTrace(payload.data);
        traceMessage.textContent = '';
      } catch (error) {
        traceMessage.textContent = error.message;
      }
    });
  }

  // Drying records for the forms: batches with their outputs, the quality
  // checks on each output, the decision on each check and the lot released
  // from it; and harvests that still have wet larvae left to dry.
  var dryingState = { batches: [], harvests: [] };
  var NEXT_STAGE = { DRAFT: 'RECEIVED', RECEIVED: 'DRYING', DRYING: 'QC_PENDING', QC_PENDING: 'COMPLETED' };
  var STAGE_LABEL = {
    DRAFT: 'Draft', RECEIVED: 'Received', DRYING: 'Drying', QC_PENDING: 'Waiting for QC', COMPLETED: 'Completed'
  };

  function kgText(value) {
    var n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: 3 }) + ' kg' : '';
  }

  function findDryingBatch(ref) {
    return dryingState.batches.find(function(b) { return b.business_id === ref; });
  }

  function fillDryingSelect(select, items, placeholder, emptyText) {
    var previous = select.value;
    select.replaceChildren(new Option(items.length ? placeholder : emptyText, ''));
    items.forEach(function(item) {
      var option = new Option(item.label, item.value);
      if (item.batch) option.dataset.batch = item.batch;
      select.add(option);
    });
    if (items.some(function(item) { return String(item.value) === previous; })) select.value = previous;
  }

  function renderDryingSelects() {
    document.querySelectorAll('select.drying-batch').forEach(function(select) {
      var statuses = (select.dataset.status || '').split(',');
      fillDryingSelect(select, dryingState.batches
        .filter(function(b) { return statuses.indexOf(b.status) !== -1; })
        .map(function(b) {
          return { value: b.business_id,
                   label: b.business_id + ' · ' + b.batch_code + ' · ' + STAGE_LABEL[b.status] + ' · ' + b.facility_name };
        }), 'Select drying batch', 'No drying batches at this stage');
    });

    // Harvests come from the farm chosen on the start form, or the farm of
    // the drying batch being added to.
    var inputBatch = findDryingBatch((document.getElementById('dryingInputBatch') || {}).value);
    [['dryingHarvest', (document.getElementById('dryingBatchFarmId') || {}).value || '', 'Select a farm first'],
     ['dryingInputHarvest', inputBatch ? String(inputBatch.farm_id) : '', 'Select a drying batch first']
    ].forEach(function(spec) {
      var select = document.getElementById(spec[0]);
      if (!select) return;
      var farmId = spec[1];
      var items = !farmId ? [] : dryingState.harvests
        .filter(function(h) { return String(h.farm_id) === farmId; })
        .map(function(h) {
          return { value: h.id,
                   label: h.harvest_code + ' · ' + h.production_batch + ' · ' + kgText(h.remaining_kg) + ' left' };
        });
      fillDryingSelect(select, items, 'Select harvest',
        farmId ? 'No harvest with larvae left on this farm' : spec[2]);
    });

    var toCheck = [], toRelease = [], undecided = [];
    dryingState.batches.forEach(function(b) {
      b.outputs.forEach(function(o) {
        var label = b.business_id + ' · output ' + o.line_no + ' · ' + kgText(o.quantity);
        var latest = o.checks[o.checks.length - 1];
        var approved = latest && latest.status === 'passed' && latest.decision === 'approved';
        if (!o.product_lot && approved) toRelease.push({ value: o.id, label: label });
        // The server takes quality checks only once a batch waits for QC.
        if (!o.product_lot && !approved && b.status === 'QC_PENDING') {
          toCheck.push({ value: o.id, label: label, batch: b.business_id });
        }
        o.checks.forEach(function(c) {
          if (!c.decision) undecided.push({ value: c.id, label: c.check_code + ' · ' + label + ' · ' + c.status });
        });
      });
    });
    document.querySelectorAll('select.drying-output').forEach(function(select) {
      var release = select.dataset.stage === 'release';
      fillDryingSelect(select, release ? toRelease : toCheck, 'Select output',
        release ? 'No approved output waiting for release' : 'No dried output waiting for QC');
    });
    document.querySelectorAll('select.drying-check').forEach(function(select) {
      fillDryingSelect(select, undecided, 'Select quality check', 'No quality check waiting for a decision');
    });

    var stageButton = document.getElementById('dryingStatusButton');
    var stageBatch = findDryingBatch((document.getElementById('dryingStatusBatch') || {}).value);
    if (stageButton) {
      var next = stageBatch && NEXT_STAGE[stageBatch.status];
      stageButton.lastChild.textContent = next ? ' Move to ' + STAGE_LABEL[next] : ' Move to Next Stage';
    }
  }

  async function loadDryingData() {
    try {
      var responses = await Promise.all([
        fetch('/api/drying/batches', { credentials: 'include' }),
        fetch('/api/drying/available-harvests', { credentials: 'include' })
      ]);
      dryingState.batches = responses[0].ok ? ((await responses[0].json()).data || []) : [];
      dryingState.harvests = responses[1].ok ? ((await responses[1].json()).data || []) : [];
    } catch (err) {
      console.error('Could not load drying records:', err);
    }
    renderDryingSelects();
  }

  ['dryingBatchFarmId', 'dryingInputBatch', 'dryingStatusBatch'].forEach(function(id) {
    var select = document.getElementById(id);
    if (select) select.addEventListener('change', renderDryingSelects);
  });
  // The farm list arrives later and may pick the only farm by itself.
  document.addEventListener('locations-loaded', renderDryingSelects);
  window.refreshDryingData = loadDryingData;
  loadDryingData();

  function harvestInput(data) {
    var input = { harvest_id: data.harvestId, quantity: data.quantityKg, unit: 'kg' };
    if (data.moisturePercent) input.incoming_moisture_percent = data.moisturePercent;
    return input;
  }

  // Each form turns its fields into one request to the scoped drying API.
  var dryingForms = [
    { id: 'dryingBatchForm', request: function(data) {
      return { url: '/api/drying/batches', body: {
        farm_id: data.farmId, site_id: data.siteId, facility_id: data.facilityId,
        batch_code: data.batchCode, drying_date: data.dryingDate, drying_method: data.dryingMethod,
        personnel: data.personnel, inputs: [harvestInput(data)] } };
    } },
    { id: 'dryingInputForm', request: function(data) {
      return { url: '/api/drying/batches/' + encodeURIComponent(data.dryingBatch) + '/inputs',
               body: { inputs: [harvestInput(data)], notes: data.notes } };
    } },
    { id: 'dryingStatusForm', request: function(data) {
      var batch = findDryingBatch(data.dryingBatch);
      return { url: '/api/drying/batches/' + encodeURIComponent(data.dryingBatch) + '/status',
               body: { status: batch && NEXT_STAGE[batch.status], reason: data.reason } };
    } },
    { id: 'dryingOutputForm', request: function(data) {
      return { url: '/api/drying/batches/' + encodeURIComponent(data.dryingBatch) + '/outputs', body: {
        quantity: data.quantityKg, unit: 'kg', moisture_percent: data.moisturePercent || null,
        output_date: data.outputDate, operator: data.operator, notes: data.notes } };
    } },
    { id: 'qualityControlForm', request: function(data, form) {
      var option = form.querySelector('select.drying-output').selectedOptions[0];
      return { url: '/api/drying/outputs/' + encodeURIComponent(data.dryingOutputId) + '/quality-checks', body: {
        drying_batch_id: option ? option.dataset.batch : undefined,
        status: data.checkStatus, inspector: data.qcPersonnel, checked_at: data.qcDate,
        moisture_percent: data.qcMoisturePercent || null,
        parameters: { sand_removal: data.sandRemoval, contaminants_found: data.contaminantsFound || [],
                      color_quality: data.colorQuality, moisture_level: data.moistureLevel },
        notes: data.notes } };
    } },
    { id: 'reviewApprovalForm', request: function(data) {
      return { url: '/api/drying/quality-approvals', body: {
        quality_check_id: data.qualityCheckId, decision: data.approvalStatus,
        approver: data.reviewedBy, rationale: data.comments } };
    } },
    { id: 'productLotReleaseForm', request: function(data) {
      return { url: '/api/product-lots', body: data };
    } }
  ];

  var releaseLocationSelect = document.getElementById('productLotInventoryLocation');
  if (releaseLocationSelect) {
    fetch('/api/inventory/locations', { credentials: 'include' })
      .then(function(response) {
        if (!response.ok) throw new Error('Could not load inventory locations');
        return response.json();
      })
      .then(function(result) {
        var rows = result.data || [];
        releaseLocationSelect.replaceChildren(new Option(
          rows.length ? 'Select inventory location' : 'No inventory locations — ask an administrator', ''
        ));
        rows.forEach(function(row) {
          releaseLocationSelect.add(new Option(
            row.farm_name + ' / ' + row.facility_name + ' — ' + row.name + ' (' + row.location_code + ')',
            row.id
          ));
        });
      })
      .catch(function(error) {
        console.error(error);
        releaseLocationSelect.replaceChildren(new Option('Inventory locations could not be loaded', ''));
      });
  }

  dryingForms.forEach(function(item) {
    var form = document.getElementById(item.id);
    if (!form) return;
    form.addEventListener('submit', async function(e) {
      e.preventDefault();
      if (window.reportFormProblems && window.reportFormProblems(form)) return;
      var formData = new FormData(form);
      var data = {};
      formData.forEach(function(value, key) {
        var input = form.querySelector('[name="' + key + '"]');
        if (input && input.multiple) {
          data[key] = Array.from(formData.getAll(key));
        } else {
          data[key] = value;
        }
      });
      var request = item.request(data, form);
      try {
        var response = await fetch(request.url, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(request.body),
          credentials: 'include'
        });
        var result = await response.json();
        if (response.ok) {
          var reference = createdReference(result);
          var saved = result.message || 'Saved';
          showFormResult(form, reference && saved.indexOf(reference) === -1 ? saved + ' \u00b7 ' + reference : saved,
            'success');
          form.reset();
          loadDryingData();
          if (item.id === 'productLotReleaseForm' && result.data) {
            var createdLink = document.getElementById('productLotCreatedLink');
            if (createdLink) {
              var link = document.createElement('a');
              link.href = '/product-lot?ref=' + encodeURIComponent(result.data.business_id);
              link.textContent = 'View Product Lot ' + result.data.business_id;
              createdLink.textContent = 'Product Lot released. ';
              createdLink.appendChild(link);
              createdLink.hidden = false;
            }
          }
        } else {
          showFormResult(form, 'Not saved: ' + (result.message || result.error || 'the server refused it.'), 'error');
        }
      } catch (err) {
        showFormResult(form, 'Not saved: the server could not be reached.', 'error');
      }
    });
    form.querySelectorAll('input, select, textarea').forEach(function(input) {
      input.addEventListener('input', function() { this.classList.remove('is-invalid'); });
    });
  });
});

// Send Harvest Report Button
document.addEventListener('DOMContentLoaded', function() {
  var sendHarvestReportBtn = document.getElementById('sendHarvestReportBtn');
  if (!sendHarvestReportBtn) return;
  sendHarvestReportBtn.addEventListener('click', async function() {
    sendHarvestReportBtn.disabled = true;
    sendHarvestReportBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Sending...';
    try {
      var resp = await fetch('/api/send-harvest-report', { method: 'POST', credentials: 'include' });
      var result = await resp.json();
      if (result.success) {
        alert('Harvest report sent to admin!');
      } else {
        alert('Failed to send report: ' + (result.error || result.message));
      }
    } catch (e) {
      alert('Error sending report: ' + e);
    } finally {
      sendHarvestReportBtn.disabled = false;
      sendHarvestReportBtn.innerHTML = '<i class="fas fa-envelope"></i> Email Harvest Report to Admin';
    }
  });
});

// Subsection Carousel
(function() {
  var CAROUSEL_SECTIONS = ['waste', 'hatchery', 'feeding', 'drying', 'frass', 'facility'];
  var carousels = {};

  function buildCarousel(sectionId) {
    var section = document.getElementById(sectionId);
    if (!section || carousels[sectionId]) return;

    var subsections = Array.prototype.filter.call(section.children, function(el) {
      return el.classList.contains('subsection');
    });
    if (subsections.length < 2) return;

    var slider = document.createElement('div');
    slider.className = 'subsection-slider';
    var track = document.createElement('div');
    track.className = 'subsection-slider-track';

    var labels = subsections.map(function(sub) {
      var h2 = sub.querySelector('h2');
      return h2 ? h2.textContent.trim() : '';
    });

    subsections.forEach(function(sub) { section.removeChild(sub); track.appendChild(sub); });
    slider.appendChild(track);
    section.appendChild(slider);

    var controls = document.createElement('div');
    controls.className = 'carousel-controls';
    var prevBtn = document.createElement('button');
    prevBtn.type = 'button'; prevBtn.className = 'carousel-arrow'; prevBtn.setAttribute('aria-label', 'Previous subsection'); prevBtn.innerHTML = '<i class="fas fa-chevron-left"></i>';
    var centerEl = document.createElement('div');
    centerEl.className = 'carousel-center';
    var dotsEl = document.createElement('div');
    dotsEl.className = 'carousel-dots';
    var dotEls = labels.map(function(label, i) {
      var dot = document.createElement('button');
      dot.type = 'button'; dot.className = 'carousel-dot' + (i === 0 ? ' active' : ''); dot.setAttribute('aria-label', 'Go to: ' + label); dot.title = label;
      dot.addEventListener('click', function() { goTo(i); });
      dotsEl.appendChild(dot);
      return dot;
    });
    var counterEl = document.createElement('div');
    counterEl.className = 'carousel-slide-counter';
    counterEl.textContent = '1 of ' + subsections.length;
    centerEl.appendChild(dotsEl); centerEl.appendChild(counterEl);
    var nextBtn = document.createElement('button');
    nextBtn.type = 'button'; nextBtn.className = 'carousel-arrow'; nextBtn.setAttribute('aria-label', 'Next subsection'); nextBtn.innerHTML = '<i class="fas fa-chevron-right"></i>';
    controls.appendChild(prevBtn); controls.appendChild(centerEl); controls.appendChild(nextBtn);
    section.appendChild(controls);

    var currentIndex = 0;
    var total = subsections.length;

    function goTo(index) {
      if (index < 0) index = 0;
      if (index >= total) index = total - 1;
      currentIndex = index;
      track.style.transform = 'translateX(-' + (index * 100) + '%)';
      dotEls.forEach(function(dot, i) { dot.classList.toggle('active', i === index); });
      counterEl.textContent = (index + 1) + ' of ' + total;
      prevBtn.disabled = index === 0;
      nextBtn.disabled = index === total - 1;
    }

    prevBtn.addEventListener('click', function() { goTo(currentIndex - 1); });
    nextBtn.addEventListener('click', function() { goTo(currentIndex + 1); });
    goTo(0);
    carousels[sectionId] = { goTo: goTo, getIndex: function() { return currentIndex; } };
  }

  function initAll() { CAROUSEL_SECTIONS.forEach(buildCarousel); }

  document.addEventListener('DOMContentLoaded', initAll);

  document.addEventListener('keydown', function(e) {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    var tag = document.activeElement ? document.activeElement.tagName : '';
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    CAROUSEL_SECTIONS.forEach(function(sectionId) {
      var section = document.getElementById(sectionId);
      if (!section || !section.classList.contains('active')) return;
      var car = carousels[sectionId];
      if (!car) return;
      if (e.key === 'ArrowRight') car.goTo(car.getIndex() + 1);
      if (e.key === 'ArrowLeft') car.goTo(car.getIndex() - 1);
    });
  });
})();

/* ── Cage Range Picker ───────────────────────────────────────────────── */
(function() {
  function CageRangePicker(cfg) {
    var trigger    = document.getElementById(cfg.triggerId);
    var panel      = document.getElementById(cfg.panelId);
    var gridEl     = document.getElementById(cfg.gridId);
    var displayEl  = document.getElementById(cfg.displayId);
    var footerEl   = document.getElementById(cfg.footerId);
    var clearBtn   = document.getElementById(cfg.clearId);
    var hiddenIn   = document.getElementById(cfg.inputId);
    var errorEl    = document.getElementById(cfg.errorId);

    if (!trigger || !panel || !gridEl || !hiddenIn) return;

    var startCage  = null;
    var endCage    = null;
    var hoverCage  = null;
    var cells      = [];

    /* ── build grid (col-headers row + 10 data rows) ── */
    // blank corner
    var corner = document.createElement('div');
    gridEl.appendChild(corner);
    // column headers 1-10
    for (var c = 1; c <= 10; c++) {
      var ch = document.createElement('div');
      ch.className = 'cage-col-header';
      ch.textContent = c;
      gridEl.appendChild(ch);
    }
    // 10 rows of cage cells
    for (var row = 0; row < 10; row++) {
      var rowLabel = document.createElement('div');
      rowLabel.className = 'cage-row-label';
      rowLabel.textContent = (row * 10 + 1) + '–';
      gridEl.appendChild(rowLabel);

      for (var col = 1; col <= 10; col++) {
        var id = row * 10 + col;
        var cell = document.createElement('div');
        cell.className = 'cage-cell';
        cell.textContent = id;
        cell.dataset.cage = id;
        gridEl.appendChild(cell);
        cells.push(cell);
      }
    }

    /* ── helpers ── */
    function rangeOf() {
      if (startCage === null) return null;
      var other = (endCage !== null) ? endCage : (hoverCage !== null ? hoverCage : startCage);
      return { s: Math.min(startCage, other), e: Math.max(startCage, other) };
    }

    function renderCells() {
      var r = rangeOf();
      cells.forEach(function(cell) {
        var n = parseInt(cell.dataset.cage);
        cell.classList.remove('range-start', 'range-end', 'in-range', 'is-selecting');
        if (!r) return;
        if (startCage !== null && endCage === null) cell.classList.add('is-selecting');
        if (n === r.s && n === r.e) { cell.classList.add('range-start', 'range-end'); }
        else if (n === r.s)         { cell.classList.add('range-start'); }
        else if (n === r.e)         { cell.classList.add('range-end'); }
        else if (n > r.s && n < r.e){ cell.classList.add('in-range'); }
      });
    }

    function updateDisplay() {
      if (startCage !== null && endCage !== null) {
        var s = Math.min(startCage, endCage);
        var e = Math.max(startCage, endCage);
        var count = e - s + 1;
        displayEl.textContent = 'Cage ' + s + '  \u2192  Cage ' + e;
        displayEl.classList.add('has-value');
        footerEl.innerHTML = '<span class="cage-range-summary"><i class="fas fa-check-circle" style="color:var(--primary-color)"></i> Cage ' + s + ' \u2013 Cage ' + e + ' &nbsp;&bull;&nbsp; ' + count + ' cage' + (count > 1 ? 's' : '') + '</span>';
        hiddenIn.value = s + '-' + e;
        if (errorEl) errorEl.style.display = 'none';
      } else if (startCage !== null) {
        displayEl.textContent = 'Cage ' + startCage + '  \u2192  pick end…';
        displayEl.classList.add('has-value');
        footerEl.innerHTML = '<span class="cage-range-preview">Now click the last cage in your range</span>';
        hiddenIn.value = '';
      } else {
        displayEl.textContent = cfg.placeholder || 'Select cage range';
        displayEl.classList.remove('has-value');
        footerEl.innerHTML = '';
        hiddenIn.value = '';
      }
    }

    function clearPicker() {
      startCage = endCage = hoverCage = null;
      renderCells();
      updateDisplay();
    }

    /* ── grid events ── */
    gridEl.addEventListener('click', function(e) {
      var cell = e.target.closest('.cage-cell');
      if (!cell) return;
      var n = parseInt(cell.dataset.cage);
      if (startCage === null || endCage !== null) {
        startCage = n; endCage = null; hoverCage = null;
      } else {
        endCage = n; hoverCage = null;
        panel.classList.remove('open');
        trigger.classList.remove('active');
      }
      renderCells();
      updateDisplay();
    });

    gridEl.addEventListener('mouseover', function(e) {
      var cell = e.target.closest('.cage-cell');
      if (!cell || startCage === null || endCage !== null) return;
      hoverCage = parseInt(cell.dataset.cage);
      renderCells();
      var r = rangeOf();
      if (r) footerEl.innerHTML = '<span class="cage-range-preview">Preview: Cage ' + r.s + ' \u2013 Cage ' + r.e + ' (' + (r.e - r.s + 1) + ' cages)</span>';
    });

    gridEl.addEventListener('mouseleave', function() {
      if (startCage !== null && endCage === null) {
        hoverCage = null;
        renderCells();
        footerEl.innerHTML = '<span class="cage-range-preview">Now click the last cage in your range</span>';
      }
    });

    /* ── trigger toggle ── */
    trigger.addEventListener('click', function(e) {
      e.stopPropagation();
      panel.classList.toggle('open');
      trigger.classList.toggle('active');
    });

    /* ── clear button ── */
    if (clearBtn) {
      clearBtn.addEventListener('click', function(e) {
        e.stopPropagation();
        clearPicker();
      });
    }

    /* ── close on outside click ── */
    document.addEventListener('click', function(e) {
      if (!panel.contains(e.target) && !trigger.contains(e.target)) {
        panel.classList.remove('open');
        trigger.classList.remove('active');
      }
    });

    /* ── expose reset for form.reset() ── */
    return { clear: clearPicker };
  }

  /* ── init both pickers on DOMContentLoaded ── */
  document.addEventListener('DOMContentLoaded', function() {
    var lovePicker = CageRangePicker({
      triggerId:  'loveCageTrigger',
      panelId:    'loveCagePanel',
      gridId:     'loveCageGrid',
      displayId:  'loveCageDisplay',
      footerId:   'loveCageFooter',
      clearId:    'loveCageClear',
      inputId:    'loveCageIdValue',
      errorId:    'loveCageError',
      placeholder: 'Select love cage range'
    });

    var cageMonPicker = CageRangePicker({
      triggerId:  'cageMonitorTrigger',
      panelId:    'cageMonitorPanel',
      gridId:     'cageMonitorGrid',
      displayId:  'cageMonitorDisplay',
      footerId:   'cageMonitorFooter',
      clearId:    'cageMonitorClear',
      inputId:    'cageMonitorIdValue',
      errorId:    'cageMonitorError',
      placeholder: 'Select cage ID range'
    });

    var eggCagePicker = CageRangePicker({
      triggerId:  'eggCageTrigger',
      panelId:    'eggCagePanel',
      gridId:     'eggCageGrid',
      displayId:  'eggCageDisplay',
      footerId:   'eggCageFooter',
      clearId:    'eggCageClear',
      inputId:    'eggCageIdValue',
      errorId:    'eggCageError',
      placeholder: 'Select cage ID range'
    });

    var barrelPicker = CageRangePicker({
      triggerId:  'barrelTrigger',
      panelId:    'barrelPanel',
      gridId:     'barrelGrid',
      displayId:  'barrelDisplay',
      footerId:   'barrelFooter',
      clearId:    'barrelClear',
      inputId:    'barrelIdValue',
      errorId:    'barrelError',
      placeholder: 'Select barrel ID range'
    });

    /* reset pickers when their parent form is reset */
    var pupaeForm = document.getElementById('pupaeTransitionForm');
    if (pupaeForm && lovePicker) {
      pupaeForm.addEventListener('reset', function() { lovePicker.clear(); });
    }
    var cageForm = document.getElementById('cageMonitoringForm');
    if (cageForm && cageMonPicker) {
      cageForm.addEventListener('reset', function() { cageMonPicker.clear(); });
    }
    var eggForm = document.getElementById('eggCollectionForm');
    if (eggForm && eggCagePicker) {
      eggForm.addEventListener('reset', function() { eggCagePicker.clear(); });
    }
    var baitForm = document.getElementById('baitPreparationForm');
    if (baitForm && barrelPicker) {
      baitForm.addEventListener('reset', function() { barrelPicker.clear(); });
    }
  });
})();
/* ── end Cage Range Picker ──────────────────────────────────────────── */

// ---- Frass & Fertiliser -----------------------------------------------------------
// Frass lots come from harvests; this section records curing checks, the cured
// weight, the quality check and decision, and the release to a store.
(function() {
  'use strict';
  var STATUS = { CURING: 'Curing', QC_PENDING: 'Waiting for QC', APPROVED: 'Approved', REJECTED: 'Rejected',
                 RELEASED: 'Released' };
  var lots = [];
  var byId = function(id) { return document.getElementById(id); };

  function kg(value) { return value == null ? '—' : Number(value).toLocaleString(undefined, { maximumFractionDigits: 3 }) + ' kg'; }

  function fill(select, items, placeholder, empty) {
    if (!select) return;
    var keep = select.value;
    select.replaceChildren(new Option(items.length ? placeholder : empty, ''));
    items.forEach(function(item) { select.add(new Option(item.label, item.value)); });
    if (keep && items.some(function(item) { return String(item.value) === keep; })) select.value = keep;
    else if (items.length === 1) select.value = items[0].value;
  }

  function lotItem(lot, extra) {
    return { value: lot.business_id, label: lot.business_id + ' · ' + lot.production_batch + ' · ' +
             kg(lot.cured_kg || lot.quantity_kg) + (extra ? ' · ' + extra : '') };
  }

  function renderTable() {
    var box = byId('frassLotsTable');
    if (!box) return;
    if (!lots.length) {
      box.innerHTML = '<p class="help-text">No frass lots yet. Enter the frass separated on the harvest form to start one.</p>';
      return;
    }
    var table = document.createElement('table');
    table.className = 'frass-table';
    table.innerHTML = '<thead><tr><th>Frass lot</th><th>From</th><th>Separated</th><th>Cured</th><th>Status</th><th>Product lot</th></tr></thead>';
    var body = document.createElement('tbody');
    lots.forEach(function(lot) {
      var row = document.createElement('tr');
      [lot.business_id, lot.harvest_code + ' · ' + lot.production_batch, kg(lot.quantity_kg), kg(lot.cured_kg),
       STATUS[lot.status] || lot.status, lot.product_lot || '—'].forEach(function(text, index) {
        var cell = document.createElement('td');
        if (index === 0) {
          var link = document.createElement('a');
          link.href = '/traceability?ref=' + encodeURIComponent(text) + '&type=frass_lot';
          link.textContent = text;
          cell.appendChild(link);
        } else if (index === 5 && lot.product_lot) {
          var lotLink = document.createElement('a');
          lotLink.href = '/product-lot?ref=' + encodeURIComponent(lot.product_lot);
          lotLink.textContent = lot.product_lot;
          cell.appendChild(lotLink);
        } else {
          cell.textContent = text;
        }
        row.appendChild(cell);
      });
      body.appendChild(row);
    });
    table.appendChild(body);
    box.replaceChildren(table);
  }

  async function load() {
    try {
      var response = await fetch('/api/frass/lots', { credentials: 'include' });
      var payload = await response.json();
      lots = response.ok ? (payload.data || []) : [];
    } catch (error) {
      lots = [];
    }
    var curing = lots.filter(function(l) { return l.status === 'CURING'; });
    fill(byId('frassCuringLot'), curing.map(function(l) { return lotItem(l, l.curing_checks + ' check(s)'); }),
      'Select frass lot', 'No frass lot is curing');
    fill(byId('frassCuredLot'), curing.map(function(l) {
      return lotItem(l, Number(l.curing_checks) ? 'curing since ' + String(l.curing_started_at).slice(0, 10) : 'no curing check yet');
    }), 'Select frass lot', 'No frass lot is curing');
    var waiting = lots.filter(function(l) {
      return l.status === 'QC_PENDING' && !(l.latest_check && !l.latest_check.decision) || l.status === 'REJECTED';
    });
    fill(byId('frassQualityLot'), waiting.map(function(l) { return lotItem(l, STATUS[l.status]); }),
      'Select frass lot', 'No frass lot is waiting for a quality check');
    var undecided = lots.filter(function(l) { return l.status === 'QC_PENDING' && l.latest_check && !l.latest_check.decision; });
    fill(byId('frassDecisionCheck'), undecided.map(function(l) {
      return { value: l.latest_check.id, label: l.latest_check.check_code + ' · ' + l.business_id + ' · ' +
               l.latest_check.status + ' · ' + l.latest_check.maturity };
    }), 'Select quality check', 'No quality check is waiting for a decision');
    fill(byId('frassReleaseLot'), lots.filter(function(l) { return l.status === 'APPROVED'; }).map(function(l) { return lotItem(l); }),
      'Select approved frass lot', 'No approved frass lot to release');
    renderTable();
  }

  async function loadStores() {
    var select = byId('frassReleaseLocation');
    if (!select) return;
    try {
      var response = await fetch('/api/inventory/locations', { credentials: 'include' });
      var rows = response.ok ? ((await response.json()).data || []) : [];
      fill(select, rows.map(function(row) {
        return { value: row.id, label: row.farm_name + ' / ' + row.facility_name + ' — ' + row.name + ' (' + row.location_code + ')' };
      }), 'Select store', 'No stores set up — ask an administrator');
    } catch (error) {
      select.replaceChildren(new Option('Stores could not be loaded', ''));
    }
  }

  function bind(formId, build) {
    var form = byId(formId);
    if (!form) return;
    form.addEventListener('submit', async function(event) {
      event.preventDefault();
      if (window.reportFormProblems && window.reportFormProblems(form)) return;
      var button = form.querySelector('[type="submit"]');
      button.disabled = true;
      try {
        var request = build(form);
        var response = await fetch(request.url, {
          method: 'POST', credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(request.body)
        });
        var result = await response.json().catch(function() { return {}; });
        if (!response.ok) throw new Error(result.message || 'The server did not accept it.');
        showFormResult(form, result.message || 'Saved', 'success');
        form.reset();
        await load();
      } catch (error) {
        showFormResult(form, 'Not saved: ' + error.message, 'error');
      } finally {
        button.disabled = false;
      }
    });
  }

  var lotUrl = function(form, tail) {
    return '/api/frass/lots/' + encodeURIComponent(form.elements.frassLot.value) + tail;
  };
  var number = function(value) { return value === '' ? null : value; };

  bind('frassCuringForm', function(form) {
    return { url: lotUrl(form, '/curing-checks'), body: {
      checked_at: ErpUI.localOccurredAt(form.elements.checkDate.value, form.elements.checkTime.value),
      temperature_c: number(form.elements.temperature_c.value),
      moisture_percent: number(form.elements.moisture_percent.value),
      notes: form.elements.notes.value } };
  });
  bind('frassCuredForm', function(form) {
    return { url: lotUrl(form, '/cured'), body: {
      cured_kg: form.elements.cured_kg.value,
      cured_at: ErpUI.localOccurredAt(form.elements.curedDate.value, '') } };
  });
  bind('frassQualityForm', function(form) {
    return { url: lotUrl(form, '/quality-checks'), body: {
      status: form.elements.status.value, maturity: form.elements.maturity.value,
      moisture_percent: number(form.elements.moisture_percent.value),
      contaminants: Array.from(form.elements.contaminants.selectedOptions).map(function(o) { return o.value; }),
      inspector: form.elements.inspector.value, notes: form.elements.notes.value } };
  });
  bind('frassDecisionForm', function(form) {
    return { url: '/api/frass/quality-checks/' + encodeURIComponent(form.elements.check.value) + '/decision', body: {
      decision: form.elements.decision.value, rationale: form.elements.rationale.value } };
  });
  bind('frassReleaseForm', function(form) {
    return { url: lotUrl(form, '/release'), body: {
      inventory_location_id: form.elements.inventory_location_id.value,
      lot_number: form.elements.lot_number.value } };
  });

  // A harvest saved elsewhere on this page may have started a new frass lot.
  window.refreshFrassLots = function(withStores) { load(); if (withStores) loadStores(); };
  function start() {
    if (!byId('frass')) return;
    load();
    loadStores();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
