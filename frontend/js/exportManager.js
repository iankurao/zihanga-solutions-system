const ExportManager = (() => {

  // Generic exports for already-loaded report rows.
  // columns: [{key, label}], rows: [{...}], summaryLines: ['Filter: ...', ...]
  function reportCells(columns, rows, format) {
    return rows.map(row => columns.map(col => {
      const value = row[col.key];
      if (value === undefined || value === null || value === '') return format ? '—' : '';
      return format ? format(col, value) : value;
    }));
  }

  function fileStamp(title, extension) {
    return `Zehunger_${title.replace(/[^A-Za-z0-9]+/g, '_')}_${new Date().toISOString().slice(0, 10)}.${extension}`;
  }

  function rowsToExcel(title, columns, rows, summaryLines) {
    if (typeof XLSX === 'undefined') {
      alert('Excel library not loaded. Please check your internet connection.');
      return;
    }
    const wb = XLSX.utils.book_new();
    const summary = XLSX.utils.aoa_to_sheet([[title], ...summaryLines.map(line => [line])]);
    XLSX.utils.book_append_sheet(wb, summary, 'Summary');
    const headers = columns.map(col => col.label);
    const body = reportCells(columns, rows);
    const sheet = XLSX.utils.aoa_to_sheet([headers, ...body]);
    sheet['!cols'] = headers.map((h, i) => ({
      wch: Math.min(60, Math.max(h.length, ...body.map(r => String(r[i] ?? '').length), 10))
    }));
    XLSX.utils.book_append_sheet(wb, sheet, 'Report');
    XLSX.writeFile(wb, fileStamp(title, 'xlsx'));
  }

  function rowsToPDF(title, columns, rows, summaryLines, formatValue) {
    if (typeof window.jspdf === 'undefined' && typeof jsPDF === 'undefined') {
      alert('PDF library not loaded. Please check your internet connection.');
      return;
    }
    const { jsPDF: JSPDF } = window.jspdf || { jsPDF: window.jsPDF };
    const doc = new JSPDF({ orientation: 'landscape', unit: 'mm', format: 'a4' });
    const brand = [20, 60, 45];
    doc.setFillColor(...brand);
    doc.rect(0, 0, 297, 22, 'F');
    doc.setTextColor(255, 255, 255);
    doc.setFont('helvetica', 'bold');
    doc.setFontSize(15);
    doc.text(`Zehunger · ${title}`, 14, 10);
    doc.setFont('helvetica', 'normal');
    doc.setFontSize(9);
    doc.text(`Generated ${new Date().toLocaleString()} · ${rows.length} rows`, 14, 17);
    doc.setTextColor(40, 40, 40);
    let y = 30;
    summaryLines.forEach(line => { doc.text(String(line), 14, y); y += 5; });
    doc.autoTable({
      head: [columns.map(col => col.label)],
      body: reportCells(columns, rows, formatValue),
      startY: y + 2,
      styles: { fontSize: 7.5, cellPadding: 1.6, overflow: 'linebreak' },
      headStyles: { fillColor: brand, textColor: [255, 255, 255], fontStyle: 'bold' },
      alternateRowStyles: { fillColor: [244, 247, 245] },
      margin: { left: 10, right: 10 },
      didDrawPage: function (data) {
        doc.setFontSize(8);
        doc.setTextColor(120, 120, 120);
        doc.text(`Page ${data.pageNumber}`, 280, 205);
      }
    });
    doc.save(fileStamp(title, 'pdf'));
  }

  return { rowsToExcel, rowsToPDF };
})();
