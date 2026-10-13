// Global utility functions

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

    // API endpoints
    const apiEndpoints = {
        'wasteSourcing': 'waste-sourcing',
        'storageRecords': 'storage-records',
        'processingRecords': 'processing-records',
        // Environmental Monitoring Endpoints
        'wasteEnvironmentalMonitoring': 'waste-monitoring',
        'feedingEnvironmentalMonitoring': 'feeding/environmental-monitoring',
        'batchInfo': 'hatchery/batch',
        'feedingRecords': 'hatchery/feeding',
        'hatcheryMonitoring': 'hatchery/monitoring',
        'hatcheryEnvironmentalMonitoring': 'hatchery/monitoring',
        'hatcheryCleaning': 'hatchery/cleaning',
        'cleaningSanitation': 'hatchery/cleaning',
        'hatcheryProblems': 'hatchery/problems',
        'problemsSolutions': 'hatchery/problems',
        'cageMonitoring': 'facility/cage-monitoring',
        'facilityMaintenance': 'facility/maintenance',
        'pupaeTransition': 'facility/pupae-transition',
        'eggCollection': 'facility/egg-collection',
        'baitPreparation': 'facility/bait-preparation',
        'substratePreparation': 'substrate-preparation',
        'healthIntervention': 'feeding/health-intervention',
        'harvestYield': 'feeding/harvest-yield',
        'feedingSchedule': 'feeding/schedule'
    };

    // Notification function
    function showNotification(message, type = 'success') {
        const notification = document.getElementById('notification');
        notification.textContent = message;
        notification.className = 'alert'; // reset
        notification.classList.add(type === 'success' ? 'alert-success' : 'alert-danger');
        notification.style.display = 'block';
        setTimeout(() => {
            notification.style.display = 'none';
        }, 4000);
    }

    let availableWasteLots = [];

    function selectedSubstrateSite() {
        return (document.getElementById('substrateFarmSite')?.value || '').trim().toLowerCase();
    }

    function refreshWasteLotSelects() {
        const site = selectedSubstrateSite();
        document.querySelectorAll('.substrate-waste-lot').forEach(select => {
            const previousValue = select.value;
            select.replaceChildren(new Option('Select an available Waste Lot', ''));
            const matchingLots = site
                ? availableWasteLots.filter(lot => lot.farm_site.trim().toLowerCase() === site)
                : [];
            matchingLots.forEach(lot => {
                select.add(new Option(
                    `${lot.business_id} — ${lot.source_name} — ${lot.available_quantity} ${lot.unit} available`,
                    lot.id
                ));
            });
            if (!matchingLots.length) {
                select.add(new Option(
                    site ? 'No available lots for this farm/site' : 'Enter the farm/site first',
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
                site.textContent = `Farm/site: ${batch.farm_site} · Total input: ${batch.total_input_weight_kg} kg`;
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
        
        form.querySelectorAll('[required]').forEach(field => {
            if (!field.value.trim()) {
                errors[field.name] = `${field.name.replace(/([A-Z])/g, ' $1').trim()} is required`;
                field.classList.add('is-invalid');
                console.log(`Missing required field: ${field.name}`);
            } else {
                field.classList.remove('is-invalid');
            }
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
            if (errors) {
                Object.entries(errors).forEach(([field, message]) => {
                    const input = form.querySelector(`[name="${field}"]`);
                    if (input) {
                        input.classList.add('is-invalid');
                        const feedback = input.nextElementSibling;
                        if (feedback && feedback.classList.contains('invalid-feedback')) {
                            feedback.textContent = message;
                        }
                    }
                });
                // This is a placeholder for a real alert function
                console.error('Please fix the errors in the form', errors);
                return;
            }

            const formData = new FormData(form);
            const data = {};
            
            const numericFields = [
                'feed_quantity_kg', 'larvae_age_days', 'larvae_weight_g', 'consumption_rate_percent',
                'temperature', 'humidity', 'moisture_percentage', 'larvae_collected_kg', 'wet_weight', 'storage_temp',
                'start_weight', 'end_weight', 'consumption', 'substrateIntroducedKg',
                'lighting_hours', 'pupae_weight_added', 'old_pupae_removed', 'number_of_crates', 'eggs_collected'
            ];

            formData.forEach((value, key) => {
                if (numericFields.includes(key)) {
                    data[key] = value ? parseFloat(value) : null;
                } else {
                    data[key] = value;
                }
            });
            if (formType === 'harvestYield' && data.harvestDate && data.event_time) {
                data.occurred_at = new Date(`${data.harvestDate}T${data.event_time}`).toISOString();
            }
            if (formType === 'substratePreparation') {
                data.inputs = Array.from(form.querySelectorAll('.substrate-input-row')).map(row => ({
                    waste_lot_id: row.querySelector('.substrate-waste-lot').value,
                    quantity_used: row.querySelector('.substrate-quantity-used').value
                }));
            }

            const endpoint = apiEndpoints[formType];
            if (!endpoint) {
                throw new Error(`No API endpoint defined for form type: ${formType}`);
            }

            const apiUrl = `/api/${endpoint}`;
            console.log('Sending data to:', apiUrl);
            console.log('Data:', data);

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
            
            console.log('Response data:', result);
            showNotification(result.message || 'Data submitted successfully!', 'success');
            form.reset();
            if (formType === 'wasteSourcing' || formType === 'substratePreparation') {
                window.refreshSubstrateChainData();
            }
            if (formType === 'feedingRecords') {
                fetchNextHatcheryBatchId();
            }
        } catch (error) {
            console.error('Error details:', error);
            showNotification(`Error: ${error.message}`, 'error');
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
            console.log(`Adding event listeners to form: ${formType}`);
            
            // Check if event listeners are already added
            if (form.hasAttribute('data-event-listeners-added')) {
                console.log(`Event listeners already added to form: ${formType}`);
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
                if(formType === 'feedingEnvironmentalMonitoring') {
                    console.log('Environmental Monitoring form submit event fired');
                }
                e.preventDefault();
                console.log(`Form submitted: ${formType}`);
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
    const substrateSiteInput = document.getElementById('substrateFarmSite');
    if (substrateSiteInput) {
        substrateSiteInput.addEventListener('input', refreshWasteLotSelects);
    }
    addSubstrateInputRow();
    refreshSubstrateChainData();

    // Auto-fetch and populate next Hatchery Batch ID for Feeding Records
    async function fetchNextHatcheryBatchId() {
        const batchIdInput = document.getElementById('batchId');
        if (!batchIdInput) return;
        try {
            const response = await fetch('/api/hatchery/next-batch-id', { credentials: 'include' });
            if (response.ok) {
                const data = await response.json();
                batchIdInput.value = data.next_batch_id || 'HAT-1';
            }
        } catch (e) {
            console.error('Could not fetch next hatchery batch ID:', e);
        }
    }

    fetchNextHatcheryBatchId();

    const refreshBatchIdBtn = document.getElementById('refreshBatchId');
    if (refreshBatchIdBtn) {
        refreshBatchIdBtn.addEventListener('click', function() {
            fetchNextHatcheryBatchId();
        });
    }

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
                resultsContainer.innerHTML = `<p class="text-danger">Error: ${error.message}</p>`;
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

    // --- Customers, Sales, Deliveries, Feedback Section Logic ---
    const customerForm = document.getElementById('customerForm');
    const customerTableBody = document.querySelector('#customerTable tbody');
    const salesForm = document.getElementById('salesForm');
    const salesTableBody = document.querySelector('#salesTable tbody');
    const saleCustomerSelect = document.getElementById('saleCustomer');
    const deliveryForm = document.getElementById('deliveryForm');
    const deliveryTableBody = document.querySelector('#deliveryTable tbody');
    const deliveryCustomerSelect = document.getElementById('deliveryCustomer');
    const feedbackForm = document.getElementById('feedbackForm');
    const feedbackTableBody = document.querySelector('#feedbackTable tbody');
    const feedbackCustomerSelect = document.getElementById('feedbackCustomer');

    let customers = [];
    let sales = [];
    let deliveries = [];
    let feedbacks = [];

    // Fetch customers from backend and update all dropdowns
    async function fetchCustomers() {
      const res = await fetch('/api/customers', { credentials: 'include' });
      customers = await res.json();
      updateCustomerDropdowns();
      renderCustomers();
    }
    function updateCustomerDropdowns() {
      const options = '<option value="">Select customer</option>' + customers.map(c => `<option value="${c.id}">${c.name}</option>`).join('');
      if (saleCustomerSelect) saleCustomerSelect.innerHTML = options;
      if (deliveryCustomerSelect) deliveryCustomerSelect.innerHTML = options;
      if (feedbackCustomerSelect) feedbackCustomerSelect.innerHTML = options;
    }

    // Fetch and render sales
    async function fetchSales() {
      const res = await fetch('/api/sales', { credentials: 'include' });
      sales = await res.json();
      renderSales();
    }
    // Fetch and render deliveries
    async function fetchDeliveries() {
      const res = await fetch('/api/deliveries', { credentials: 'include' });
      deliveries = await res.json();
      renderDeliveries();
    }
    // Fetch and render feedback
    async function fetchFeedback() {
      const res = await fetch('/api/feedback', { credentials: 'include' });
      feedbacks = await res.json();
      renderFeedback();
    }

    // Render functions
    function renderCustomers() {
      if (!customerTableBody) return;
      customerTableBody.innerHTML = '';
      customers.forEach(c => {
        const row = document.createElement('tr');
        row.innerHTML = `<td>${c.name}</td><td>${c.contact || ''}</td><td>${c.email || ''}</td><td>${c.address || ''}</td><td><button class='btn btn-sm btn-warning' onclick='editCustomer(${c.id})'>Edit</button></td>`;
        customerTableBody.appendChild(row);
      });
    }
    function renderSales() {
      if (!salesTableBody) return;
      salesTableBody.innerHTML = '';
      sales.forEach(s => {
        const row = document.createElement('tr');
        row.innerHTML = `<td>${s.date}</td><td>${s.customer_name}</td><td>${s.product || ''}</td><td>${s.quantity || ''}</td><td>${s.amount}</td><td><button class='btn btn-sm btn-warning' onclick='editSale(${s.id})'>Edit</button></td>`;
        salesTableBody.appendChild(row);
      });
    }
    function renderDeliveries() {
      if (!deliveryTableBody) return;
      deliveryTableBody.innerHTML = '';
      deliveries.forEach(d => {
        const row = document.createElement('tr');
        row.innerHTML = `<td>${d.date}</td><td>${d.customer_name}</td><td>${d.product || ''}</td><td>${d.quantity || ''}</td><td>${d.status}</td><td>${d.notes || ''}</td><td><button class='btn btn-sm btn-warning' onclick='editDelivery(${d.id})'>Edit</button></td>`;
        deliveryTableBody.appendChild(row);
      });
    }
    function renderFeedback() {
      if (!feedbackTableBody) return;
      feedbackTableBody.innerHTML = '';
      feedbacks.forEach(f => {
        const row = document.createElement('tr');
        row.innerHTML = `<td>${f.date}</td><td>${f.customer_name}</td><td>${f.feedback}</td><td>${f.rating}</td><td><button class='btn btn-sm btn-warning' onclick='editFeedback(${f.id})'>Edit</button></td>`;
        feedbackTableBody.appendChild(row);
      });
    }

    // Add record handlers
    if (customerForm) {
      // Remove any existing submit event listeners (defensive, in case of hot reloads or multiple DOMContentLoaded)
      customerForm.replaceWith(customerForm.cloneNode(true));
      const newCustomerForm = document.getElementById('customerForm');
      newCustomerForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        const btn = newCustomerForm.querySelector('button[type="submit"]');
        if (btn) btn.disabled = true;
        const data = {
          name: newCustomerForm.name.value.trim(),
          contact: newCustomerForm.contact.value.trim(),
          email: newCustomerForm.email.value.trim(),
          address: newCustomerForm.address.value.trim()
        };
        await fetch('/api/customers', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data), credentials: 'include'});
        newCustomerForm.reset();
        if (btn) btn.disabled = false;
        fetchCustomers();
      }, { once: true });
    }
    if (salesForm) {
      salesForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        const data = {
          date: salesForm.date.value,
          customer_id: salesForm.customer.value, // Use customer_id
          product: salesForm.product.value.trim(),
          quantity: salesForm.quantity.value,
          amount: salesForm.amount.value
        };
        await fetch('/api/sales', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data), credentials: 'include'});
        salesForm.reset();
        fetchSales();
      });
    }
    if (deliveryForm) {
      deliveryForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        const data = {
          date: deliveryForm.date.value,
          customer_id: deliveryForm.customer.value, // Use customer_id
          product: deliveryForm.product.value.trim(),
          quantity: deliveryForm.quantity.value,
          status: deliveryForm.status.value,
          notes: deliveryForm.notes.value.trim()
        };
        await fetch('/api/deliveries', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data), credentials: 'include'});
        deliveryForm.reset();
        fetchDeliveries();
      });
    }
    if (feedbackForm) {
      feedbackForm.addEventListener('submit', async function(e) {
        e.preventDefault();
        const data = {
          date: feedbackForm.date.value,
          customer_id: feedbackForm.customer.value,
          feedback: feedbackForm.feedback.value.trim(),
          rating: feedbackForm.rating.value
        };
        await fetch('/api/feedback', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(data), credentials: 'include'});
        feedbackForm.reset();
        fetchFeedback();
      });
    }

    // Edit handlers (simple prompt-based for now)
    window.editCustomer = async function(id) {
      const c = customers.find(x => x.id === id);
      if (!c) return;
      const name = prompt('Edit Name:', c.name);
      if (name === null) return;
      const contact = prompt('Edit Contact:', c.contact || '');
      if (contact === null) return;
      const email = prompt('Edit Email:', c.email || '');
      if (email === null) return;
      const address = prompt('Edit Address:', c.address || '');
      if (address === null) return;
      await fetch(`/api/customers/${id}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({name, contact, email, address}), credentials: 'include'});
      fetchCustomers();
    };
    window.editSale = async function(id) {
      const s = sales.find(x => x.id === id);
      if (!s) return;
      const date = prompt('Edit Date:', s.date);
      if (date === null) return;
      const customer_id = prompt('Edit Customer ID:', s.customer_id);
      if (customer_id === null) return;
      const product = prompt('Edit Product:', s.product || '');
      if (product === null) return;
      const quantity = prompt('Edit Quantity:', s.quantity || '');
      if (quantity === null) return;
      const amount = prompt('Edit Amount:', s.amount);
      if (amount === null) return;
      await fetch(`/api/sales/${id}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({date, customer_id, product, quantity, amount}), credentials: 'include'});
      fetchSales();
    };
    window.editDelivery = async function(id) {
      const d = deliveries.find(x => x.id === id);
      if (!d) return;
      const date = prompt('Edit Date:', d.date);
      if (date === null) return;
      const customer_id = prompt('Edit Customer ID:', d.customer_id);
      if (customer_id === null) return;
      const product = prompt('Edit Product:', d.product || '');
      if (product === null) return;
      const quantity = prompt('Edit Quantity:', d.quantity || '');
      if (quantity === null) return;
      const status = prompt('Edit Status:', d.status);
      if (status === null) return;
      const notes = prompt('Edit Notes:', d.notes || '');
      if (notes === null) return;
      await fetch(`/api/deliveries/${id}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({date, customer_id, product, quantity, status, notes}), credentials: 'include'});
      fetchDeliveries();
    };
    window.editFeedback = async function(id) {
      const f = feedbacks.find(x => x.id === id);
      if (!f) return;
      const date = prompt('Edit Date:', f.date);
      if (date === null) return;
      const customer_id = prompt('Edit Customer ID:', f.customer_id);
      if (customer_id === null) return;
      const feedback = prompt('Edit Feedback:', f.feedback);
      if (feedback === null) return;
      const rating = prompt('Edit Rating:', f.rating);
      if (rating === null) return;
      await fetch(`/api/feedback/${id}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({date, customer_id, feedback, rating}), credentials: 'include'});
      fetchFeedback();
    };

    // Ensure correct rendering when switching sections
    window.showSection = function(sectionId, element) {
      // Hide all sections
      document.querySelectorAll('.section').forEach(section => {
        section.classList.remove('active');
      });
      // Remove active class from all nav links
      document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.remove('active');
      });
      // Show selected section
      const section = document.getElementById(sectionId);
      if (section) {
        section.classList.add('active');
        // If switching to customers or sales, re-render to ensure up-to-date display
        if (sectionId === 'customers') {
          renderCustomers();
        } else if (sectionId === 'sales') {
          renderCustomers(); // update dropdown
          renderSales();
        }
      }
      // Add active class to clicked nav link
      if (element) {
        element.classList.add('active');
      }
    };

    // Initial load
    fetchCustomers();
    fetchSales();
    fetchDeliveries();
    fetchFeedback();
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

  var dryingForms = [
    { id: 'dryingBatchForm', endpoint: 'drying/batch' },
    { id: 'dryingInputForm', endpoint: 'drying/input' },
    { id: 'dryingOutputForm', endpoint: 'drying/output' },
    { id: 'qualityControlForm', endpoint: 'drying/qc' },
    { id: 'reviewApprovalForm', endpoint: 'drying/review' },
    { id: 'productLotReleaseForm', endpoint: 'product-lots' }
  ];

  var dryingSuccessAlert = document.createElement('div');
  dryingSuccessAlert.className = 'alert alert-success';
  dryingSuccessAlert.style.display = 'none';
  dryingSuccessAlert.innerHTML = '<i class="fas fa-check-circle"></i> <span></span>';
  var dryingErrorAlert = document.createElement('div');
  dryingErrorAlert.className = 'alert alert-danger';
  dryingErrorAlert.style.display = 'none';
  dryingErrorAlert.innerHTML = '<i class="fas fa-exclamation-circle"></i> <span></span>';
  var dryingSection = document.getElementById('drying');
  if (dryingSection) {
    dryingSection.insertBefore(dryingSuccessAlert, dryingSection.children[1]);
    dryingSection.insertBefore(dryingErrorAlert, dryingSection.children[2]);
  }

  function showDryingAlert(type, message) {
    if (type === 'success') {
      dryingSuccessAlert.querySelector('span').textContent = message;
      dryingSuccessAlert.style.display = 'block';
      dryingErrorAlert.style.display = 'none';
    } else {
      dryingErrorAlert.querySelector('span').textContent = message;
      dryingErrorAlert.style.display = 'block';
      dryingSuccessAlert.style.display = 'none';
    }
    setTimeout(function() {
      dryingSuccessAlert.style.display = 'none';
      dryingErrorAlert.style.display = 'none';
    }, 5000);
  }

  dryingForms.forEach(function(item) {
    var form = document.getElementById(item.id);
    if (!form) return;
    form.addEventListener('submit', async function(e) {
      e.preventDefault();
      form.querySelectorAll('.is-invalid').forEach(function(el) { el.classList.remove('is-invalid'); });
      var valid = true;
      form.querySelectorAll('[required]').forEach(function(input) {
        if (!input.value.trim()) { input.classList.add('is-invalid'); valid = false; }
      });
      if (!valid) { showDryingAlert('error', 'Please fill in all required fields.'); return; }
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
      if (item.id === 'dryingOutputForm') {
        var wetPlaced = parseFloat(document.getElementById('wetPlaced') ? document.getElementById('wetPlaced').value : 0) || 0;
        var driedProduced = parseFloat(document.getElementById('driedProduced') ? document.getElementById('driedProduced').value : 0) || 0;
        if (wetPlaced && driedProduced) {
          var ratio = (wetPlaced / driedProduced).toFixed(2);
          var yieldPercent = ((driedProduced / wetPlaced) * 100).toFixed(2);
          if (document.getElementById('actualRatio')) document.getElementById('actualRatio').value = ratio;
          if (document.getElementById('yieldPercentage')) document.getElementById('yieldPercentage').value = yieldPercent;
          data.actualRatio = ratio;
          data.yieldPercentage = yieldPercent;
        }
      }
      var endpointUrl = '/api/' + item.endpoint;
      var requestData = data;
      if (item.id === 'qualityControlForm' && data.dryingOutputId) {
        endpointUrl = '/api/drying/outputs/' + encodeURIComponent(data.dryingOutputId) + '/quality-checks';
        requestData = {
          drying_batch_id: data.batchId,
          status: data.checkStatus,
          inspector: data.qcPersonnel,
          checked_at: data.qcDate,
          moisture_percent: data.qcMoisturePercent || null,
          parameters: {
            sand_removal: data.sandRemoval,
            contaminants_found: data.contaminantsFound || [],
            color_quality: data.colorQuality,
            moisture_level: data.moistureLevel
          },
          notes: data.notes
        };
      } else if (item.id === 'reviewApprovalForm' && data.qualityCheckId) {
        endpointUrl = '/api/drying/quality-approvals';
        requestData = {
          quality_check_id: data.qualityCheckId,
          decision: data.approvalStatus,
          approver: data.reviewedBy,
          rationale: data.comments
        };
      }
      try {
        var response = await fetch(endpointUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestData),
          credentials: 'include'
        });
        var result = await response.json();
        if (response.ok) {
          showDryingAlert('success', result.message || 'Data saved successfully!');
          form.reset();
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
          showDryingAlert('error', result.message || result.error || 'Failed to save data.');
        }
      } catch (err) {
        showDryingAlert('error', 'Network or server error.');
      }
    });
    form.querySelectorAll('input, select, textarea').forEach(function(input) {
      input.addEventListener('input', function() { this.classList.remove('is-invalid'); });
    });
  });
});

