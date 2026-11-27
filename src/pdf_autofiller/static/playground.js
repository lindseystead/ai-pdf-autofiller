    const drop = document.getElementById('drop');
    const fileInput = document.getElementById('file');
    const fileName = document.getElementById('fileName');
    const userData = document.getElementById('userData');
    const fillBtn = document.getElementById('fillBtn');
    const sampleBtn = document.getElementById('sampleBtn');
    const loadSamplePdfBtn = document.getElementById('loadSamplePdfBtn');
    const inspectBtn = document.getElementById('inspectBtn');
    const templateBtn = document.getElementById('templateBtn');
    const previewBtn = document.getElementById('previewBtn');
    const statusEl = document.getElementById('status');
    const inspectOut = document.getElementById('inspectOut');
    const download = document.getElementById('download');
    const apiKey = document.getElementById('apiKey');
    const incompleteWarning = document.getElementById('incompleteWarning');
    const incompleteText = document.getElementById('incompleteText');
    const ackIncomplete = document.getElementById('ackIncomplete');
    const pdfPreview = document.getElementById('pdfPreview');
    const pdfPreviewLabel = document.getElementById('pdfPreviewLabel');
    const aiConsent = document.getElementById('aiConsent');
    const aiAvailability = document.getElementById('aiAvailability');
    const fieldMapping = document.getElementById('fieldMapping');
    const saveMappingBtn = document.getElementById('saveMappingBtn');
    const loadMappingBtn = document.getElementById('loadMappingBtn');
    const clearMappingBtn = document.getElementById('clearMappingBtn');
    const refreshMappingBtn = document.getElementById('refreshMappingBtn');
    const mappingEditor = document.getElementById('mappingEditor');

    let selectedFile = null;
    let downloadUrl = null;
    let previewUrl = null;
    let previewKind = null;
    let providerAvailable = false;
    let selectedPdfKey = null;
    let templateFields = [];

    function setStatus(message, kind = '') {
      statusEl.className = 'status' + (kind ? ' ' + kind : '');
      statusEl.textContent = message;  // messages can echo PDF field names: never parse as HTML
    }

    function showPdf(blob, kind) {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      previewUrl = URL.createObjectURL(blob);
      previewKind = kind;
      pdfPreview.data = previewUrl;
      pdfPreview.hidden = false;
      pdfPreviewLabel.textContent = kind === 'filled'
        ? 'Review the filled PDF below before downloading it.'
        : 'Original PDF. Fill it to preview the completed result.';
    }

    function resetFilledResult() {
      if (downloadUrl) URL.revokeObjectURL(downloadUrl);
      downloadUrl = null;
      download.removeAttribute('href');
      download.hidden = true;
      download.textContent = 'Download filled PDF';
      incompleteWarning.hidden = true;
      incompleteText.textContent = '';
      ackIncomplete.checked = false;
      if (selectedFile && previewKind === 'filled') showPdf(selectedFile, 'original');
    }

    function updateAiControls() {
      const enabled = aiConsent.checked && providerAvailable;
      fallbackBox.disabled = !enabled;
      semanticBox.disabled = !enabled;
      if (!enabled) {
        fallbackBox.checked = false;
        semanticBox.checked = false;
        strictBox.checked = true;
      }
      resetFilledResult();
    }

    // Strict mode disables the AI key fallback; keep the two boxes from contradicting.
    const strictBox = document.getElementById('strict');
    const fallbackBox = document.getElementById('fallback');
    const semanticBox = document.getElementById('semantic');
    strictBox.addEventListener('change', () => { if (strictBox.checked) fallbackBox.checked = false; });
    fallbackBox.addEventListener('change', () => { if (fallbackBox.checked) strictBox.checked = false; });
    aiConsent.addEventListener('change', updateAiControls);

    fetch('/health')
      .then(response => response.json())
      .then(payload => {
        providerAvailable = payload?.checks?.semantic_provider === 'available';
        aiAvailability.textContent = providerAvailable
          ? 'AI is configured. Acknowledgment is required before enabling it.'
          : 'AI is not configured on this server; deterministic matching remains available.';
        updateAiControls();
      })
      .catch(() => {
        aiAvailability.textContent = 'Could not verify AI availability; AI controls remain disabled.';
        updateAiControls();
      });

    function authHeaders() {
      const headers = {};
      if (apiKey.value.trim()) headers['X-API-Key'] = apiKey.value.trim();
      return headers;
    }

    function formatApiError(payload, status) {
      const err = payload?.detail?.error || payload?.detail || payload;
      if (err && typeof err === 'object') {
        const code = err.code ? '[' + err.code + '] ' : '';
        const msg = err.message || JSON.stringify(err);
        const details = err.details ? ' ' + JSON.stringify(err.details) : '';
        return code + msg + details;
      }
      return 'Request failed (' + status + ')';
    }

    drop.addEventListener('click', () => fileInput.click());
    drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('dragover'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('dragover'));
    drop.addEventListener('drop', (e) => {
      e.preventDefault();
      drop.classList.remove('dragover');
      if (e.dataTransfer.files.length) pickFile(e.dataTransfer.files[0]);
    });
    fileInput.addEventListener('change', () => {
      if (fileInput.files.length) pickFile(fileInput.files[0]);
    });

    async function pdfStorageKey(file) {
      const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer());
      const hex = Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, '0')).join('');
      return 'pdf-autofiller:mapping:' + hex;
    }

    function parseObject(text, label) {
      const parsed = JSON.parse(text);
      if (typeof parsed !== 'object' || Array.isArray(parsed) || parsed === null) {
        throw new Error(label + ' must be a JSON object');
      }
      return parsed;
    }

    function flattenedKeys(value, prefix = '') {
      const keys = [];
      for (const [key, child] of Object.entries(value)) {
        const path = prefix ? prefix + '.' + key : key;
        if (child && typeof child === 'object' && !Array.isArray(child)) {
          keys.push(...flattenedKeys(child, path));
        } else {
          keys.push(path);
        }
      }
      return keys.sort();
    }

    function renderMappingEditor() {
      mappingEditor.replaceChildren();
      if (!templateFields.length) {
        mappingEditor.textContent = 'Create a starter mapping to edit fields visually.';
        return;
      }
      let keys;
      let mapping;
      try {
        keys = flattenedKeys(parseObject(userData.value, 'User data'));
        mapping = parseObject(fieldMapping.value, 'Field mapping');
      } catch (err) {
        mappingEditor.textContent = 'Fix the JSON above to refresh the visual editor.';
        return;
      }
      const table = document.createElement('table');
      table.className = 'mapping-table';
      const header = document.createElement('tr');
      for (const text of ['PDF field', 'JSON key']) {
        const cell = document.createElement('th');
        cell.scope = 'col';
        cell.textContent = text;
        header.appendChild(cell);
      }
      const head = document.createElement('thead');
      head.appendChild(header);
      table.appendChild(head);
      const body = document.createElement('tbody');
      for (const field of templateFields) {
        if (field.field_type === 'signature') continue;
        const row = document.createElement('tr');
        const nameCell = document.createElement('td');
        nameCell.textContent = field.field_name + (field.required ? ' *' : '');
        const selectCell = document.createElement('td');
        const select = document.createElement('select');
        select.setAttribute('aria-label', 'JSON key for ' + field.field_name);
        const none = document.createElement('option');
        none.value = '';
        none.textContent = 'Do not map';
        select.appendChild(none);
        for (const key of keys) {
          const option = document.createElement('option');
          option.value = key;
          option.textContent = key;
          select.appendChild(option);
        }
        select.value = mapping[field.field_name] || '';
        select.addEventListener('change', () => {
          const next = parseObject(fieldMapping.value, 'Field mapping');
          if (select.value) next[field.field_name] = select.value;
          else delete next[field.field_name];
          fieldMapping.value = JSON.stringify(next, null, 2);
          resetFilledResult();
        });
        selectCell.appendChild(select);
        row.appendChild(nameCell);
        row.appendChild(selectCell);
        body.appendChild(row);
      }
      table.appendChild(body);
      mappingEditor.appendChild(table);
    }

    function loadSavedMapping() {
      if (!selectedPdfKey) return false;
      const saved = localStorage.getItem(selectedPdfKey);
      if (!saved) return false;
      fieldMapping.value = saved;
      resetFilledResult();
      return true;
    }

    async function pickFile(file) {
      if (!file.name.toLowerCase().endsWith('.pdf')) {
        setStatus('Please upload a PDF file.', 'err');
        return;
      }
      selectedFile = file;
      selectedPdfKey = await pdfStorageKey(file);
      templateFields = [];
      renderMappingEditor();
      resetFilledResult();
      download.download = file.name.replace(/\.pdf$/i, '') + '_filled.pdf';
      fileName.textContent = file.name + ' (' + Math.round(file.size / 1024) + ' KB)';
      showPdf(file, 'original');
      setStatus('PDF ready. Click Fill PDF when your JSON looks good.');
      inspectOut.hidden = true;
      if (loadSavedMapping()) setStatus('PDF ready. Its saved field mapping was loaded.');
    }

    sampleBtn.addEventListener('click', () => {
      userData.value = JSON.stringify({
        firstname: 'Jane',
        lastname: 'Doe',
        dob: '1990-01-01',
        email: 'jane@example.com',
        phone: '555-0100'
      }, null, 2);
      resetFilledResult();
      setStatus('Sample JSON loaded for the bundled sample form.');
    });

    userData.addEventListener('input', resetFilledResult);
    fieldMapping.addEventListener('input', resetFilledResult);
    apiKey.addEventListener('input', resetFilledResult);
    for (const option of document.querySelectorAll('.checks input')) {
      option.addEventListener('change', resetFilledResult);
    }
    ackIncomplete.addEventListener('change', () => {
      download.hidden = !(ackIncomplete.checked && downloadUrl);
    });
    window.addEventListener('beforeunload', () => {
      if (downloadUrl) URL.revokeObjectURL(downloadUrl);
      if (previewUrl) URL.revokeObjectURL(previewUrl);
    });

    saveMappingBtn.addEventListener('click', () => {
      if (!selectedPdfKey) {
        setStatus('Choose a PDF before saving a field mapping.', 'err');
        return;
      }
      try {
        const normalized = JSON.stringify(parseObject(fieldMapping.value, 'Field mapping'), null, 2);
        fieldMapping.value = normalized;
        localStorage.setItem(selectedPdfKey, normalized);
        setStatus('Field mapping saved in this browser for this exact PDF.', 'ok');
      } catch (err) {
        setStatus('Invalid field mapping: ' + err.message, 'err');
      }
    });
    loadMappingBtn.addEventListener('click', () => {
      setStatus(loadSavedMapping() ? 'Saved field mapping loaded.' : 'No mapping is saved for this PDF.');
    });
    clearMappingBtn.addEventListener('click', () => {
      if (selectedPdfKey) localStorage.removeItem(selectedPdfKey);
      fieldMapping.value = '{}';
      resetFilledResult();
      setStatus('Field mapping cleared.');
      renderMappingEditor();
    });
    refreshMappingBtn.addEventListener('click', renderMappingEditor);

    loadSamplePdfBtn.addEventListener('click', async () => {
      setStatus('Loading sample PDF…');
      try {
        const response = await fetch('/samples/sample_form.pdf');
        if (!response.ok) {
          setStatus('Sample PDF is not available in this deployment.', 'err');
          return;
        }
        const blob = await response.blob();
        pickFile(new File([blob], 'sample_form.pdf', { type: 'application/pdf' }));
        sampleBtn.click();
      } catch (err) {
        setStatus('Could not load sample PDF: ' + err.message, 'err');
      }
    });

    inspectBtn.addEventListener('click', async () => {
      if (!selectedFile) {
        setStatus('Upload a PDF first (or click Use sample PDF).', 'err');
        return;
      }
      inspectBtn.disabled = true;
      setStatus('Inspecting fields…');
      const form = new FormData();
      form.append('pdf_file', selectedFile, selectedFile.name);
      try {
        const response = await fetch('/inspect', { method: 'POST', body: form, headers: authHeaders() });
        const payload = await response.json();
        if (!response.ok) {
          setStatus(formatApiError(payload, response.status), 'err');
          return;
        }
        const lines = payload.fields.map(f => {
          const quality = f.name_quality === 'opaque' ? ' [opaque]' : '';
          return (f.required ? '* ' : '  ') + f.name + ' (' + f.field_type + ', page ' + f.page_number + ')' + quality;
        });
        const hints = (payload.mapping_hints || []).map(h => '- ' + h).join('\n');
        inspectOut.hidden = false;
        inspectOut.textContent =
          'Fields (' + payload.field_count + ', opaque: ' + (payload.opaque_field_count || 0) + '):\n'
          + lines.join('\n')
          + (hints ? '\n\nHints:\n' + hints : '');
        templateFields = payload.fields.map(field => ({
          field_name: field.name,
          key: null,
          required: field.required,
          field_type: field.field_type
        }));
        setStatus(
          payload.opaque_field_count
            ? 'Inspect complete. Opaque names detected — see hints below.'
            : 'Inspect complete. Required fields are marked with *.'
        );
      } catch (err) {
        setStatus('Network error: ' + err.message, 'err');
      } finally {
        inspectBtn.disabled = false;
      }
    });

    templateBtn.addEventListener('click', async () => {
      if (!selectedFile) {
        setStatus('Upload a PDF first (or click Use sample PDF).', 'err');
        return;
      }
      templateBtn.disabled = true;
      setStatus('Creating starter data and field mapping…');
      const form = new FormData();
      form.append('pdf_file', selectedFile, selectedFile.name);
      try {
        const response = await fetch('/template', { method: 'POST', body: form, headers: authHeaders() });
        const payload = await response.json();
        if (!response.ok) {
          setStatus(formatApiError(payload, response.status), 'err');
          return;
        }
        userData.value = JSON.stringify(payload.example || {}, null, 2);
        const mapping = {};
        for (const field of payload.fields || []) {
          if (field.key) mapping[field.field_name] = field.key;
        }
        fieldMapping.value = JSON.stringify(mapping, null, 2);
        templateFields = payload.fields || [];
        renderMappingEditor();
        resetFilledResult();
        setStatus('Starter mapping created. Add values, review the mapping, then save it for reuse.', 'ok');
      } catch (err) {
        setStatus('Network error: ' + err.message, 'err');
      } finally {
        templateBtn.disabled = false;
      }
    });

    previewBtn.addEventListener('click', async () => {
      if (!selectedFile) {
        setStatus('Upload a PDF first (or click Use sample PDF).', 'err');
        return;
      }
      let parsed;
      try {
        parsed = parseObject(userData.value, 'User data');
      } catch (err) {
        setStatus('Invalid JSON: ' + err.message, 'err');
        return;
      }
      previewBtn.disabled = true;
      setStatus('Previewing mapping…');
      const form = new FormData();
      form.append('pdf_file', selectedFile, selectedFile.name);
      form.append('user_data', JSON.stringify(parsed));
      try {
        form.append('field_mapping', JSON.stringify(parseObject(fieldMapping.value, 'Field mapping')));
      } catch (err) {
        setStatus('Invalid field mapping: ' + err.message, 'err');
        previewBtn.disabled = false;
        return;
      }
      form.append('strict', document.getElementById('strict').checked ? 'true' : 'false');
      form.append('allow_fallback_mapping', document.getElementById('fallback').checked ? 'true' : 'false');
      form.append('use_semantic_inference', document.getElementById('semantic').checked ? 'true' : 'false');
      try {
        const response = await fetch('/preview', { method: 'POST', body: form, headers: authHeaders() });
        const payload = await response.json();
        if (!response.ok) {
          setStatus(formatApiError(payload, response.status), 'err');
          return;
        }
        const decisionLines = (payload.decisions || []).map(d => {
          const review = d.requires_review ? ' [review]' : '';
          const val = d.selected_value == null ? '(empty)' : JSON.stringify(d.selected_value);
          return d.field_name + ' ← ' + val + ' (' + d.confidence.toFixed(2) + ')' + review
            + '\n    ' + d.semantic_meaning + ' — ' + d.reason;
        });
        const missing = (payload.missing_required || []).join(', ') || '(none)';
        const unmapped = (payload.unmapped_user_keys || []).join(', ') || '(none)';
        const hints = (payload.mapping_hints || []).map(h => '- ' + h).join('\n');
        inspectOut.hidden = false;
        inspectOut.textContent =
          'Preview (' + payload.field_count + ' fields, ' + payload.pages + ' pages)\n\n'
          + 'Decisions:\n' + (decisionLines.join('\n') || '(none)') + '\n\n'
          + 'Missing required: ' + missing + '\n'
          + 'Unmapped user keys: ' + unmapped
          + (hints ? '\n\nHints:\n' + hints : '');
        setStatus('Preview complete. Review decisions before filling.', 'ok');
      } catch (err) {
        setStatus('Network error: ' + err.message, 'err');
      } finally {
        previewBtn.disabled = false;
      }
    });

    fillBtn.addEventListener('click', async () => {
      if (!selectedFile) {
        setStatus('Upload a PDF first (or click Use sample PDF).', 'err');
        return;
      }

      let parsed;
      try {
        parsed = parseObject(userData.value, 'User data');
      } catch (err) {
        setStatus('Invalid JSON: ' + err.message, 'err');
        return;
      }

      fillBtn.disabled = true;
      resetFilledResult();
      setStatus('Filling PDF…');

      const form = new FormData();
      form.append('pdf_file', selectedFile, selectedFile.name);
      form.append('user_data', JSON.stringify(parsed));
      try {
        form.append('field_mapping', JSON.stringify(parseObject(fieldMapping.value, 'Field mapping')));
      } catch (err) {
        setStatus('Invalid field mapping: ' + err.message, 'err');
        fillBtn.disabled = false;
        return;
      }
      form.append('strict', document.getElementById('strict').checked ? 'true' : 'false');
      form.append('allow_fallback_mapping', document.getElementById('fallback').checked ? 'true' : 'false');
      form.append('use_semantic_inference', document.getElementById('semantic').checked ? 'true' : 'false');
      form.append('flatten', document.getElementById('flatten').checked ? 'true' : 'false');
      form.append('allow_partial', document.getElementById('allowPartial').checked ? 'true' : 'false');
      form.append('need_appearances', document.getElementById('needAppearances').checked ? 'true' : 'false');

      try {
        const response = await fetch('/fill', { method: 'POST', body: form, headers: authHeaders() });
        if (!response.ok) {
          let detail = 'Request failed (' + response.status + ')';
          try {
            detail = formatApiError(await response.json(), response.status);
          } catch (_) {}
          setStatus(detail, 'err');
          return;
        }

        const filledBlob = await response.blob();
        downloadUrl = URL.createObjectURL(filledBlob);
        download.href = downloadUrl;
        showPdf(filledBlob, 'filled');

        const written = response.headers.get('X-PDF-Fields-Written') || '?';
        const skippedReview = response.headers.get('X-PDF-Fields-Skipped-Review') || '(none)';
        const skippedEmpty = response.headers.get('X-PDF-Fields-Skipped-Empty') || '(none)';
        const skippedUnwritable = response.headers.get('X-PDF-Fields-Skipped-Unwritable') || '(none)';
        const displayWarnings = response.headers.get('X-PDF-Fields-Display-Warnings') || '(none)';
        const aiAssisted = response.headers.get('X-PDF-Fields-AI-Assisted') || '(none)';
        const missingRequired = response.headers.get('X-PDF-Fields-Missing-Required') || '';
        const report =
          'Fill report\n'
          + 'Written: ' + written + '\n'
          + 'Skipped (review): ' + skippedReview + '\n'
          + 'Skipped (empty): ' + skippedEmpty + '\n'
          + 'Skipped (unwritable): ' + skippedUnwritable + '\n'
          + 'Display warnings: ' + displayWarnings + '\n'
          + 'Mapped by AI (review): ' + aiAssisted + '\n'
          + 'Missing required: ' + (missingRequired || '(none)');
        inspectOut.hidden = false;
        inspectOut.textContent = report;
        if (missingRequired) {
          incompleteText.textContent = 'Incomplete PDF — required fields are missing: ' + missingRequired + '.';
          incompleteWarning.hidden = false;
          download.textContent = 'Download incomplete PDF';
          download.hidden = true;
          setStatus(
            'The PDF was generated but is incomplete. Review the missing required fields and acknowledge the warning before downloading.',
            'warn'
          );
        } else {
          download.hidden = false;
          setStatus(
            'Success! Wrote ' + written + ' fields. Skipped review: '
            + skippedReview + '. Skipped empty: ' + skippedEmpty
            + '. Unwritable: ' + skippedUnwritable
            + '. Review the preview, then download the filled PDF.',
            'ok'
          );
        }
      } catch (err) {
        setStatus('Network error: ' + err.message, 'err');
      } finally {
        fillBtn.disabled = false;
      }
    });
