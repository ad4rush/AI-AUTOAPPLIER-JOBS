(async () => {
  const task = await taskSpace('inspect_apple_job_' + Date.now());
  const page = task.page('p1');
  console.log('[*] Navigating to Apple job URL...');
  await page.goto('https://jobs.apple.com/en-us/details/200694246-1052?board=17682', { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForTimeout(5000);

  const title = await page.title();
  const url = await page.url();
  console.log('[*] Page title:', title);
  console.log('[*] Resolved URL:', url);

  const jdText = await page.evaluate(() => {
    return document.body.innerText;
  });

  console.log('[*] Body text length:', jdText.length);
  const fs = require('fs');
  fs.writeFileSync('./data/apple_rohit_job_details.txt', jdText, 'utf8');
  console.log('[✓] Wrote job details to ./data/apple_rohit_job_details.txt');
})();
