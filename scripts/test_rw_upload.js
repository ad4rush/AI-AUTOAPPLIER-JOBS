(async () => {
  const task = await taskSpace('test_rw_upload', { profileId: 'Profile 1' });
  const page = task.page('p1');
  console.log('[*] Navigating to https://resumeworded.com/upload-resume ...');
  await page.goto('https://resumeworded.com/upload-resume', { waitUntil: 'domcontentloaded', timeout: 25000 });
  await new Promise(r => setTimeout(r, 4000));

  console.log('[*] URL:', await page.url());
  console.log('[*] Title:', await page.title());

  const dropzone = await page.evaluate(() => {
    const fileInputs = Array.from(document.querySelectorAll('input[type="file"], input.dz-hidden-input'));
    const dropzoneEl = document.querySelector('.dropzone, [class*="upload"], [class*="drop"]');
    return {
      fileInputsCount: fileInputs.length,
      hasDropzone: !!dropzoneEl,
      dropzoneText: dropzoneEl ? dropzoneEl.innerText : null
    };
  });

  console.log('[*] Dropzone details:', JSON.stringify(dropzone, null, 2));
})();
