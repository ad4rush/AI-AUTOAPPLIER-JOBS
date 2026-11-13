(async () => {
  for (const prof of ['Profile 1', 'Profile 2']) {
    try {
      const task = await taskSpace('check_rw_' + prof.replace(' ', '_'), { profileId: prof });
      const page = task.page('p1');
      console.log(`[*] Checking ResumeWorded on ${prof}...`);
      await page.goto('https://resumeworded.com/results-v2.php', { waitUntil: 'domcontentloaded', timeout: 25000 });
      await new Promise(r => setTimeout(r, 4000));
      console.log(`[${prof}] URL:`, await page.url());
      console.log(`[${prof}] Title:`, await page.title());
      const text = await page.evaluate(() => document.body.innerText.slice(0, 300));
      console.log(`[${prof}] Text snippet:`, text.replace(/\n+/g, ' '));
    } catch (e) {
      console.log(`[${prof}] Error:`, e.message);
    }
  }
})();
