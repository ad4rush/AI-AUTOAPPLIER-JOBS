(async () => {
  const task = await taskSpace('inspect_google_job_' + Date.now());
  const page = task.page('p1');
  const url = 'https://www.google.com/about/careers/applications/apply?jobId=CiUAL2FckbiVZ5aPageEkamtmEIah3UsXNkZWm1fXOEwlJALAVhYEjsA9yzvgt58EL5acok1zFyvAn_LJVw1uXP23SMLt_LnZAYOxHtyhEL0ixMk556iCGczjwZtlGBsz2Ph8A%3D%3D_V2&loc=IN&title=Software+Engineer&target_level=EARLY&target_level=INTERN_AND_APPRENTICE&location=India&sort_by=date';

  console.log('[*] Navigating to Google Careers URL...');
  await page.goto(url, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(6000);

  const title = await page.title();
  const currentUrl = await page.url();
  console.log('[*] Page title:', title);
  console.log('[*] Current URL:', currentUrl);

  const bodyText = await page.evaluate(() => document.body.innerText);
  console.log('[*] Body text length:', bodyText.length);

  const fs = require('fs');
  fs.writeFileSync('./data/google_swe_job_details.txt', bodyText, 'utf8');
  console.log('[✓] Wrote Google job details to ./data/google_swe_job_details.txt');
})();