// Drying Output Efficiency Analysis
document.addEventListener('DOMContentLoaded', function() {
  var analyzeBtn = document.getElementById('analyzeDryingBtn');
  var resultsDiv = document.getElementById('dryingEfficiencyResults');
  if (!analyzeBtn) return;
  analyzeBtn.addEventListener('click', async function() {
    resultsDiv.innerHTML = '<p>Loading...</p>';
    try {
      var response = await fetch('/api/drying/output/all', { credentials: 'include' });
      var data = await response.json();
      if (!response.ok) throw new Error(data.error || 'Failed to fetch data');
      if (!Array.isArray(data.records) || data.records.length === 0) {
        resultsDiv.innerHTML = '<p>No drying output records found.</p>';
        return;
      }
      var html = '<table class="table"><thead><tr><th>Drying Batch</th><th>Dried Produced (kg)</th><th>Actual Ratio (wet:dry)</th><th>Yield %</th><th>Status</th></tr></thead><tbody>';
      data.records.forEach(function(record) {
        var dried = parseFloat(record.dried_produced_kg || 0);
        var ratioStr = record.actual_ratio || '';
        var yieldPercent = parseFloat(record.yield_percentage || 0);
        var ratioNum = null;
        if (ratioStr && ratioStr !== 'N/A') {
          var parts = ratioStr.split(':');
          if (parts.length === 2) {
            var w = parseFloat(parts[0]), d = parseFloat(parts[1]);
            if (!isNaN(w) && !isNaN(d) && d > 0) ratioNum = w / d;
          }
        }
        var status = '';
        if (ratioNum !== null) {
          status = ratioNum <= 3.0
            ? '<span style="color:green;font-weight:bold;">Efficient</span>'
            : '<span style="color:red;font-weight:bold;">Inefficient</span>';
        } else {
          status = '<span style="color:gray;">Incomplete Data</span>';
        }
        html += '<tr><td>' + (record.drying_batch_business_id || record.business_id || record.batch_id || '') + '</td><td>' + (dried || '') + '</td><td>' + (ratioStr || '—') + '</td><td>' + (yieldPercent ? yieldPercent.toFixed(2) + '%' : '—') + '</td><td>' + status + '</td></tr>';
      });
      html += '</tbody></table>';
      html += '<p><strong>Guideline:</strong> Wet:Dried Ratio ≈ 3:1, Yield ≈ 33%</p>';
      resultsDiv.innerHTML = html;
    } catch (err) {
      resultsDiv.innerHTML = '<p style="color:red;">' + err.message + '</p>';
    }
  });
});

