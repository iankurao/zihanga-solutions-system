const DataManager = (() => {
  const PREFIX = 'bsf_data_';

  function getAll(key) {
    try {
      return JSON.parse(localStorage.getItem(PREFIX + key) || '[]');
    } catch (e) {
      return [];
    }
  }

  function save(key, record) {
    const records = getAll(key);
    const entry = {
      ...record,
      _id: Date.now() + '_' + Math.random().toString(36).substr(2, 9),
      _savedAt: new Date().toISOString()
    };
    records.push(entry);
    try {
      localStorage.setItem(PREFIX + key, JSON.stringify(records));
    } catch (e) {
      console.error('DataManager: storage full or unavailable', e);
    }
    document.dispatchEvent(new CustomEvent('bsf:dataChanged', { detail: { key, records } }));
    return entry;
  }

  function remove(key, id) {
    const records = getAll(key).filter(r => r._id !== id);
    localStorage.setItem(PREFIX + key, JSON.stringify(records));
    document.dispatchEvent(new CustomEvent('bsf:dataChanged', { detail: { key, records } }));
    return records;
  }

  function update(key, id, updates) {
    const records = getAll(key).map(r => r._id === id ? { ...r, ...updates } : r);
    localStorage.setItem(PREFIX + key, JSON.stringify(records));
    document.dispatchEvent(new CustomEvent('bsf:dataChanged', { detail: { key, records } }));
    return records;
  }

  function getFormData(form) {
    const data = {};
    const formData = new FormData(form);
    const multiSelects = Array.from(form.querySelectorAll('select[multiple]')).map(s => s.name);
    formData.forEach((value, key) => {
      if (multiSelects.includes(key)) {
        if (!data[key]) data[key] = [];
        data[key].push(value);
      } else {
        data[key] = value;
      }
    });
    multiSelects.forEach(name => {
      if (!data[name]) data[name] = [];
    });
    return data;
  }

  return { getAll, save, remove, update, getFormData };
})();
