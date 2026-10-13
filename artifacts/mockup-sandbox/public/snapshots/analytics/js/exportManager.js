const ExportManager = (() => {

  function prettifyKey(key) {
    return key
      .replace(/_/g, ' ')
      .replace(/([A-Z])/g, ' $1')
      .replace(/\b\w/g, l => l.toUpperCase())
      .trim();
  }

  function getColumns(records) {
    if (!records.length) return [];
    return Object.keys(records[0]).filter(k => k !== 'id' && !k.startsWith('_') && k !== 'created_at' && k !== 'updated_at');
  }

  function getSummary(key, records) {
    if (!records.length) return 'No records available.';
    const cols = getColumns(records);
    const lines = [`Section: ${prettifyKey(key)}`, `Total Records: ${records.length}`, `Generated: ${new Date().toLocaleString()}`];
    cols.forEach(field => {
      const vals = records.map(r => parseFloat(r[field])).filter(v => !isNaN(v));
      if (vals.length > 1) {
        const sum = vals.reduce((a, b) => a + b, 0);
        lines.push(`${prettifyKey(field)} — Total: ${sum.toFixed(2)}, Avg: ${(sum / vals.length).toFixed(2)}`);
      }
    });
    return lines.join('\n');
  }

  async function toExcel(key, label) {
    if (typeof XLSX === 'undefined') {
      alert('Excel library not loaded. Please check your internet connection.');
      return;
    }

    const records = await AnalyticsManager.fetchRecords(key);
    if (!records.length) {
      alert('No records to export for this section.');
      return;
    }

    const wb = XLSX.utils.book_new();
    const cols = getColumns(records);
    const headers = cols.map(prettifyKey);

    const summaryLines = getSummary(key, records).split('\n').map(l => [l]);
    const summarySheet = XLSX.utils.aoa_to_sheet([['Summary Report'], ...summaryLines]);
    XLSX.utils.book_append_sheet(wb, summarySheet, 'Summary');

    const dataRows = records.map(r => cols.map(c => {
      const val = r[c];
      if (Array.isArray(val)) return val.join(', ');
      return val !== undefined && val !== null ? val : '';
    }));
    const dataSheet = XLSX.utils.aoa_to_sheet([headers, ...dataRows]);

    const colWidths = headers.map((h, i) => ({
      wch: Math.max(h.length, ...dataRows.map(row => String(row[i] || '').length), 12)
    }));
    dataSheet['!cols'] = colWidths;

    XLSX.utils.book_append_sheet(wb, dataSheet, label.substring(0, 31));

    const filename = `BSF_${label.replace(/\s+/g, '_')}_${new Date().toISOString().slice(0, 10)}.xlsx`;
    XLSX.writeFile(wb, filename);
  }

  async function toPDF(key, label) {
    if (typeof window.jspdf === 'undefined' && typeof jsPDF === 'undefined') {
      alert('PDF library not loaded. Please check your internet connection.');
      return;
    }

    const records = await AnalyticsManager.fetchRecords(key);
    if (!records.length) {
      alert('No records to export for this section.');
      return;
    }

    const { jsPDF: JSPDF } = window.jspdf || { jsPDF: window.jsPDF };
    const doc = new JSPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });

    const primaryColor = [46, 204, 113];
    const darkColor = [44, 62, 80];

    doc.setFillColor(...primaryColor);
    doc.rect(0, 0, 297, 25, 'F');
    doc.setTextColor(255, 255, 255);
    doc.setFontSize(16);
    doc.setFont('helvetica', 'bold');
    doc.text(`BSF Farm - ${label}`, 14, 10);
    doc.setFontSize(10);
    doc.setFont('helvetica', 'normal');
    doc.text(`Generated: ${new Date().toLocaleString()}`, 14, 18);
    doc.text(`Total Records: ${records.length}`, 180, 18);

    doc.setTextColor(...darkColor);
    doc.setFontSize(12);
    doc.setFont('helvetica', 'bold');
    doc.text('Summary', 14, 34);

    doc.setFont('helvetica', 'normal');
    doc.setFontSize(10);
    let yPos = 42;
    const cols = getColumns(records);

    cols.forEach(field => {
      const vals = records.map(r => parseFloat(r[field])).filter(v => !isNaN(v));
      if (vals.length > 1) {
        const sum = vals.reduce((a, b) => a + b, 0);
        doc.setTextColor(100, 100, 100);
        doc.text(`${prettifyKey(field)}:`, 14, yPos);
        doc.setTextColor(...darkColor);
        doc.text(`Total: ${sum.toFixed(2)}   Avg: ${(sum / vals.length).toFixed(2)}   Count: ${vals.length}`, 70, yPos);
        yPos += 7;
        if (yPos > 65) return;
      }
    });

    const headers = cols.map(prettifyKey);
    const tableData = records.map(r => cols.map(c => {
      const val = r[c];
      if (Array.isArray(val)) return val.join(', ');
      return val !== undefined && val !== null && val !== '' ? String(val) : '—';
    }));

    const maxCols = Math.min(cols.length, 10);
    const truncatedHeaders = headers.slice(0, maxCols);
    const truncatedData = tableData.map(row => row.slice(0, maxCols));

    doc.autoTable({
      head: [truncatedHeaders],
      body: truncatedData,
      startY: Math.max(yPos + 5, 70),
      styles: { fontSize: 8, cellPadding: 2 },
      headStyles: {
        fillColor: primaryColor,
        textColor: [255, 255, 255],
        fontStyle: 'bold'
      },
      alternateRowStyles: { fillColor: [245, 246, 250] },
      columnStyles: {},
      margin: { left: 14, right: 14 },
      tableWidth: 'auto',
      didDrawPage: function (data) {
        doc.setFillColor(...primaryColor);
        doc.rect(0, 200, 297, 10, 'F');
        doc.setTextColor(255, 255, 255);
        doc.setFontSize(8);
        doc.text('BSF Farm Management System - eFarm Zehunger', 14, 207);
        doc.text(`Page ${data.pageNumber}`, 270, 207);
      }
    });

    const filename = `BSF_${label.replace(/\s+/g, '_')}_${new Date().toISOString().slice(0, 10)}.pdf`;
    doc.save(filename);
  }

  return { toExcel, toPDF };
})();