// Full Process Flow Efficiency Analysis
document.addEventListener('DOMContentLoaded', function() {
  var analyzeFullBtn = document.getElementById('analyzeFullProcessBtn');
  var fullResultsDiv = document.getElementById('fullProcessResults');
  var fullProcessChart = document.getElementById('fullProcessChart');
  var chartInstance = null;
  if (!analyzeFullBtn) return;
  analyzeFullBtn.addEventListener('click', async function() {
    fullResultsDiv.innerHTML = '<p>Loading...</p>';
    if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
    try {
      var [wasteRes, harvestRes, dryingInputRes, dryingOutputRes] = await Promise.all([
        fetch('/api/waste-sourcing/all', { credentials: 'include' }),
        fetch('/api/feeding/harvest/all', { credentials: 'include' }),
        fetch('/api/drying/input/all', { credentials: 'include' }),
        fetch('/api/drying/output/all', { credentials: 'include' })
      ]);
      var [wasteData, harvestData, dryingInputData, dryingOutputData] = await Promise.all([
        wasteRes.json(), harvestRes.json(), dryingInputRes.json(), dryingOutputRes.json()
      ]);
      if (!wasteRes.ok || !harvestRes.ok || !dryingInputRes.ok || !dryingOutputRes.ok) {
        throw new Error('Failed to fetch all required data.');
      }
      var batchMap = {};
      (wasteData.records || []).forEach(function(r) {
        var batchId = r.business_id || r.drying_batch_business_id || r.batch_id || r.batchId; if (!batchId) return;
        if (!batchMap[batchId]) batchMap[batchId] = {};
        batchMap[batchId].waste = parseFloat(r.waste_weight || r.wasteWeight || r.quantity || 0);
        batchMap[batchId].wasteDate = r.collection_date || r.collectionDate || r.date || null;
      });
      (harvestData.records || []).forEach(function(r) {
        var batchId = r.business_id || r.tray_batch_id || r.batch_id || r.batchId; if (!batchId) return;
        if (!batchMap[batchId]) batchMap[batchId] = {};
        batchMap[batchId].larvae = parseFloat(r.larvae_collected || r.larvaeCollected || r.larvae_harvested || r.quantity || 0);
        batchMap[batchId].harvestDate = r.harvest_date || r.harvestDate || r.date || null;
      });
      (dryingInputData.records || []).forEach(function(r) {
        var batchId = r.drying_batch_business_id || r.business_id || r.batch_id || r.batchId; if (!batchId) return;
        if (!batchMap[batchId]) batchMap[batchId] = {};
        batchMap[batchId].wet = parseFloat(r.wet_placed_for_drying_kg || r.wetPlaced || r.wet_placed || 0);
        batchMap[batchId].dryingDate = r.created_at || r.dryingDate || r.date || null;
      });
      (dryingOutputData.records || []).forEach(function(r) {
        var batchId = r.drying_batch_business_id || r.business_id || r.batch_id || r.batchId; if (!batchId) return;
        if (!batchMap[batchId]) batchMap[batchId] = {};
        batchMap[batchId].dried = parseFloat(r.dried_produced_kg || r.driedProduced || r.dried_produced || 0);
        batchMap[batchId].outputDate = r.created_at || r.dryingDate || r.date || null;
      });
      var html = '<table class="table"><thead><tr><th>Batch ID</th><th>Waste (kg)</th><th>Larvae (kg)</th><th>Wet (kg)</th><th>Dried (kg)</th><th>Waste→Larvae</th><th>Larvae→Dried</th><th>Waste→Dried</th><th>Status</th></tr></thead><tbody>';
      var batchLabels = [], driedOutputs = [], wasteToLarvaeArr = [], larvaeToDriedArr = [], wasteToDriedArr = [];
      var monthlyHarvest = {};
      Object.entries(batchMap).forEach(function([batchId, vals]) {
        var waste = vals.waste || 0, larvae = vals.larvae || 0, wet = vals.wet || 0, dried = vals.dried || 0;
        var wasteToLarvae = waste && larvae ? (larvae / waste).toFixed(2) : '';
        var larvaeToDried = larvae && dried ? (dried / larvae).toFixed(2) : '';
        var wasteToDried = waste && dried ? (dried / waste).toFixed(2) : '';
        var status = '';
        if (wasteToLarvae && larvaeToDried && wasteToDried) {
          if (wasteToLarvae >= 0.15 && Math.abs(larvaeToDried - 0.33) <= 0.05 && Math.abs(wasteToDried - 0.05) <= 0.02) {
            status = '<span style="color:green;font-weight:bold;">Efficient</span>';
          } else {
            status = '<span style="color:red;font-weight:bold;">Inefficient</span>';
          }
        } else {
          status = '<span style="color:gray;">Incomplete Data</span>';
        }
        html += '<tr><td>' + batchId + '</td><td>' + waste + '</td><td>' + larvae + '</td><td>' + wet + '</td><td>' + dried + '</td><td>' + wasteToLarvae + '</td><td>' + larvaeToDried + '</td><td>' + wasteToDried + '</td><td>' + status + '</td></tr>';
        batchLabels.push(batchId);
        driedOutputs.push(dried);
        wasteToLarvaeArr.push(wasteToLarvae ? parseFloat(wasteToLarvae) : null);
        larvaeToDriedArr.push(larvaeToDried ? parseFloat(larvaeToDried) : null);
        wasteToDriedArr.push(wasteToDried ? parseFloat(wasteToDried) : null);
        var dateStr = vals.outputDate || vals.dryingDate || vals.harvestDate || vals.wasteDate;
        if (dateStr) {
          var month = dateStr.slice(0, 7);
          if (!monthlyHarvest[month]) monthlyHarvest[month] = 0;
          monthlyHarvest[month] += dried;
        }
      });
      html += '</tbody></table>';
      html += '<p><strong>Guidelines:</strong> Waste→Larvae ≥ 0.15, Larvae→Dried ≈ 0.33, Waste→Dried ≈ 0.05</p>';
      fullResultsDiv.innerHTML = html;
      var months = Object.keys(monthlyHarvest).sort();
      var monthlyDried = months.map(function(m) { return monthlyHarvest[m]; });
      chartInstance = new Chart(fullProcessChart, {
        type: 'bar',
        data: {
          labels: batchLabels,
          datasets: [
            { label: 'Dried Output (kg) per Batch', data: driedOutputs, backgroundColor: 'rgba(54,162,235,0.5)', borderColor: 'rgba(54,162,235,1)', borderWidth: 1, yAxisID: 'y' },
            { label: 'Waste→Larvae Ratio', data: wasteToLarvaeArr, type: 'line', borderColor: 'rgba(255,99,132,1)', backgroundColor: 'rgba(255,99,132,0.2)', fill: false, yAxisID: 'y1' },
            { label: 'Larvae→Dried Ratio', data: larvaeToDriedArr, type: 'line', borderColor: 'rgba(255,206,86,1)', backgroundColor: 'rgba(255,206,86,0.2)', fill: false, yAxisID: 'y1' },
            { label: 'Waste→Dried Ratio', data: wasteToDriedArr, type: 'line', borderColor: 'rgba(75,192,192,1)', backgroundColor: 'rgba(75,192,192,0.2)', fill: false, yAxisID: 'y1' }
          ]
        },
        options: {
          responsive: true,
          plugins: { title: { display: true, text: 'Batch Efficiency and Output' }, legend: { position: 'top' } },
          scales: {
            y: { type: 'linear', position: 'left', title: { display: true, text: 'Dried Output (kg)' } },
            y1: { type: 'linear', position: 'right', min: 0, max: 1, title: { display: true, text: 'Conversion Ratios' }, grid: { drawOnChartArea: false } }
          }
        }
      });
      if (months.length > 0) {
        var monthlyCanvas = document.createElement('canvas');
        monthlyCanvas.id = 'monthlyHarvestChart';
        monthlyCanvas.style.maxWidth = '100%';
        fullResultsDiv.appendChild(document.createElement('hr'));
        fullResultsDiv.appendChild(monthlyCanvas);
        new Chart(monthlyCanvas, {
          type: 'line',
          data: { labels: months, datasets: [{ label: 'Monthly Dried Output (kg)', data: monthlyDried, borderColor: 'rgba(54,162,235,1)', backgroundColor: 'rgba(54,162,235,0.2)', fill: true, tension: 0.2 }] },
          options: { responsive: true, plugins: { title: { display: true, text: 'Monthly Harvest Trend' }, legend: { display: false } }, scales: { y: { title: { display: true, text: 'Dried Output (kg)' } } } }
        });
      }
    } catch (err) {
      fullResultsDiv.innerHTML = '<p style="color:red;">' + err.message + '</p>';
    }
  });
});

