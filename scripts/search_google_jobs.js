(async () => {
  const task = await taskSpace('inspect_google_job_' + Date.now());
  const page = task.page('p1');
  const searchUrl = 'https://www.google.com/about/careers/applications/jobs/results/?q=Software%20Engineer&location=India&sort_by=date&target_level=EARLY&target_level=INTERN_AND_APPRENTICE';

  console.log('[*] Navigating to Google Careers search results...');
  await page.goto(searchUrl, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(6000);

  const jobs = await page.evaluate(() => {
    const cards = Array.from(document.querySelectorAll('[data-job-id], li[class*="results"], [role="listitem"]'));
    return cards.map(c => c.innerText).filter(t => t.includes('Software Engineer') || t.includes('India'));
  });

  console.log('[*] Found job cards count:', jobs.length);
  const fs = require('fs');
  fs.writeFileSync('./data/google_search_results.txt', JSON.stringify(jobs.slice(0, 10), null, 2), 'utf8');
  console.log('[✓] Wrote search results to ./data/google_search_results.txt');
})();
