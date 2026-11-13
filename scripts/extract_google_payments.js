(async () => {
  const task = await taskSpace('inspect_google_job_' + Date.now());
  const page = task.page('p1');
  const searchUrl = 'https://www.google.com/about/careers/applications/jobs/results/?location=India&target_level=EARLY&title=Software%20Engineer&sort_by=date';

  await page.goto(searchUrl, { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(4000);

  // Click on "Learn more" under Software Engineer, Payments or find its link
  const jobLink = await page.evaluate(() => {
    const titles = Array.from(document.querySelectorAll('h2, h3, [role="heading"]'));
    const paymentHeading = titles.find(h => h.innerText.includes('Software Engineer, Payments'));
    if (!paymentHeading) return null;
    const container = paymentHeading.closest('li, [role="listitem"], div[class*="item"]');
    const link = container ? container.querySelector('a[href*="jobs/results"]') : null;
    return link ? link.href : null;
  });

  console.log('[*] Found job link:', jobLink);
  if (jobLink) {
    await page.goto(jobLink, { waitUntil: 'networkidle', timeout: 45000 });
    await page.waitForTimeout(4000);
    const fullText = await page.evaluate(() => document.body.innerText);
    const fs = require('fs');
    fs.writeFileSync('./data/google_payments_swe_jd.txt', fullText, 'utf8');
    console.log('[✓] Successfully extracted full Google Payments SWE JD!');
  } else {
    // If no direct link, extract the card text
    console.log('[!] Could not find direct link, dumping page text');
  }
})();
