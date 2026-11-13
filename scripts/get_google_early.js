(async () => {
  const task = await taskSpace('inspect_google_job_' + Date.now());
  const page = task.page('p1');
  const searchUrl = 'https://www.google.com/about/careers/applications/jobs/results/?location=India&target_level=EARLY&title=Software%20Engineer&sort_by=date';

  console.log('[*] Navigating to Google Early Career Software Engineer roles in India...');
  await page.goto(searchUrl, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(6000);

  const text = await page.evaluate(() => document.body.innerText);
  console.log('[*] Page text:');
  console.log(text.slice(0, 4000));

  const fs = require('fs');
  fs.writeFileSync('./data/google_early_career_jobs.txt', text, 'utf8');
})();
