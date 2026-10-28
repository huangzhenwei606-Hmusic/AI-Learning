/* Keep the app on the document page while saving or handing off to the share sheet. */
document.querySelectorAll('.document-save').forEach(button => {
  button.addEventListener('click', async () => {
    const status = document.querySelector('.document-status');
    button.disabled = true;
    status.textContent = 'Preparing PDF…';
    try {
      const response = await fetch(button.dataset.pdfUrl, {credentials: 'same-origin', cache: 'no-store'});
      if (!response.ok || !response.headers.get('content-type')?.includes('application/pdf')) {
        throw new Error('PDF unavailable');
      }
      const blob = await response.blob();
      const file = new File([blob], button.dataset.filename, {type: 'application/pdf'});
      if (navigator.share && navigator.canShare && navigator.canShare({files: [file]})) {
        await navigator.share({files: [file], title: button.dataset.filename});
        status.textContent = 'Share sheet closed. Use Back to invoice to return.';
      } else {
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = button.dataset.filename;
        link.target = '_blank';
        link.rel = 'noopener';
        document.body.appendChild(link);
        link.click();
        link.remove();
        setTimeout(() => URL.revokeObjectURL(url), 60000);
        status.textContent = 'Download requested. Use Back to invoice to return.';
      }
    } catch (error) {
      status.textContent = error.name === 'AbortError'
        ? 'Save cancelled. You can try again or return to your invoice.'
        : 'Unable to prepare the PDF. Try again, or use Back to invoice.';
    } finally {
      button.disabled = false;
    }
  });
});
