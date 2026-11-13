(async () => {
  const task = await taskSpace('inspect_google_job_' + Date.now());
  const page = task.page('p1');
  const searchUrl = 'https://www.google.com/about/careers/applications/jobs/results/?q=Software%20Engineer&location=India&sort_by=date';

  console.log('[*] Navigating to Google Careers search results...');
  await page.goto(searchUrl, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(5000);

  const text = await page.evaluate(() => document.body.innerText);
  console.log('[*] Page text snippet (length ' + text.length + '):');
  console.log(text.slice(0, 3000));
})();
