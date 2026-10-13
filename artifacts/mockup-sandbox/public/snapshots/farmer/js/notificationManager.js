const NotificationManager = (() => {

  const FORM_KEY_MAP = {
    wasteSourcingForm:                  'wasteSourcing',
    storageRecordsForm:                 'storageRecords',
    processingRecordsForm:              'processingRecords',
    wasteEnvironmentalMonitoringForm:   'wasteEnvMonitoring',
    environmentalMonitoringForm:        'larvaeEnvMonitoring',
    substratePreparationForm:           'substratePrep',
    healthInterventionForm:             'healthIntervention',
    harvestYieldForm:                   'harvestYield',
    feedingScheduleForm:                'feedingSchedule',
    batchInformationForm:               'hatcheryBatch',
    feedingRecordsForm:                 'hatcheryFeeding',
    hatcheryEnvironmentalMonitoringForm:'hatcheryEnvMonitoring',
    cleaningForm:                       'hatcheryCleaning',
    problemsSolutionsForm:              'hatcheryProblems',
    cageMonitoringForm:                 'cageMonitoring',
    facilityMaintenanceForm:            'facilityMaintenance',
    pupaeTransitionForm:                'pupaeTransition',
    eggCollectionForm:                  'eggCollection',
    baitPreparationForm:                'baitPreparation',
    dryingBatchForm:                    'dryingBatch',
    dryingInputForm:                    'dryingInput',
    dryingOutputForm:                   'dryingOutput',
    qualityControlForm:                 'dryingQc',
    reviewApprovalForm:                 'dryingReview',
    customerForm:                       'customers',
    salesForm:                          'sales',
    deliveryForm:                       'deliveries',
    feedbackForm:                       'feedback'
  };

  const SECTION_LABELS = {
    wasteSourcing:          'Waste Sourcing',
    storageRecords:         'Storage Records',
    processingRecords:      'Processing Records',
    wasteEnvMonitoring:     'Waste Env. Monitoring',
    larvaeEnvMonitoring:    'Larvae Env. Monitoring',
    substratePrep:          'Substrate Preparation',
    healthIntervention:     'Health & Intervention',
    harvestYield:           'Harvest & Yield',
    feedingSchedule:        'Feeding Schedule',
    hatcheryBatch:          'Hatchery Batch Info',
    hatcheryFeeding:        'Hatchery Feeding Records',
    hatcheryEnvMonitoring:  'Hatchery Env. Monitoring',
    hatcheryCleaning:       'Hatchery Cleaning',
    hatcheryProblems:       'Hatchery Problems & Solutions',
    cageMonitoring:         'Cage Monitoring',
    facilityMaintenance:    'Facility Maintenance',
    pupaeTransition:        'Pupae Transition',
    eggCollection:          'Egg Collection',
    baitPreparation:        'Bait Preparation',
    dryingBatch:            'Drying Batch Information',
    dryingInput:            'Drying Input Records',
    dryingOutput:           'Drying Output Records',
    dryingQc:               'Drying Quality Control',
    dryingReview:           'Drying Review & Approval',
    customers:              'Customer Records',
    sales:                  'Sales Records',
    deliveries:             'Delivery Records',
    feedback:               'Customer Feedback'
  };

  let toastContainer = null;

  function getContainer() {
    if (!toastContainer) {
      toastContainer = document.createElement('div');
      toastContainer.id = 'bsf-toast-container';
      document.body.appendChild(toastContainer);
    }
    return toastContainer;
  }

  function playChime() {
    try {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (!AC) return;
      const ctx = new AC();
      const notes = [
        { freq: 523.25, start: 0.00 },
        { freq: 659.25, start: 0.18 },
        { freq: 783.99, start: 0.34 }
      ];
      notes.forEach(({ freq, start }) => {
        const osc  = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.type = 'sine';
        osc.frequency.setValueAtTime(freq, ctx.currentTime + start);
        gain.gain.setValueAtTime(0, ctx.currentTime + start);
        gain.gain.linearRampToValueAtTime(0.22, ctx.currentTime + start + 0.04);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + start + 0.6);
        osc.start(ctx.currentTime + start);
        osc.stop(ctx.currentTime + start + 0.6);
      });
      setTimeout(() => { try { ctx.close(); } catch (_) {} }, 1500);
    } catch (_) { /* audio unavailable */ }
  }

  function dismiss(toast) {
    toast.classList.add('bsf-toast-out');
    setTimeout(() => { if (toast.parentNode) toast.parentNode.removeChild(toast); }, 380);
  }

  function show(key) {
    const label = SECTION_LABELS[key] || key;
    const c = getContainer();

    const toast = document.createElement('div');
    toast.className = 'bsf-toast';
    toast.innerHTML = `
      <div class="bsf-toast-icon"><i class="fas fa-check-circle"></i></div>
      <div class="bsf-toast-body">
        <div class="bsf-toast-title">Data Recorded Successfully!</div>
        <div class="bsf-toast-msg">${label} — record saved.</div>
      </div>
      <button class="bsf-toast-close" aria-label="Dismiss">
        <i class="fas fa-times"></i>
      </button>
    `;

    toast.querySelector('.bsf-toast-close').addEventListener('click', () => dismiss(toast));
    c.appendChild(toast);
    playChime();

    const timerId = setTimeout(() => dismiss(toast), 5000);
    toast.addEventListener('mouseenter', () => clearTimeout(timerId));
  }

  function hookForms() {
    Object.entries(FORM_KEY_MAP).forEach(([formId, key]) => {
      const form = document.getElementById(formId);
      if (!form) return;

      form.addEventListener('submit', function () {
        const data = DataManager.getFormData(form);
        DataManager.save(key, data);
      });
    });
  }

  function init() {
    hookForms();
    document.addEventListener('bsf:dataChanged', e => show(e.detail.key));
  }

  return { init, show, playChime };
})();

document.addEventListener('DOMContentLoaded', () => NotificationManager.init());
