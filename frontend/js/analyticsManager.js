const AnalyticsManager = (() => {

  const chartInstances = {};

  const CHART_COLORS = [
    '#3498db','#2ecc71','#e74c3c','#f39c12','#9b59b6',
    '#1abc9c','#e67e22','#e91e63','#00bcd4','#8bc34a'
  ];

  const BACKEND_URLS = {
    wasteSourcing:          '/api/analytics/waste-sourcing',
    storageRecords:         '/api/analytics/storage-records',
    processingRecords:      '/api/analytics/processing-records',
    wasteEnvMonitoring:     '/api/analytics/waste-env-monitoring',
    hatcheryBatch:          '/api/analytics/hatchery-batches',
    hatcheryFeeding:        '/api/analytics/hatchery-feeding',
    hatcheryEnvMonitoring:  '/api/analytics/hatchery-monitoring',
    larvaeEnvMonitoring:    '/api/analytics/larvae-env-monitoring',
    substratePrep:          '/api/analytics/substrate-preparation',
    healthIntervention:     '/api/analytics/health-intervention',
    harvestYield:           '/api/analytics/harvest-yield',
    feedingSchedule:        '/api/analytics/feeding-schedule',
    cageMonitoring:         '/api/analytics/cage-monitoring',
    facilityMaintenance:    '/api/analytics/facility-maintenance',
    pupaeTransition:        '/api/analytics/pupae-transition',
    eggCollection:          '/api/analytics/egg-collection',
    baitPreparation:        '/api/analytics/bait-preparation',
    dryingBatch:            '/api/analytics/drying-batches',
    dryingInput:            '/api/drying/input/all',
    dryingOutput:           '/api/drying/output/all',
    customers:              '/api/analytics/customers',
    sales:                  '/api/analytics/sales',
    deliveries:             '/api/analytics/deliveries',
    feedback:               '/api/analytics/feedback'
  };

  async function fetchRecords(key) {
    const url = BACKEND_URLS[key];
    if (!url) return [];
    try {
      const res = await fetch(url, { credentials: 'include' });
      if (!res.ok) return [];
      const data = await res.json();
      if (Array.isArray(data)) return data;
      if (data.records && Array.isArray(data.records)) return data.records;
      return [];
    } catch (e) {
      console.error('AnalyticsManager: fetch error for', key, e);
      return [];
    }
  }

  function countBy(records, field) {
    return records.reduce((acc, r) => {
      const val = r[field] || 'Unknown';
      acc[val] = (acc[val] || 0) + 1;
      return acc;
    }, {});
  }

  function avg(records, field) {
    const vals = records.map(r => parseFloat(r[field])).filter(v => !isNaN(v));
    return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : 0;
  }

  function topKey(counts) {
    const entries = Object.entries(counts);
    return entries.length ? entries.sort((a, b) => b[1] - a[1])[0][0] : 'N/A';
  }

  const SUBSECTIONS = {
    wasteSourcing: {
      label: 'Waste Sourcing',
      columns: [
        { field: 'business_id', label: 'Waste Lot' },
        { field: 'collection_date', label: 'Date' },
        { field: 'source_type', label: 'Source Type' },
        { field: 'waste_type', label: 'Waste Type' },
        { field: 'waste_weight', label: 'Weight (kg)' },
        { field: 'segregation_status', label: 'Segregation' },
        { field: 'collection_personnel', label: 'Personnel' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const totalWeight = records.reduce((s, r) => s + (parseFloat(r.waste_weight) || 0), 0);
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-list', color: '#3498db' },
          { label: 'Total Waste (kg)', value: totalWeight.toFixed(1), icon: 'fa-weight', color: '#2ecc71' },
          { label: 'Avg Weight (kg)', value: (totalWeight / records.length).toFixed(1), icon: 'fa-balance-scale', color: '#f39c12' },
          { label: 'Top Source', value: topKey(countBy(records, 'source_type')), icon: 'fa-map-marker-alt', color: '#9b59b6' },
          { label: 'Top Waste Type', value: topKey(countBy(records, 'waste_type')), icon: 'fa-recycle', color: '#e74c3c' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'wsWasteType', title: 'Waste Type Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'waste_type'); return { labels: Object.keys(c), data: Object.values(c) }; } },
          { id: 'wsSourceType', title: 'Source Type Distribution', type: 'bar',
            getData: () => { const c = countBy(records, 'source_type'); return { labels: Object.keys(c), data: Object.values(c), yLabel: 'Count' }; } },
          { id: 'wsWeightTrend', title: 'Waste Weight Over Time', type: 'line',
            getData: () => {
              const s = [...records].sort((a, b) => (a.collection_date || '').localeCompare(b.collection_date || ''));
              return { labels: s.map(r => r.collection_date || ''), data: s.map(r => parseFloat(r.waste_weight) || 0), yLabel: 'kg' };
            } }
        ];
      }
    },

    storageRecords: {
      label: 'Storage Records',
      columns: [
        { field: 'storage_date', label: 'Date' },
        { field: 'storage_method', label: 'Method' },
        { field: 'storage_conditions', label: 'Conditions' },
        { field: 'storage_duration', label: 'Duration (days)' },
        { field: 'planned_utilization', label: 'Utilization' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-list', color: '#3498db' },
          { label: 'Avg Duration (days)', value: avg(records, 'storage_duration').toFixed(1), icon: 'fa-clock', color: '#f39c12' },
          { label: 'Top Method', value: topKey(countBy(records, 'storage_method')), icon: 'fa-box', color: '#2ecc71' },
          { label: 'Top Condition', value: topKey(countBy(records, 'storage_conditions')), icon: 'fa-thermometer-half', color: '#e74c3c' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'srMethod', title: 'Storage Method Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'storage_method'); return { labels: Object.keys(c), data: Object.values(c) }; } },
          { id: 'srCondition', title: 'Storage Conditions', type: 'doughnut',
            getData: () => { const c = countBy(records, 'storage_conditions'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    processingRecords: {
      label: 'Processing Records',
      columns: [
        { field: 'processing_date', label: 'Date' },
        { field: 'processing_type', label: 'Type' },
        { field: 'waste_processed', label: 'Processed (kg)' },
        { field: 'waste_reduction', label: 'Reduction (%)' },
        { field: 'by_products', label: 'By-products' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const totalProcessed = records.reduce((s, r) => s + (parseFloat(r.waste_processed) || 0), 0);
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-list', color: '#3498db' },
          { label: 'Total Processed (kg)', value: totalProcessed.toFixed(1), icon: 'fa-cogs', color: '#2ecc71' },
          { label: 'Avg Reduction (%)', value: avg(records, 'waste_reduction').toFixed(1), icon: 'fa-arrow-down', color: '#f39c12' },
          { label: 'Top Process Type', value: topKey(countBy(records, 'processing_type')), icon: 'fa-tag', color: '#9b59b6' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'prType', title: 'Processing Type Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'processing_type'); return { labels: Object.keys(c), data: Object.values(c) }; } },
          { id: 'prWeight', title: 'Waste Processed Over Time', type: 'bar',
            getData: () => {
              const s = [...records].sort((a, b) => (a.processing_date || '').localeCompare(b.processing_date || ''));
              return { labels: s.map(r => r.processing_date || ''), data: s.map(r => parseFloat(r.waste_processed) || 0), yLabel: 'kg' };
            } }
        ];
      }
    },

    wasteEnvMonitoring: {
      label: 'Waste Env. Monitoring',
      columns: [
        { field: 'monitoring_date', label: 'Date' },
        { field: 'temperature', label: 'Temp (°C)' },
        { field: 'humidity', label: 'Humidity (%)' },
        { field: 'odor_level', label: 'Odor Level' },
        { field: 'pest_presence', label: 'Pest Presence' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-list', color: '#3498db' },
          { label: 'Avg Temp (°C)', value: avg(records, 'temperature').toFixed(1), icon: 'fa-thermometer-half', color: '#e74c3c' },
          { label: 'Avg Humidity (%)', value: avg(records, 'humidity').toFixed(1), icon: 'fa-tint', color: '#3498db' },
          { label: 'Pest Issues', value: records.filter(r => r.pest_presence && r.pest_presence !== 'none').length, icon: 'fa-bug', color: '#f39c12' },
          { label: 'Top Odor Level', value: topKey(countBy(records, 'odor_level')), icon: 'fa-wind', color: '#9b59b6' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'wemOdor', title: 'Odor Level Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'odor_level'); return { labels: Object.keys(c), data: Object.values(c) }; } },
          { id: 'wemPest', title: 'Pest Presence', type: 'doughnut',
            getData: () => { const c = countBy(records, 'pest_presence'); return { labels: Object.keys(c), data: Object.values(c) }; } },
          { id: 'wemTemp', title: 'Temperature Trend', type: 'line',
            getData: () => {
              const s = [...records].sort((a, b) => (a.monitoring_date || '').localeCompare(b.monitoring_date || ''));
              return { labels: s.map(r => r.monitoring_date || ''), data: s.map(r => parseFloat(r.temperature) || 0), yLabel: '°C' };
            } }
        ];
      }
    },

    hatcheryBatch: {
      label: 'Batch Information',
      columns: [
        { field: 'batch_number', label: 'Batch No' },
        { field: 'batch_date', label: 'Batch Date' },
        { field: 'total_eggs_grams', label: 'Eggs (g)' },
        { field: 'supervisor_name', label: 'Supervisor' },
        { field: 'hatch_days', label: 'Hatch Days' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const totalEggs = records.reduce((s, r) => s + (parseFloat(r.total_eggs_grams) || 0), 0);
        return [
          { label: 'Total Batches', value: records.length, icon: 'fa-egg', color: '#3498db' },
          { label: 'Total Eggs (g)', value: totalEggs.toFixed(1), icon: 'fa-weight', color: '#2ecc71' },
          { label: 'Avg Hatch Days', value: avg(records, 'hatch_days').toFixed(1), icon: 'fa-clock', color: '#f39c12' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'hbEggTrend', title: 'Eggs Weight Over Time', type: 'line',
            getData: () => {
              const s = [...records].sort((a, b) => (a.batch_date || '').localeCompare(b.batch_date || ''));
              return { labels: s.map(r => r.batch_date || ''), data: s.map(r => parseFloat(r.total_eggs_grams) || 0), yLabel: 'g' };
            } }
        ];
      }
    },

    hatcheryFeeding: {
      label: 'Hatchery Feeding',
      columns: [
        { field: 'feeding_date', label: 'Date' },
        { field: 'batch_id', label: 'Batch ID' },
        { field: 'feed_type', label: 'Feed Type' },
        { field: 'total_feed_used_grams', label: 'Feed Used (kg)' },
        { field: 'distribution_method', label: 'Method' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const totalFeed = records.reduce((s, r) => s + (parseFloat(r.total_feed_used_grams) || 0), 0);
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-utensils', color: '#3498db' },
          { label: 'Total Feed Used (kg)', value: totalFeed.toFixed(1), icon: 'fa-seedling', color: '#2ecc71' },
          { label: 'Top Feed Type', value: topKey(countBy(records, 'feed_type')), icon: 'fa-leaf', color: '#9b59b6' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'hfType', title: 'Feed Type Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'feed_type'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    hatcheryEnvMonitoring: {
      label: 'Hatchery Env. Monitoring',
      columns: [
        { field: 'monitoring_date', label: 'Date' },
        { field: 'temperature_c', label: 'Temp (°C)' },
        { field: 'humidity_percent', label: 'Humidity (%)' },
        { field: 'adjustments_made', label: 'Adjustments' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-list', color: '#3498db' },
          { label: 'Avg Temp (°C)', value: avg(records, 'temperature_c').toFixed(1), icon: 'fa-thermometer-half', color: '#e74c3c' },
          { label: 'Avg Humidity (%)', value: avg(records, 'humidity_percent').toFixed(1), icon: 'fa-tint', color: '#3498db' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'hemTemp', title: 'Temperature Trend', type: 'line',
            getData: () => {
              const s = [...records].sort((a, b) => (a.monitoring_date || '').localeCompare(b.monitoring_date || ''));
              return { labels: s.map(r => r.monitoring_date || ''), data: s.map(r => parseFloat(r.temperature_c) || 0), yLabel: '°C' };
            } }
        ];
      }
    },

    larvaeEnvMonitoring: {
      label: 'Larval Env. Monitoring',
      columns: [
        { field: 'monitoring_date', label: 'Date' },
        { field: 'tray_facility_id', label: 'Tray/Facility ID' },
        { field: 'temperature', label: 'Temp (°C)' },
        { field: 'humidity', label: 'Humidity (%)' },
        { field: 'ammonia_odor', label: 'Ammonia Odor' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-list', color: '#3498db' },
          { label: 'Avg Temp (°C)', value: avg(records, 'temperature').toFixed(1), icon: 'fa-thermometer-half', color: '#e74c3c' },
          { label: 'Avg Humidity (%)', value: avg(records, 'humidity').toFixed(1), icon: 'fa-tint', color: '#3498db' },
          { label: 'Ammonia Detected', value: records.filter(r => r.ammonia_odor === 'yes').length, icon: 'fa-exclamation-triangle', color: '#f39c12' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'lemTemp', title: 'Temperature Over Time', type: 'line',
            getData: () => {
              const s = [...records].sort((a, b) => (a.monitoring_date || '').localeCompare(b.monitoring_date || ''));
              return { labels: s.map(r => r.monitoring_date || ''), data: s.map(r => parseFloat(r.temperature) || 0), yLabel: '°C' };
            } },
          { id: 'lemAmmonia', title: 'Ammonia Odor Occurrence', type: 'doughnut',
            getData: () => { const c = countBy(records, 'ammonia_odor'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    substratePrep: {
      label: 'Substrate Preparation',
      columns: [
        { field: 'business_id', label: 'Substrate Batch' },
        { field: 'batch_no', label: 'Batch No' },
        { field: 'prep_date', label: 'Prep Date' },
        { field: 'organic_waste_source', label: 'Waste Source' },
        { field: 'moisture_percentage', label: 'Moisture (%)' },
        { field: 'waste_particle_size', label: 'Particle Size' },
        { field: 'foreign_matter', label: 'Foreign Matter' },
        { field: 'handler_operator', label: 'Handler' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-list', color: '#3498db' },
          { label: 'Avg Moisture (%)', value: avg(records, 'moisture_percentage').toFixed(1), icon: 'fa-water', color: '#3498db' },
          { label: 'Top Particle Size', value: topKey(countBy(records, 'waste_particle_size')), icon: 'fa-cubes', color: '#f39c12' },
          { label: 'Foreign Matter Incidents', value: records.filter(r => r.foreign_matter === 'yes').length, icon: 'fa-exclamation-circle', color: '#e74c3c' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'spSize', title: 'Particle Size Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'waste_particle_size'); return { labels: Object.keys(c), data: Object.values(c) }; } },
          { id: 'spMoisture', title: 'Moisture % Trend', type: 'line',
            getData: () => {
              const s = [...records].sort((a, b) => (a.prep_date || '').localeCompare(b.prep_date || ''));
              return { labels: s.map(r => r.prep_date || ''), data: s.map(r => parseFloat(r.moisture_percentage) || 0), yLabel: '%' };
            } }
        ];
      }
    },

    healthIntervention: {
      label: 'Health & Intervention',
      columns: [
        { field: 'health_date', label: 'Date' },
        { field: 'tray_batch_id', label: 'Tray/Batch ID' },
        { field: 'observed_issue', label: 'Issue' },
        { field: 'severity', label: 'Severity' },
        { field: 'resolved', label: 'Resolved' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        return [
          { label: 'Total Incidents', value: records.length, icon: 'fa-heartbeat', color: '#e74c3c' },
          { label: 'Resolved', value: records.filter(r => r.resolved === 'yes').length, icon: 'fa-check-circle', color: '#2ecc71' },
          { label: 'High Severity', value: records.filter(r => r.severity === 'high').length, icon: 'fa-exclamation-triangle', color: '#e74c3c' },
          { label: 'Top Severity', value: topKey(countBy(records, 'severity')), icon: 'fa-chart-bar', color: '#f39c12' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'hiSeverity', title: 'Severity Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'severity'); return { labels: Object.keys(c), data: Object.values(c) }; } },
          { id: 'hiResolved', title: 'Resolution Status', type: 'doughnut',
            getData: () => { const c = countBy(records, 'resolved'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    harvestYield: {
      label: 'Harvest & Yield',
      columns: [
        { field: 'business_id', label: 'Harvest' },
        { field: 'harvest_date', label: 'Date' },
        { field: 'tray_batch_id', label: 'Batch ID' },
        { field: 'instar_stage', label: 'Instar Stage' },
        { field: 'larvae_collected', label: 'Collected (kg)' },
        { field: 'processing_method', label: 'Method' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const total = records.reduce((s, r) => s + (parseFloat(r.larvae_collected) || 0), 0);
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-list', color: '#3498db' },
          { label: 'Total Harvested (kg)', value: total.toFixed(1), icon: 'fa-leaf', color: '#2ecc71' },
          { label: 'Avg per Harvest (kg)', value: (total / records.length).toFixed(1), icon: 'fa-balance-scale', color: '#f39c12' },
          { label: 'Top Method', value: topKey(countBy(records, 'processing_method')), icon: 'fa-cog', color: '#9b59b6' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'hyTrend', title: 'Harvest Yield Over Time', type: 'bar',
            getData: () => {
              const s = [...records].sort((a, b) => (a.harvest_date || '').localeCompare(b.harvest_date || ''));
              return { labels: s.map(r => r.harvest_date || ''), data: s.map(r => parseFloat(r.larvae_collected) || 0), yLabel: 'kg' };
            } },
          { id: 'hyMethod', title: 'Processing Method Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'processing_method'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    feedingSchedule: {
      label: 'Feeding Schedule',
      columns: [
        { field: 'feeding_date', label: 'Date' },
        { field: 'tray_batch_id', label: 'Batch ID' },
        { field: 'larvae_age_days', label: 'Age (days)' },
        { field: 'feed_type', label: 'Feed Type' },
        { field: 'feed_quantity', label: 'Feed (kg)' },
        { field: 'consumption', label: 'Consumption' },
        { field: 'operator', label: 'Operator' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const totalFeed = records.reduce((s, r) => s + (parseFloat(r.feed_quantity) || 0), 0);
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-list', color: '#3498db' },
          { label: 'Total Feed (kg)', value: totalFeed.toFixed(1), icon: 'fa-utensils', color: '#2ecc71' },
          { label: 'Avg Larvae Age (days)', value: avg(records, 'larvae_age_days').toFixed(1), icon: 'fa-clock', color: '#f39c12' },
          { label: 'Top Feed Type', value: topKey(countBy(records, 'feed_type')), icon: 'fa-seedling', color: '#9b59b6' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'fsFeed', title: 'Feed Quantity Over Time', type: 'line',
            getData: () => {
              const s = [...records].sort((a, b) => (a.feeding_date || '').localeCompare(b.feeding_date || ''));
              return { labels: s.map(r => r.feeding_date || ''), data: s.map(r => parseFloat(r.feed_quantity) || 0), yLabel: 'kg' };
            } },
          { id: 'fsFeedType', title: 'Feed Type Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'feed_type'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    cageMonitoring: {
      label: 'Cage Monitoring',
      columns: [
        { field: 'monitoring_date', label: 'Date' },
        { field: 'cage_id', label: 'Cage ID' },
        { field: 'temperature', label: 'Temp (°C)' },
        { field: 'humidity', label: 'Humidity (%)' },
        { field: 'lighting_hours', label: 'Lighting' },
        { field: 'ventilation_ok', label: 'Ventilation' },
        { field: 'cage_cleaned', label: 'Cleaned?' },
        { field: 'cage_damage', label: 'Damage' },
        { field: 'cages_damaged_list', label: 'Cages Damaged' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-list', color: '#3498db' },
          { label: 'Avg Temp (°C)', value: avg(records, 'temperature').toFixed(1), icon: 'fa-thermometer-half', color: '#e74c3c' },
          { label: 'Avg Humidity (%)', value: avg(records, 'humidity').toFixed(1), icon: 'fa-tint', color: '#3498db' },
          { label: 'Bad Lighting Events', value: records.filter(r => r.lighting_hours === 'bad').length, icon: 'fa-lightbulb', color: '#f39c12' },
          { label: 'Damage Incidents', value: records.filter(r => r.cage_damage && r.cage_damage !== 'no').length, icon: 'fa-exclamation-circle', color: '#e74c3c' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'cmTempHumidity', title: 'Temperature & Humidity Trend', type: 'line',
            getData: () => {
              const s = [...records].sort((a, b) => (a.monitoring_date || '').localeCompare(b.monitoring_date || ''));
              return {
                labels: s.map(r => r.monitoring_date || ''),
                datasets: [
                  { label: 'Temperature (°C)', data: s.map(r => parseFloat(r.temperature) || 0), borderColor: '#e74c3c', fill: false },
                  { label: 'Humidity (%)', data: s.map(r => parseFloat(r.humidity) || 0), borderColor: '#3498db', fill: false }
                ]
              };
            } },
          { id: 'cmLighting', title: 'Lighting Status Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'lighting_hours'); return { labels: Object.keys(c), data: Object.values(c) }; } },
          { id: 'cmDamage', title: 'Cage Damage Status', type: 'pie',
            getData: () => { const c = countBy(records, 'cage_damage'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    facilityMaintenance: {
      label: 'Facility Maintenance',
      columns: [
        { field: 'maintenance_date', label: 'Date' },
        { field: 'moat_check', label: 'Moat Status' },
        { field: 'ants_present', label: 'Ants' },
        { field: 'rodents_present', label: 'Rodents' },
        { field: 'bird_net_ok', label: 'Bird Net' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-tools', color: '#3498db' },
          { label: 'Ant Incidents', value: records.filter(r => r.ants_present && r.ants_present !== 'no').length, icon: 'fa-bug', color: '#e74c3c' },
          { label: 'Rodent Sightings', value: records.filter(r => r.rodents_present === 'yes').length, icon: 'fa-exclamation-triangle', color: '#f39c12' },
          { label: 'Net Damage Events', value: records.filter(r => r.bird_net_ok === 'damaged').length, icon: 'fa-times-circle', color: '#9b59b6' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'fmMoat', title: 'Moat Status Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'moat_check'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    pupaeTransition: {
      label: 'Pupae Transition',
      columns: [
        { field: 'transition_date', label: 'Date' },
        { field: 'love_cage_id', label: 'Cage ID' },
        { field: 'pupae_weight_added', label: 'Added (kg)' },
        { field: 'old_pupae_removed', label: 'Removed (kg)' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const totalAdded = records.reduce((s, r) => s + (parseFloat(r.pupae_weight_added) || 0), 0);
        const totalRemoved = records.reduce((s, r) => s + (parseFloat(r.old_pupae_removed) || 0), 0);
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-exchange-alt', color: '#3498db' },
          { label: 'Total Added (kg)', value: totalAdded.toFixed(1), icon: 'fa-arrow-up', color: '#2ecc71' },
          { label: 'Total Removed (kg)', value: totalRemoved.toFixed(1), icon: 'fa-arrow-down', color: '#e74c3c' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'ptWeight', title: 'Pupae Weight Added vs Removed', type: 'bar',
            getData: () => {
              const s = [...records].sort((a, b) => (a.transition_date || '').localeCompare(b.transition_date || ''));
              return {
                labels: s.map(r => r.transition_date || ''),
                datasets: [
                  { label: 'Added (kg)', data: s.map(r => parseFloat(r.pupae_weight_added) || 0), backgroundColor: 'rgba(46,204,113,0.7)' },
                  { label: 'Removed (kg)', data: s.map(r => parseFloat(r.old_pupae_removed) || 0), backgroundColor: 'rgba(231,76,60,0.7)' }
                ]
              };
            } }
        ];
      }
    },

    eggCollection: {
      label: 'Egg Collection',
      columns: [
        { field: 'collection_date', label: 'Date' },
        { field: 'cage_id', label: 'Cage ID' },
        { field: 'eggs_collected', label: 'Eggs (g)' },
        { field: 'eggs_intact', label: 'Condition' },
        { field: 'collector_name', label: 'Collector' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const total = records.reduce((s, r) => s + (parseFloat(r.eggs_collected) || 0), 0);
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-egg', color: '#3498db' },
          { label: 'Total Eggs (g)', value: total.toFixed(1), icon: 'fa-weight', color: '#2ecc71' },
          { label: 'Avg per Collection (g)', value: (total / records.length).toFixed(1), icon: 'fa-balance-scale', color: '#f39c12' },
          { label: 'Damage Incidents', value: records.filter(r => r.eggs_intact && r.eggs_intact !== 'yes').length, icon: 'fa-exclamation-circle', color: '#e74c3c' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'ecTrend', title: 'Egg Collection Trend', type: 'line',
            getData: () => {
              const s = [...records].sort((a, b) => (a.collection_date || '').localeCompare(b.collection_date || ''));
              return { labels: s.map(r => r.collection_date || ''), data: s.map(r => parseFloat(r.eggs_collected) || 0), yLabel: 'g' };
            } },
          { id: 'ecIntact', title: 'Egg Condition', type: 'pie',
            getData: () => { const c = countBy(records, 'eggs_intact'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    baitPreparation: {
      label: 'Bait Preparation',
      columns: [
        { field: 'barrel_id', label: 'Barrel ID' },
        { field: 'bait_type', label: 'Bait Type' },
        { field: 'start_date', label: 'Start Date' },
        { field: 'ready_date', label: 'Ready Date' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-flask', color: '#3498db' },
          { label: 'Top Bait Type', value: topKey(countBy(records, 'bait_type')), icon: 'fa-vial', color: '#9b59b6' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'bpType', title: 'Bait Type Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'bait_type'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    dryingBatch: {
      label: 'Drying Batch',
      columns: [
        { field: 'business_id', label: 'Drying Batch' },
        { field: 'batch_id', label: 'Batch ID' },
        { field: 'drying_date', label: 'Date' },
        { field: 'drying_method', label: 'Method' },
        { field: 'personnel', label: 'Personnel' },
        { field: 'status', label: 'Status' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        return [
          { label: 'Total Batches', value: records.length, icon: 'fa-wind', color: '#3498db' },
          { label: 'Completed', value: records.filter(r => r.status === 'completed').length, icon: 'fa-check-circle', color: '#2ecc71' },
          { label: 'Top Status', value: topKey(countBy(records, 'status')), icon: 'fa-info-circle', color: '#f39c12' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'dbStatus', title: 'Batch Status Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'status'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    dryingInput: {
      label: 'Drying Input',
      columns: [
        { field: 'drying_batch_business_id', label: 'Drying Batch' },
        { field: 'batch_id', label: 'Batch ID' },
        { field: 'wet_harvested_kg', label: 'Wet Harvested (kg)' },
        { field: 'wet_placed_for_drying_kg', label: 'Wet Placed (kg)' },
        { field: 'sand_used_kg', label: 'Sand Used (kg)' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const totalWet = records.reduce((s, r) => s + (parseFloat(r.wet_harvested_kg) || 0), 0);
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-box-open', color: '#3498db' },
          { label: 'Total Wet Harvested (kg)', value: totalWet.toFixed(1), icon: 'fa-weight', color: '#2ecc71' },
          { label: 'Total Sand Used (kg)', value: records.reduce((s, r) => s + (parseFloat(r.sand_used_kg) || 0), 0).toFixed(1), icon: 'fa-mountain', color: '#f39c12' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'diWet', title: 'Wet Harvested per Batch', type: 'bar',
            getData: () => ({
              labels: records.map((r, i) => r.batch_id || `Batch ${i + 1}`),
              data: records.map(r => parseFloat(r.wet_harvested_kg) || 0),
              yLabel: 'kg'
            }) }
        ];
      }
    },

    dryingOutput: {
      label: 'Drying Output',
      columns: [
        { field: 'drying_batch_business_id', label: 'Drying Batch' },
        { field: 'batch_id', label: 'Batch ID' },
        { field: 'dried_produced_kg', label: 'Dried (kg)' },
        { field: 'actual_ratio', label: 'Actual Ratio' },
        { field: 'yield_percentage', label: 'Yield (%)' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const totalDried = records.reduce((s, r) => s + (parseFloat(r.dried_produced_kg) || 0), 0);
        return [
          { label: 'Total Records', value: records.length, icon: 'fa-box', color: '#3498db' },
          { label: 'Total Dried (kg)', value: totalDried.toFixed(1), icon: 'fa-weight', color: '#2ecc71' },
          { label: 'Avg Yield (%)', value: avg(records, 'yield_percentage').toFixed(1), icon: 'fa-chart-line', color: '#f39c12' },
          { label: 'Efficient Batches', value: records.filter(r => {
              if (!r.actual_ratio || r.actual_ratio === 'N/A') return false;
              const parts = String(r.actual_ratio).split(':');
              if (parts.length === 2) { const w = parseFloat(parts[0]), d = parseFloat(parts[1]); return !isNaN(w) && !isNaN(d) && d > 0 && (w / d) <= 3.0; }
              return false;
            }).length, icon: 'fa-check-circle', color: '#2ecc71' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'doYield', title: 'Dried Output per Batch', type: 'bar',
            getData: () => ({
              labels: records.map((r, i) => r.batch_id || `Batch ${i + 1}`),
              data: records.map(r => parseFloat(r.dried_produced_kg) || 0),
              yLabel: 'kg'
            }) }
        ];
      }
    },

    customers: {
      label: 'Customers',
      columns: [
        { field: 'name', label: 'Name' },
        { field: 'contact', label: 'Contact' },
        { field: 'email', label: 'Email' },
        { field: 'address', label: 'Address' }
      ],
      getAnalytics(records) {
        return [
          { label: 'Total Customers', value: records.length, icon: 'fa-users', color: '#3498db' }
        ];
      },
      getCharts() { return []; }
    },

    sales: {
      label: 'Sales Records',
      columns: [
        { field: 'date', label: 'Date' },
        { field: 'customer_name', label: 'Customer' },
        { field: 'product', label: 'Product' },
        { field: 'quantity', label: 'Quantity' },
        { field: 'amount', label: 'Amount' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const totalRevenue = records.reduce((s, r) => s + (parseFloat(r.amount) || 0), 0);
        return [
          { label: 'Total Sales', value: records.length, icon: 'fa-cash-register', color: '#3498db' },
          { label: 'Total Revenue', value: totalRevenue.toFixed(2), icon: 'fa-money-bill', color: '#2ecc71' },
          { label: 'Top Product', value: topKey(countBy(records, 'product')), icon: 'fa-star', color: '#f39c12' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'salRevenue', title: 'Revenue Over Time', type: 'line',
            getData: () => {
              const s = [...records].sort((a, b) => (a.date || '').localeCompare(b.date || ''));
              return { labels: s.map(r => r.date || ''), data: s.map(r => parseFloat(r.amount) || 0), yLabel: 'Amount' };
            } }
        ];
      }
    },

    deliveries: {
      label: 'Deliveries',
      columns: [
        { field: 'date', label: 'Date' },
        { field: 'customer_name', label: 'Customer' },
        { field: 'product', label: 'Product' },
        { field: 'quantity', label: 'Quantity' },
        { field: 'status', label: 'Status' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        return [
          { label: 'Total Deliveries', value: records.length, icon: 'fa-truck', color: '#3498db' },
          { label: 'Delivered', value: records.filter(r => r.status === 'delivered').length, icon: 'fa-check-circle', color: '#2ecc71' },
          { label: 'Top Status', value: topKey(countBy(records, 'status')), icon: 'fa-info-circle', color: '#f39c12' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'delStatus', title: 'Delivery Status Distribution', type: 'pie',
            getData: () => { const c = countBy(records, 'status'); return { labels: Object.keys(c), data: Object.values(c) }; } }
        ];
      }
    },

    feedback: {
      label: 'Customer Feedback',
      columns: [
        { field: 'date', label: 'Date' },
        { field: 'customer_name', label: 'Customer' },
        { field: 'feedback', label: 'Feedback' },
        { field: 'rating', label: 'Rating' }
      ],
      getAnalytics(records) {
        if (!records.length) return [];
        const ratings = records.map(r => parseFloat(r.rating)).filter(v => !isNaN(v));
        const avgRating = ratings.length ? ratings.reduce((a, b) => a + b, 0) / ratings.length : 0;
        return [
          { label: 'Total Feedback', value: records.length, icon: 'fa-comment-dots', color: '#3498db' },
          { label: 'Avg Rating', value: avgRating.toFixed(1) + ' / 5', icon: 'fa-star', color: '#f39c12' }
        ];
      },
      getCharts(records) {
        return [
          { id: 'fbRating', title: 'Rating Distribution', type: 'bar',
            getData: () => {
              const counts = { '1': 0, '2': 0, '3': 0, '4': 0, '5': 0 };
              records.forEach(r => { if (r.rating && counts[r.rating] !== undefined) counts[r.rating]++; });
              return { labels: Object.keys(counts).map(k => `${k} Star`), data: Object.values(counts), yLabel: 'Count' };
            } }
        ];
      }
    }
  };

  function buildChart(canvasId, config, records) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    if (chartInstances[canvasId]) { chartInstances[canvasId].destroy(); }
    const ctx = canvas.getContext('2d');
    const d = config.getData(records);

    let chartCfg;
    if (d.datasets) {
      chartCfg = {
        type: config.type,
        data: { labels: d.labels, datasets: d.datasets.map(ds => ({ ...ds, tension: 0.3, fill: false })) },
        options: { responsive: true, animation: { duration: 500 }, plugins: { legend: { position: 'top' } } }
      };
    } else {
      chartCfg = {
        type: config.type,
        data: {
          labels: d.labels,
          datasets: [{
            data: d.data,
            backgroundColor: config.type === 'line' ? 'rgba(46,204,113,0.15)' : d.data.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
            borderColor: config.type === 'line' ? '#2ecc71' : d.data.map((_, i) => CHART_COLORS[i % CHART_COLORS.length]),
            fill: config.type === 'line',
            tension: 0.3,
            borderWidth: 2
          }]
        },
        options: {
          responsive: true,
          animation: { duration: 500 },
          plugins: { legend: { position: ['pie','doughnut'].includes(config.type) ? 'right' : 'top' } },
          scales: !['pie','doughnut'].includes(config.type) ? {
            y: { beginAtZero: true, title: { display: !!d.yLabel, text: d.yLabel || '' } }
          } : undefined
        }
      };
    }
    chartInstances[canvasId] = new Chart(ctx, chartCfg);
  }

  async function renderSubsectionPanel(containerId, key) {
    const container = document.getElementById(containerId);
    if (!container) return;
    const sub = SUBSECTIONS[key];
    if (!sub) return;

    container.innerHTML = `<div style="padding:20px;text-align:center;color:#7f8c8d"><i class="fas fa-spinner fa-spin"></i> Loading...</div>`;

    const records = await fetchRecords(key);

    const colHeaders = sub.columns.map(c => `<th>${c.label}</th>`).join('');
    const analytics = sub.getAnalytics(records);
    const charts = sub.getCharts(records);

    const cardsHtml = analytics.map(a => `
      <div class="bsf-card" style="border-left: 4px solid ${a.color}">
        <div class="bsf-card-icon" style="color:${a.color}"><i class="fas ${a.icon}"></i></div>
        <div class="bsf-card-content">
          <div class="bsf-card-value">${a.value}</div>
          <div class="bsf-card-label">${a.label}</div>
        </div>
      </div>`).join('');

    const chartsHtml = charts.map(c => `
      <div class="bsf-chart-container">
        <h4 class="bsf-chart-title">${c.title}</h4>
        <canvas id="chart-${c.id}" height="200"></canvas>
      </div>`).join('');

    const tbodyRows = records.length === 0
      ? `<tr><td colspan="${sub.columns.length}" class="bsf-empty">No records found in the database.</td></tr>`
      : records.slice(0, 50).map(r => `
          <tr>
            ${sub.columns.map(c => `<td title="${r[c.field] !== undefined && r[c.field] !== null ? r[c.field] : ''}">${r[c.field] !== undefined && r[c.field] !== null && r[c.field] !== '' ? r[c.field] : '—'}</td>`).join('')}
          </tr>`).join('');

    container.innerHTML = `
      <div class="bsf-panel-header">
        <span class="bsf-panel-title"><i class="fas fa-chart-bar"></i> ${sub.label}</span>
        <span class="bsf-badge">${records.length} record${records.length !== 1 ? 's' : ''}</span>
      </div>
      ${analytics.length ? `<div class="bsf-summary-cards">${cardsHtml}</div>` : ''}
      ${charts.length && records.length ? `<div class="bsf-charts-grid">${chartsHtml}</div>` : ''}
      <div class="bsf-table-section">
        <h4 class="bsf-table-title"><i class="fas fa-table"></i> Records Table ${records.length > 50 ? '(showing latest 50)' : ''}</h4>
        <div class="bsf-table-wrapper">
          <table class="bsf-table">
            <thead><tr>${colHeaders}</tr></thead>
            <tbody>${tbodyRows}</tbody>
          </table>
        </div>
      </div>
      <div class="bsf-export-buttons">
        <button class="bsf-btn-excel" onclick="ExportManager.toExcel('${key}', '${sub.label}')">
          <i class="fas fa-file-excel"></i> Export Excel
        </button>
        <button class="bsf-btn-pdf" onclick="ExportManager.toPDF('${key}', '${sub.label}')">
          <i class="fas fa-file-pdf"></i> Export PDF
        </button>
      </div>`;

    if (records.length) {
      charts.forEach(c => buildChart(`chart-${c.id}`, c, records));
    }
  }

  return { SUBSECTIONS, renderSubsectionPanel, fetchRecords };
})();
