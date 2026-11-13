/* Registered workflow document actions always recheck backend grants. */
(function () {
  ['exportSheet', 'taskExportCsv', 'exportProductionReport', 'printSalarySlip'].forEach(function (name) {
    var previous = window[name];
    window[name] = async function () {
      var response = await fetch('/api/v1/auth/me', {
        headers: { Authorization: 'Bearer ' + (localStorage.getItem('epv3_access_token') || '') }, cache: 'no-store'
      }).catch(function () { return null; });
      if (!response || !response.ok) { window.toast('Sesi tidak berlaku. Login ulang.'); return; }
      var me = await response.json();
      if (me.workflow_authorization !== 'enforced') return previous && previous.apply(this, arguments);
      var kind = {exportSheet:'job.export',taskExportCsv:'task.export',exportProductionReport:'report.production.export',printSalarySlip:'payroll.print'}[name];
      var query = '';
      if (kind === 'payroll.print') {
        var runId = Number(window.v3LastPayrollRunId);
        if (!Number.isInteger(runId) || runId <= 0) { window.toast('Hitung periode payroll dulu sebelum mencetak.'); return; }
        query = '?run_id=' + runId;
      }
      var result = await fetch('/api/v1/production/access/documents/' + kind + query, {
        headers: {Authorization:'Bearer ' + localStorage.getItem('epv3_access_token')}, cache:'no-store'
      });
      if (!result.ok) { window.toast('Export ditolak: perlu grant manual sesuai scope.'); return; }
      var payload = await result.json();
      if (kind === 'payroll.print') return previous && previous.apply(this, arguments);
      var blob = new Blob([JSON.stringify(payload, null, 2)], {type:'application/json'});
      var url = URL.createObjectURL(blob), link = document.createElement('a');
      link.href=url;link.download=kind+'.json';link.click();URL.revokeObjectURL(url);
    };
  });
})();