// Clear Reports Button
document.addEventListener('DOMContentLoaded', function() {
  var clearReportsBtn = document.getElementById('clearReportsBtn');
  if (!clearReportsBtn) return;
  clearReportsBtn.addEventListener('click', function() {
    var resultsDiv = document.getElementById('fullProcessResults');
    if (resultsDiv) resultsDiv.innerHTML = '';
    var chartCanvas = document.getElementById('fullProcessChart');
    if (chartCanvas && chartCanvas.getContext) {
      var ctx = chartCanvas.getContext('2d');
      ctx.clearRect(0, 0, chartCanvas.width, chartCanvas.height);
    }
  });
});

// Harvest Efficiency Analysis
document.addEventListener('DOMContentLoaded', function() {
  var analyzeBtn = document.getElementById('analyzeHarvestEfficiencyBtn');
  var resultsDiv = document.getElementById('efficiencyComparisonTable');
  var chartCanvas = document.getElementById('harvestEfficiencyChart');
  var chartInstance = null;
  if (!analyzeBtn) return;
  analyzeBtn.addEventListener('click', async function() {
    resultsDiv.innerHTML = '<p>Loading...</p>';
    if (chartInstance) { chartInstance.destroy(); chartInstance = null; }
    try {
      var response = await fetch('/api/statistics/harvest-efficiency', { credentials: 'include' });
      if (response.redirected || response.url.includes('/login')) {
        resultsDiv.innerHTML = '<p style="color:orange;"><strong>Session expired.</strong> Please refresh the page and log in again.</p>';
        return;
      }
      if (!response.ok) {
        resultsDiv.innerHTML = '<p style="color:red;">Server error (' + response.status + '). Please try again.</p>';
        return;
      }
      var result;
      try { result = await response.json(); }
      catch (e) {
        resultsDiv.innerHTML = '<p style="color:orange;"><strong>Session expired.</strong> Please refresh the page and log in again.</p>';
        return;
      }
      if (!result.success) throw new Error(result.error || 'Failed to fetch data');
      var data = result.data;
      if (!Array.isArray(data) || data.length === 0) {
        resultsDiv.innerHTML = '<p class="text-muted">No harvest efficiency records found. Add drying input and output records in the <strong>Drying</strong> section first.</p>';
        return;
      }
      var html = '<table class="table table-bordered table-sm"><thead class="table-dark"><tr><th>Batch ID</th><th>Date</th><th>Wet Placed (kg)</th><th>Dried Produced (kg)</th><th>Actual Ratio</th><th>Status</th></tr></thead><tbody>';
      var chartLabels = [], chartData = [];
      data.forEach(function(record) {
        var batchId = record.business_id || record.drying_batch_business_id || record.batch_id || record.batchId || '-';
        var date = record.drying_date || record.dryingDate || '-';
        var wet = parseFloat(record.wet_placed || 0).toFixed(2);
        var dried = parseFloat(record.dried_produced || 0).toFixed(2);
        var ratio = record.actual_ratio != null ? parseFloat(record.actual_ratio).toFixed(4) : 'N/A';
        var isEfficient = record.efficiency_status === 'Efficient';
        var status = isEfficient ? '<span style="color:green;font-weight:bold;">&#10003; Efficient</span>' : '<span style="color:red;font-weight:bold;">&#10007; Inefficient</span>';
        var rowClass = isEfficient ? '' : 'table-danger';
        html += '<tr class="' + rowClass + '"><td>' + batchId + '</td><td>' + date + '</td><td>' + wet + '</td><td>' + dried + '</td><td>' + ratio + '</td><td>' + status + '</td></tr>';
        chartLabels.push('Batch ' + batchId);
        chartData.push(record.actual_ratio != null ? parseFloat(record.actual_ratio) : null);
      });
      html += '</tbody></table>';
      html += '<p class="text-muted small"><strong>Guideline:</strong> Target ratio is 3:1 wet-to-dry. Actual ratio ≤ 3.0 = Efficient.</p>';
      resultsDiv.innerHTML = html;
      var freshCanvas = document.getElementById('harvestEfficiencyChart');
      if (!freshCanvas) return;
      chartInstance = new Chart(freshCanvas, {
        type: 'line',
        data: {
          labels: chartLabels,
          datasets: [
            { label: 'Actual Wet:Dry Ratio', data: chartData, borderColor: 'rgba(54,162,235,1)', backgroundColor: 'rgba(54,162,235,0.2)', fill: true, tension: 0.2, pointRadius: 5 },
            { label: 'Target Ratio (3:1)', data: chartLabels.map(function() { return 3; }), borderColor: 'rgba(255,99,132,1)', borderDash: [5, 5], pointRadius: 0, fill: false }
          ]
        },
        options: {
          responsive: true,
          plugins: { title: { display: true, text: 'Harvest Efficiency (Wet:Dry Ratio per Batch)' }, legend: { position: 'top' } },
          scales: { y: { title: { display: true, text: 'Ratio' }, min: 0 } }
        }
      });
    } catch (err) {
      resultsDiv.innerHTML = '<p style="color:red;">' + err.message + '</p>';
    }
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
  var CAROUSEL_SECTIONS = ['waste', 'hatchery', 'feeding', 'drying', 'facility'];
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